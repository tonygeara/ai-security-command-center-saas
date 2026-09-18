import {redirect} from "next/navigation";
import {createClient} from "../../lib/supabase/server";
import FeatureToggle from "./FeatureToggle";

export default async function Admin(){
 const supabase=await createClient();
 const {data:{user}}=await supabase.auth.getUser();
 if(!user)redirect("/login");
 const {data:admin}=await supabase.from("super_admins").select("user_id").eq("user_id",user.id).maybeSingle();
 if(!admin)redirect("/unauthorized");

 const [{data:orgs},{data:subs},{data:devices},{data:entitlements}]=await Promise.all([
  supabase.from("organizations").select("id,name,slug,plan_code,status").order("created_at",{ascending:false}),
  supabase.from("subscriptions").select("organization_id,plan_code,status,current_period_end"),
  supabase.from("edge_devices").select("id,organization_id,device_name,status,last_seen_at,app_version"),
  supabase.from("feature_entitlements").select("organization_id,feature_key,enabled,limit_value,source")
 ]);
 const subscriptions=subs??[], edgeDevices=devices??[], overrides=entitlements??[];
 return <main className="shell">
  <div className="brand">AI SECURITY COMMAND CENTER</div><h1>Super Admin</h1>
  <span className="badge ok">AUTHORIZED</span><p className="muted">Signed in as {user.email}</p>
  <section className="grid">
   <article className="card"><h2>Customers</h2><strong>{orgs?.length??0}</strong><p className="muted">Organizations</p></article>
   <article className="card"><h2>Subscriptions</h2><strong>{subscriptions.length}</strong><p className="muted">Subscription records</p></article>
   <article className="card"><h2>Devices</h2><strong>{edgeDevices.length}</strong><p className="muted">{edgeDevices.filter(d=>d.status==="online").length} online</p></article>
   <article className="card"><h2>Overrides</h2><strong>{overrides.length}</strong><p className="muted">Feature entitlements</p></article>
  </section>
  <h2>Customers</h2>
  <section className="grid">{(orgs??[]).map(o=>{const sd=subscriptions.find(s=>s.organization_id===o.id);const ds=edgeDevices.filter(d=>d.organization_id===o.id);const drone=overrides.find(e=>e.organization_id===o.id&&e.feature_key==="drone_ai");return <article className="card" key={o.id}><h2>{o.name}</h2><p className="muted">{o.slug}</p><p>Plan: <b>{sd?.plan_code??o.plan_code}</b></p><p>Status: <span className="ok">{sd?.status??o.status}</span></p><p>Devices: {ds.length}</p><p>Drone AI: <FeatureToggle orgId={o.id} feature="drone_ai" initial={drone?.enabled??false}/></p></article>})}</section>
 </main>
}