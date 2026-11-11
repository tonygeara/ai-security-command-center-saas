// Portal users: who may create, change and remove whom. Called by the portal with the signed-in user's
// session (Authorization header); does the work with the service role.
//
//   Super admin   everything, every client: create a client with its admin, add/change/remove any user.
//   Client admin  (role owner/admin) their own company only: Viewers and Editors, within the licence's
//                 user places, while the account and licence are in good standing.
//   Editor/Viewer cannot manage users.
//
// Actions (POST JSON):
//   {action:"list", org}                                  -> members with email, name, role, last sign-in; seats
//   {action:"create", org, email, full_name, role}        -> {temp_password}
//   {action:"set_role", org, user_id, role}
//   {action:"reset_password", org, user_id}               -> {temp_password}
//   {action:"remove", org, user_id}
//   {action:"create_client", name, admin_email, admin_name, plan?, status?}   (super admin) -> {org, temp_password}
//
// Super admin only, any account whatever its company (Admin → Users):
//   {action:"account_list"}                               -> every account with blocked / super admin flags
//   {action:"account_block", user_id, blocked}            block or allow sign-in
//   {action:"account_update", user_id, full_name?, email?}
//   {action:"account_password", user_id}                  -> {temp_password}
//   {action:"account_super", user_id, on}                 give or take super admin rights (never your own)
//   {action:"account_add_super", email}                   make an existing account a super admin
//   {action:"account_delete", user_id}                    delete the account and its company memberships
//
// New users and reset passwords get a temporary password, shown once to the person who made it; the user
// must choose their own at first sign-in (user_metadata.must_change_password).
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import {createClient, SupabaseClient} from "npm:@supabase/supabase-js@2";

const origins = new Set(["https://www.aisecuritycommandcenter.com", "https://aisecuritycommandcenter.com",
  "https://ai-security-command-center-saas.vercel.app", "http://localhost:3000"]);
const ADMIN = ["owner", "admin"], ALL_ROLES = ["admin", "member", "viewer"], CLIENT_ADMIN_ROLES = ["member", "viewer"];
const ROLE_NAME: Record<string, string> = {owner: "Admin", admin: "Admin", member: "Editor", viewer: "Viewer"};
const text = (v: unknown, max = 200) => (typeof v === "string" ? v.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, max) : "");
const isUuid = (v: unknown) => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);

class Refused extends Error { constructor(msg: string, public status = 400) { super(msg); } }

function tempPassword() {
  const abc = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";  // no 0/O, 1/l/I
  const bytes = crypto.getRandomValues(new Uint8Array(14));
  const s = Array.from(bytes, b => abc[b % abc.length]).join("");
  return `${s.slice(0, 4)}-${s.slice(4, 9)}-${s.slice(9)}`;
}

async function roleIn(admin: SupabaseClient, org: string, user: string) {
  const {data} = await admin.from("organization_members").select("role").eq("organization_id", org).eq("user_id", user).maybeSingle();
  return (data?.role as string) || null;
}

async function adminsLeft(admin: SupabaseClient, org: string, without: string) {
  const {count} = await admin.from("organization_members").select("user_id", {count: "exact", head: true})
    .eq("organization_id", org).in("role", ADMIN).neq("user_id", without);
  return count || 0;
}

async function audit(admin: SupabaseClient, org: string | null, actor: string, action: string, target: string, meta: Record<string, unknown>) {
  await admin.from("audit_logs").insert({organization_id: org, actor_user_id: actor, action, target_type: "user", target_id: target, metadata: meta});
}

async function findUserByEmail(admin: SupabaseClient, email: string) {
  for (let page = 1; page <= 10; page++) {
    const {data, error} = await admin.auth.admin.listUsers({page, perPage: 1000});
    if (error) throw error;
    const u = data.users.find(x => (x.email || "").toLowerCase() === email);
    if (u) return u;
    if (data.users.length < 1000) return null;
  }
  return null;
}

// Make (or reuse) the account and add it to the company with that role.
async function addUser(admin: SupabaseClient, org: string, email: string, fullName: string, role: string) {
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) throw new Refused("Enter a valid email address.");
  const password = tempPassword();
  let userId: string, temp: string | null = password;
  const made = await admin.auth.admin.createUser({email, password, email_confirm: true,
    user_metadata: {full_name: fullName || email, must_change_password: true}});
  if (made.error) {
    const existing = await findUserByEmail(admin, email);
    if (!existing) throw new Refused(made.error.message);
    const {data: other} = await admin.from("organization_members").select("organization_id").eq("user_id", existing.id).limit(1);
    if (other && other.length) {
      throw new Refused(other[0].organization_id === org ? "This person is already a user of this company."
        : "This email already belongs to another company's account.");
    }
    userId = existing.id; temp = null;  // an account with no company yet: keep its password
  } else {
    userId = made.data.user!.id;
  }
  const {error} = await admin.from("organization_members").insert({organization_id: org, user_id: userId, role});
  if (error) {
    if (temp) await admin.auth.admin.deleteUser(userId);
    throw new Refused(error.message, 500);
  }
  return {userId, temp};
}

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("Origin") || "";
  const headers = {"Content-Type": "application/json", "Access-Control-Allow-Origin": origins.has(origin) ? origin : "https://www.aisecuritycommandcenter.com",
    "Access-Control-Allow-Headers": "authorization,x-client-info,apikey,content-type", "Access-Control-Allow-Methods": "POST,OPTIONS", "Vary": "Origin"};
  const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status, headers});
  if (origin && !origins.has(origin)) return reply({error: "Origin not allowed"}, 403);
  if (req.method === "OPTIONS") return new Response(null, {status: 204, headers});
  if (req.method !== "POST") return reply({error: "Method not allowed"}, 405);

  try {
    const auth = req.headers.get("Authorization");
    if (!auth) throw new Refused("Sign in required", 401);
    const asUser = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!, {global: {headers: {Authorization: auth}}});
    const {data: {user}, error: authError} = await asUser.auth.getUser();
    if (authError || !user) throw new Refused("Sign in required", 401);
    const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {auth: {persistSession: false}});
    const {data: sa} = await admin.from("super_admins").select("user_id").eq("user_id", user.id).maybeSingle();
    const isSuper = !!sa;
    const body = await req.json().catch(() => ({})) as Record<string, unknown>;
    const action = text(body.action, 30);

    if (action === "create_client") {
      if (!isSuper) throw new Refused("Super admin only.", 403);
      const name = text(body.name, 120), email = text(body.admin_email, 200).toLowerCase(), adminName = text(body.admin_name, 120);
      const plan = text(body.plan, 40) || "trial", status = text(body.status, 20) || "trial";
      if (name.length < 2) throw new Refused("Enter the client's name.");
      if (!["active", "trial"].includes(status)) throw new Refused("Status must be active or trial.");
      if (plan !== "trial") {
        const {data: p} = await admin.from("plans").select("code").eq("code", plan).eq("active", true).maybeSingle();
        if (!p) throw new Refused("Unknown plan.");
      }
      const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") + "-" + crypto.randomUUID().slice(0, 6);
      const {data: o, error: oe} = await admin.from("organizations").insert({name, slug, plan_code: plan, status}).select("id").single();
      if (oe || !o) throw new Refused(oe?.message || "Could not create the client.", 500);
      try {
        await admin.from("subscriptions").insert({organization_id: o.id, plan_code: plan, status, provider: "manual"});
        await admin.from("sites").insert({organization_id: o.id, name: "Main Site"});
        const r = await addUser(admin, o.id, email, adminName, "admin");
        await audit(admin, o.id, user.id, "client_created", o.id, {client: name, admin: email, plan, status});
        return reply({ok: true, org: o.id, user_id: r.userId, temp_password: r.temp});
      } catch (e) {
        await admin.from("organizations").delete().eq("id", o.id);  // nothing half-made is left behind
        throw e;
      }
    }

    // Super admin: any account, whatever company it belongs to (Admin → Users).
    if (action.startsWith("account_")) {
      if (!isSuper) throw new Refused("Super admin only.", 403);
      if (action === "account_list") {
        const all: Record<string, unknown>[] = [];
        for (let page = 1; page <= 10; page++) {
          const {data, error} = await admin.auth.admin.listUsers({page, perPage: 1000});
          if (error) throw new Refused(error.message, 500);
          all.push(...data.users.map(u => ({user_id: u.id, email: u.email || "", banned_until: (u as {banned_until?: string}).banned_until || null,
            must_change_password: !!u.user_metadata?.must_change_password})));
          if (data.users.length < 1000) break;
        }
        const {data: supers} = await admin.from("super_admins").select("user_id");
        const ids = new Set((supers || []).map(s => s.user_id));
        const now = Date.now();
        return reply({ok: true, me: user.id, accounts: all.map(a => ({...a, super: ids.has(a.user_id as string),
          blocked: !!a.banned_until && new Date(a.banned_until as string).getTime() > now}))});
      }
      if (action === "account_add_super") {
        const email = text(body.email, 200).toLowerCase();
        const u = await findUserByEmail(admin, email);
        if (!u) throw new Refused("No account with that email. Add them to a client first, or create the account, then make them a super admin.", 404);
        const {error} = await admin.from("super_admins").upsert({user_id: u.id});
        if (error) throw new Refused(error.message, 500);
        await audit(admin, null, user.id, "super_admin_added", u.id, {email});
        return reply({ok: true});
      }
      const target = body.user_id;
      if (!isUuid(target)) throw new Refused("Choose a user.");
      if (target === user.id) throw new Refused("You can't change your own account here. Use Account for your password.", 403);
      const {data: cur} = await admin.auth.admin.getUserById(target as string);
      if (!cur?.user) throw new Refused("That account no longer exists.", 404);
      const email = cur.user.email;
      const {data: targetSuper} = await admin.from("super_admins").select("user_id").eq("user_id", target).maybeSingle();

      if (action === "account_block") {
        const blocked = body.blocked === true;
        const {error} = await admin.auth.admin.updateUserById(target as string, {ban_duration: blocked ? "876000h" : "none"});
        if (error) throw new Refused(error.message, 500);
        await audit(admin, null, user.id, blocked ? "user_blocked" : "user_unblocked", target as string, {email});
        return reply({ok: true});
      }
      if (action === "account_update") {
        const fullName = text(body.full_name, 120), newEmail = text(body.email, 200).toLowerCase();
        const change: Record<string, unknown> = {};
        if (newEmail && newEmail !== email) {
          if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(newEmail)) throw new Refused("Enter a valid email address.");
          change.email = newEmail; change.email_confirm = true;
        }
        if (fullName) change.user_metadata = {...(cur.user.user_metadata || {}), full_name: fullName};
        if (Object.keys(change).length) {
          const {error} = await admin.auth.admin.updateUserById(target as string, change);
          if (error) throw new Refused(error.message, 400);
        }
        if (fullName) await admin.from("profiles").update({full_name: fullName}).eq("id", target);
        await audit(admin, null, user.id, "user_updated", target as string, {email, new_email: change.email ?? null, full_name: fullName || null});
        return reply({ok: true});
      }
      if (action === "account_password") {
        const password = tempPassword();
        const {error} = await admin.auth.admin.updateUserById(target as string,
          {password, user_metadata: {...(cur.user.user_metadata || {}), must_change_password: true}});
        if (error) throw new Refused(error.message, 500);
        await audit(admin, null, user.id, "user_password_reset", target as string, {email});
        return reply({ok: true, temp_password: password});
      }
      if (action === "account_super") {
        const on = body.on === true;
        if (on) {
          const {error} = await admin.from("super_admins").upsert({user_id: target});
          if (error) throw new Refused(error.message, 500);
        } else {
          const {error} = await admin.from("super_admins").delete().eq("user_id", target);
          if (error) throw new Refused(error.message, 500);
        }
        await audit(admin, null, user.id, on ? "super_admin_added" : "super_admin_removed", target as string, {email});
        return reply({ok: true});
      }
      if (action === "account_delete") {
        if (targetSuper) throw new Refused("Remove their super admin rights first.", 403);
        const {data: orgs} = await admin.from("organization_members").select("organization_id,role").eq("user_id", target);
        for (const m of orgs || []) {
          if (ADMIN.includes(m.role) && await adminsLeft(admin, m.organization_id, target as string) === 0) {
            const {data: o} = await admin.from("organizations").select("name").eq("id", m.organization_id).maybeSingle();
            throw new Refused(`${o?.name || "Their company"} needs at least one admin. Add another admin there first.`);
          }
        }
        await admin.from("organization_members").delete().eq("user_id", target);
        const {error} = await admin.auth.admin.deleteUser(target as string);
        if (error) throw new Refused(error.message, 500);
        await audit(admin, null, user.id, "user_deleted", target as string, {email});
        return reply({ok: true});
      }
      throw new Refused("Unknown action.");
    }

    const org = body.org;
    if (!isUuid(org)) throw new Refused("Choose a company.");
    const myRole = await roleIn(admin, org as string, user.id);
    const isClientAdmin = !!myRole && ADMIN.includes(myRole);
    if (!isSuper && !isClientAdmin) throw new Refused("Only the company's admin can manage users.", 403);

    if (action === "list") {
      const {data: members} = await admin.from("organization_members").select("user_id,role,created_at").eq("organization_id", org);
      const ids = (members || []).map(m => m.user_id);
      const {data: profiles} = ids.length ? await admin.from("profiles").select("id,full_name").in("id", ids) : {data: []};
      const users = await Promise.all((members || []).map(async m => {
        const {data} = await admin.auth.admin.getUserById(m.user_id);
        const u = data?.user;
        return {user_id: m.user_id, role: m.role, role_name: ROLE_NAME[m.role] || m.role, email: u?.email || "",
                full_name: profiles?.find(p => p.id === m.user_id)?.full_name || "", last_sign_in_at: u?.last_sign_in_at || null,
                must_change_password: !!u?.user_metadata?.must_change_password, is_me: m.user_id === user.id,
                can_manage: isSuper ? m.user_id !== user.id : CLIENT_ADMIN_ROLES.includes(m.role)};
      }));
      const {data: seats} = await admin.rpc("org_user_allowance", {target_org: org});
      return reply({ok: true, users, seats: seats?.[0] || null, roles: isSuper ? ALL_ROLES : CLIENT_ADMIN_ROLES, super: isSuper});
    }

    if (action === "create") {
      const role = text(body.role, 20), email = text(body.email, 200).toLowerCase(), fullName = text(body.full_name, 120);
      if (!(isSuper ? ALL_ROLES : CLIENT_ADMIN_ROLES).includes(role)) throw new Refused(isSuper ? "Choose a role." : "Admins can add Viewers and Editors.", 403);
      if (!isSuper) {
        const {data: seats} = await admin.rpc("org_user_allowance", {target_org: org});
        if (!seats?.[0]?.can_add) throw new Refused(seats?.[0]?.reason || "No user places left.", 403);
      }
      const r = await addUser(admin, org as string, email, fullName, role);
      await audit(admin, org as string, user.id, "user_added", r.userId, {email, role: ROLE_NAME[role]});
      return reply({ok: true, user_id: r.userId, temp_password: r.temp});
    }

    const target = body.user_id;
    if (!isUuid(target)) throw new Refused("Choose a user.");
    const targetRole = await roleIn(admin, org as string, target as string);
    if (!targetRole) throw new Refused("That person is not a user of this company.", 404);
    if (target === user.id && action !== "reset_password") throw new Refused("You can't change your own access here.", 403);
    if (!isSuper && !CLIENT_ADMIN_ROLES.includes(targetRole)) throw new Refused("Only your provider can change another admin.", 403);

    if (action === "set_role") {
      const role = text(body.role, 20);
      if (!(isSuper ? ALL_ROLES : CLIENT_ADMIN_ROLES).includes(role)) throw new Refused("Admins can set Viewer or Editor.", 403);
      if (ADMIN.includes(targetRole) && !ADMIN.includes(role) && await adminsLeft(admin, org as string, target as string) === 0) {
        throw new Refused("The company needs at least one admin. Add another admin first.");
      }
      const {error} = await admin.from("organization_members").update({role}).eq("organization_id", org).eq("user_id", target);
      if (error) throw new Refused(error.message, 500);
      await audit(admin, org as string, user.id, "user_role_changed", target as string, {from: ROLE_NAME[targetRole], to: ROLE_NAME[role]});
      return reply({ok: true});
    }

    if (action === "reset_password") {
      if (target === user.id) throw new Refused("Change your own password under Account.", 400);
      const {data: cur} = await admin.auth.admin.getUserById(target as string);
      const password = tempPassword();
      const {error} = await admin.auth.admin.updateUserById(target as string,
        {password, user_metadata: {...(cur?.user?.user_metadata || {}), must_change_password: true}});
      if (error) throw new Refused(error.message, 500);
      await audit(admin, org as string, user.id, "user_password_reset", target as string, {email: cur?.user?.email});
      return reply({ok: true, temp_password: password});
    }

    if (action === "remove") {
      if (ADMIN.includes(targetRole) && await adminsLeft(admin, org as string, target as string) === 0) {
        throw new Refused("The company needs at least one admin. Add another admin first.");
      }
      const {data: cur} = await admin.auth.admin.getUserById(target as string);
      const {error} = await admin.from("organization_members").delete().eq("organization_id", org).eq("user_id", target);
      if (error) throw new Refused(error.message, 500);
      // The account existed only for this company: remove it too (never a super admin's).
      const {count} = await admin.from("organization_members").select("user_id", {count: "exact", head: true}).eq("user_id", target);
      const {data: targetSuper} = await admin.from("super_admins").select("user_id").eq("user_id", target).maybeSingle();
      if (!count && !targetSuper) await admin.auth.admin.deleteUser(target as string);
      await audit(admin, org as string, user.id, "user_removed", target as string, {email: cur?.user?.email, role: ROLE_NAME[targetRole]});
      return reply({ok: true});
    }

    throw new Refused("Unknown action.");
  } catch (e) {
    if (e instanceof Refused) return reply({error: e.message}, e.status);
    console.error(e);
    return reply({error: "Something went wrong."}, 500);
  }
});
