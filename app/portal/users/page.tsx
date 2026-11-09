import {redirect} from "next/navigation";
import {createClient} from "../../../lib/supabase/server";
import UserManager from "../../components/UserManager";

// The company admin's Users page: add Viewers and Editors, within the places the licence allows.
export default async function Users({searchParams}: {searchParams: Promise<{organization?: string}>}) {
  const supabase = await createClient();
  const {data: {user}} = await supabase.auth.getUser();
  if (!user) redirect("/login");
  if (user.user_metadata?.must_change_password) redirect("/account/password");
  const {organization} = await searchParams;
  let org = "", role = "";
  if (organization) {
    const {data: sa} = await supabase.from("super_admins").select("user_id").eq("user_id", user.id).maybeSingle();
    if (!sa || !/^[0-9a-f-]{36}$/i.test(organization)) redirect("/unauthorized");
    org = organization; role = "super";
  } else {
    const {data: m} = await supabase.from("organization_members").select("organization_id,role").eq("user_id", user.id).limit(1).maybeSingle();
    if (!m) redirect("/onboarding");
    org = m.organization_id; role = m.role;
  }
  const {data: o} = await supabase.from("organizations").select("name").eq("id", org).maybeSingle();
  const manager = role === "super" || role === "owner" || role === "admin";
  return <main className="shell">
    <div className="portalTop"><div><p className="eyebrow">USERS</p><h1>{o?.name || "Your company"}</h1>
      <p className="muted">Who can sign in to your portal. <b>Editors</b> can change cameras, sites and PCs; <b>Viewers</b> can only look.</p></div>
      <div className="portalActions"><a className="ghost" href={organization ? `/portal?organization=${organization}` : "/portal"}>Back to portal</a></div></div>
    {manager ? <article className="card"><UserManager orgId={org}/></article>
      : <article className="card"><p className="muted">Only your company&apos;s admin can add or change users.</p></article>}
  </main>;
}
