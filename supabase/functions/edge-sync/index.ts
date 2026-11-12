// Phone access: the Windows edge agent sends incidents and pictures here, and asks whether a phone
// wants live pictures. Authenticated by the device token (x-device-token), like edge-agent-control.
//   {action:"incidents", incidents:[...], cameras:[...]}   upsert the PC's incidents (25 at a time)
//   {action:"photo", local_id, jpeg}                        an incident's snapshot (base64 JPEG)
//   {action:"poll"}                                         -> {live:[{id, camera, seconds_left}]}
//   {action:"live", request_id, camera, jpeg}               the latest live picture for a request
//   {action:"signin", email, password}                      one sign-in: is this portal account allowed on this PC?
//        -> {ok, email, name, role: admin|operator|viewer}  (super admin and company Admin -> admin,
//           Editor -> operator, Viewer -> viewer) or {ok:false, error: bad_credentials|blocked|
//           must_change_password|not_member}
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import {createClient} from "npm:@supabase/supabase-js@2";

const BUCKET = "edge-pictures", MAX_JPEG = 1_500_000;
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), {status: s, headers: {"content-type": "application/json", "cache-control": "no-store"}});
const hex = async (s: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s))))
  .map(b => b.toString(16).padStart(2, "0")).join("");
const str = (v: unknown, n: number) => (typeof v === "string" ? v : "").slice(0, n);
const when = (v: unknown) => { const t = Number(v); return Number.isFinite(t) && t > 1e9 && t < 1e10 ? new Date(t * 1000).toISOString() : null; };

function jpeg(b64: unknown): Uint8Array | null {
  if (typeof b64 !== "string" || b64.length > MAX_JPEG * 1.4) return null;
  try {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    return bytes.length > 4 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes.length <= MAX_JPEG ? bytes : null;
  } catch { return null; }
}

Deno.serve(async req => {
  if (req.method !== "POST") return json({error: "method_not_allowed"}, 405);
  const token = req.headers.get("x-device-token") || "";
  if (token.length < 32) return json({error: "unauthorized"}, 401);
  const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const {data: d, error} = await admin.from("edge_devices").select("id,organization_id,status").eq("device_token_hash", await hex(token)).maybeSingle();
  if (error || !d || d.status === "disabled") return json({error: "unauthorized"}, 401);
  const org = d.organization_id as string, dev = d.id as string;
  const body = await req.json().catch(() => ({})) as Record<string, unknown>;

  if (body.action === "signin") {
    const email = str(body.email, 200).trim().toLowerCase(), password = str(body.password, 200);
    if (!email.includes("@") || !password) return json({ok: false, error: "bad_credentials"});
    const anon = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!, {auth: {persistSession: false}});
    const {data: s, error: e} = await anon.auth.signInWithPassword({email, password});
    if (e || !s?.user) return json({ok: false, error: /banned/i.test(e?.message || "") ? "blocked" : "bad_credentials"});
    const uid = s.user.id;
    await anon.auth.signOut({scope: "local"}).catch(() => {});  // only this check, never their other sessions
    if (s.user.user_metadata?.must_change_password) return json({ok: false, error: "must_change_password"});
    const {data: sa} = await admin.from("super_admins").select("user_id").eq("user_id", uid).maybeSingle();
    let role: string | null = sa ? "admin" : null;
    if (!role) {
      const {data: m} = await admin.from("organization_members").select("role").eq("organization_id", org).eq("user_id", uid).maybeSingle();
      role = m ? ({owner: "admin", admin: "admin", member: "operator", viewer: "viewer"} as Record<string, string>)[m.role] ?? null : null;
    }
    if (!role) return json({ok: false, error: "not_member"});
    const {data: p} = await admin.from("profiles").select("full_name").eq("id", uid).maybeSingle();
    await admin.from("audit_logs").insert({organization_id: org, actor_user_id: uid, action: "pc_signin", target_type: "edge_device",
      target_id: dev, metadata: {email, role, super_admin: !!sa}});
    return json({ok: true, email, name: p?.full_name || "", role});
  }

  if (body.action === "incidents") {
    const list = Array.isArray(body.incidents) ? body.incidents.slice(0, 25) : [];
    const rows = list.flatMap((x: Record<string, unknown>) => {
      const local = Number(x.local_id), started = when(x.started), updated = when(x.updated);
      if (!Number.isInteger(local) || !started || !updated) return [];
      const items = (Array.isArray(x.items) ? x.items.slice(-40) : []).map((i: Record<string, unknown>) =>
        ({t: Number(i.t) || 0, kind: str(i.kind, 20), text: str(i.text, 200)}));
      return [{organization_id: org, device_id: dev, local_id: local, camera: str(x.camera, 80), title: str(x.title, 200),
               level: str(x.level, 20), severity: Math.max(1, Math.min(3, Number(x.severity) || 1)), status: str(x.status, 20),
               started_at: started, updated_at: updated, items, received_at: new Date().toISOString()}];
    });
    if (rows.length) {
      const {error: e} = await admin.from("remote_incidents").upsert(rows, {onConflict: "device_id,local_id"});
      if (e) return json({error: e.message}, 500);
    }
    if (Array.isArray(body.cameras)) {
      const cameras = body.cameras.slice(0, 64).map(c => str(c, 80)).filter(Boolean);
      await admin.from("remote_cameras").upsert({device_id: dev, organization_id: org, cameras, updated_at: new Date().toISOString()});
    }
    return json({ok: true, saved: rows.length});
  }

  if (body.action === "photo") {
    const local = Number(body.local_id), bytes = jpeg(body.jpeg);
    if (!Number.isInteger(local) || !bytes) return json({error: "bad_photo"}, 400);
    const path = `${org}/${dev}/incidents/${local}.jpg`;
    const {error: e} = await admin.storage.from(BUCKET).upload(path, bytes, {contentType: "image/jpeg", upsert: true});
    if (e) return json({error: e.message}, 500);
    await admin.from("remote_incidents").update({photo_path: path}).eq("device_id", dev).eq("local_id", local);
    return json({ok: true});
  }

  if (body.action === "poll") {
    const {data} = await admin.from("live_requests").select("id,camera,active_until").eq("device_id", dev)
      .gt("active_until", new Date().toISOString()).order("requested_at", {ascending: false}).limit(8);
    const now = Date.now();
    return json({ok: true, live: (data || []).map(r => ({id: r.id, camera: r.camera,
      seconds_left: Math.max(0, Math.round((Date.parse(r.active_until) - now) / 1000))}))});
  }

  if (body.action === "live") {
    const id = str(body.request_id, 40), bytes = jpeg(body.jpeg);
    if (!bytes) return json({error: "bad_photo"}, 400);
    const {data: r} = await admin.from("live_requests").select("id,camera,active_until").eq("id", id).eq("device_id", dev).maybeSingle();
    if (!r || Date.parse(r.active_until) < Date.now()) return json({ok: false, error: "not_watching"});
    const path = `${org}/${dev}/live/${r.camera.replace(/[^\w.-]/g, "_")}.jpg`;
    const {error: e} = await admin.storage.from(BUCKET).upload(path, bytes, {contentType: "image/jpeg", upsert: true});
    if (e) return json({error: e.message}, 500);
    await admin.from("live_requests").update({last_frame_at: new Date().toISOString(), frame_path: path}).eq("id", r.id);
    return json({ok: true});
  }

  return json({error: "unknown_action"}, 400);
});
