import {redirect} from "next/navigation";
import {createClient} from "../../lib/supabase/server";
import PairDevice from "./PairDevice";
import UpgradePlans from "./UpgradePlans";

export default async function Portal(){
 const supabase=await createClient();
 const {data:{user}}=await supabase.auth.getUser();
 if(!user)redirect("/login");
 const {data:member}=await supabase.from("organization_members").select("organization_id,role").eq("user_id",user.id).limit(1).maybeSingle();
 if(!member)redirect("/onboarding");
 const [{data:org},{data:sub},{data:devices},{data:features},{data:site}]=await Promise.all([
  supabase.from("organizations").select("id,name,plan_code,status").eq("id",member.organization_id).single(),
  supabase.from("subscriptions").select("plan_code,status,current_period_end").eq("organization_id",member.organization_id).maybeSingle(),
  supabase.from("edge_devices").select("id,device_name,status,last_seen_at,app_version").eq("organization_id",member.organization_id),
  supabase.from("feature_entitlements").select("feature_key,enabled,source").eq("organization_id",member.organization_id),
  supabase.from("sites").select("id,name").eq("organization_id",member.organization_id).limit(1).maybeSingle()
 ]);
 return <main className="shell"><div className="brand">AI SECURITY COMMAND CENTER</div><h1>Customer Portal</h1>
 <p className="muted">{user.email} · {org?.name}</p>
 <section className="grid">
  <article className="card"><h2>Plan</h2><strong>{sub?.plan_code??org?.plan_code}</strong><p className="muted">Status: {sub?.status??org?.status}</p></article>
  <article className="card"><h2>Devices</h2><strong>{devices?.length??0}</strong><p className="muted">{devices?.filter(d=>d.status==="online").length??0} reporting online</p></article>
  <article className="card"><h2>Overrides</h2><strong>{features?.length??0}</strong><p className="muted">Managed feature settings</p></article>
 </section>
 <h2>Plans</h2><UpgradePlans/><h2>Device pairing</h2><article className="card"><PairDevice orgId={member.organization_id} siteId={site?.id}/></article><h2>Your devices</h2>
 <section className="grid">{(devices??[]).map(d=><article className="card" key={d.id}><h2>{d.device_name}</h2><p>Status: <span className={d.status==="online"?"ok":"muted"}>{d.status}</span></p><p className="muted">Version: {d.app_version??"unknown"}</p><p className="muted">Last heartbeat: {d.last_seen_at?new Date(d.last_seen_at).toLocaleString():"Never"}</p></article>)}</section>
 </main>
}