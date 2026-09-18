import {redirect} from "next/navigation";
import {createClient} from "../../lib/supabase/server";
import FeatureToggle from "./FeatureToggle";

const FEATURES=[
 ["camera_ai","Camera AI"],["face_ai","Face AI"],["lpr","LPR"],
 ["drone_live","Drone Live"],["drone_ai","Drone AI"],["drone_tracking","Drone Tracking"]
] as const;

function heartbeat(last:string|null){
 if(!last)return "Never";
 const sec=Math.max(0,Math.floor((Date.now()-new Date(last).getTime())/1000));
 if(sec<90)return `${sec}s ago`;
 if(sec<3600)return `${Math.floor(sec/60)}m ago`;
 return `${Math.floor(sec/3600)}h ago`;
}

export default async function Admin(){
 const supabase=await createClient();
 const {data:{user}}=await supabase.auth.getUser();
 if(!user)redirect("/login");
 const {data:admin}=await supabase.from("super_admins").select("user_id").eq("user_id",user.id).maybeSingle();
 if(!admin)redirect("/unauthorized");

 const [{data:orgs},{data:subs},{data:devices},{data:entitlements},{data:planFeatures}]=await Promise.all([
  supabase.from("organizations").select("id,name,slug,plan_code,status").order("created_at",{ascending:false}),
  supabase.from("subscriptions").select("organization_id,plan_code,status,current_period_end"),
  supabase.from("edge_devices").select("id,organization_id,device_name,status,last_seen_at,app_version"),
  supabase.from("feature_entitlements").select("organization_id,feature_key,enabled,limit_value,source"),
  supabase.from("plan_features").select("plan_code,feature_key,enabled,limit_value")
 ]);
 const subscriptions=subs??[], edgeDevices=devices??[], overrides=entitlements??[], defaults=planFeatures??[];
 const now=Date.now();
 const isOnline=(d:any)=>d.status==="online"&&!!d.last_seen_at&&(now-new Date(d.last_seen_at).getTime())<90000;

 return <main className="shell">
  <div className="brand">AI SECURITY COMMAND CENTER</div><h1>Super Admin</h1>
  <span className="badge ok">AUTHORIZED</span><p className="muted">Signed in as {user.email}</p>
  <section className="grid">
   <article className="card"><h2>Customers</h2><strong>{orgs?.length??0}</strong><p className="muted">Organizations</p></article>
   <article className="card"><h2>Subscriptions</h2><strong>{subscriptions.length}</strong><p className="muted">Subscription records</p></article>
   <article className="card"><h2>Devices</h2><strong>{edgeDevices.length}</strong><p className="muted">{edgeDevices.filter(isOnline).length} online now</p></article>
   <article className="card"><h2>Overrides</h2><strong>{overrides.length}</strong><p className="muted">Feature entitlements</p></article>
  </section>

  <h2>Customers & Devices</h2>
  <section className="grid">{(orgs??[]).map(o=>{
   const sd=subscriptions.find(s=>s.organization_id===o.id);
   const ds=edgeDevices.filter(d=>d.organization_id===o.id);
   const plan=sd?.plan_code??o.plan_code;
   return <article className="card" key={o.id}>
    <h2>{o.name}</h2><p className="muted">{o.slug}</p>
    <p>Plan: <b>{plan}</b> · Status: <span className="ok">{sd?.status??o.status}</span></p>
    <h3>Devices</h3>
    {ds.length?ds.map(d=><div key={d.id} style={{marginBottom:12,paddingBottom:10,borderBottom:"1px solid #17384a"}}>
      <b>{d.device_name}</b> · <span className={isOnline(d)?"ok":"muted"}>{isOnline(d)?"ONLINE":"OFFLINE"}</span>
      <div className="muted">Heartbeat: {heartbeat(d.last_seen_at)} · Version: {d.app_version??"unknown"}</div>
    </div>):<p className="muted">No devices enrolled.</p>}
    <h3>Feature Controls</h3>
    {FEATURES.map(([key,label])=>{
      const ov=overrides.find(e=>e.organization_id===o.id&&e.feature_key===key);
      const def=defaults.find(e=>e.plan_code===plan&&e.feature_key===key);
      const effective=ov?.enabled??def?.enabled??false;
      return <p key={key}>{label}: <FeatureToggle orgId={o.id} feature={key} initial={effective}/> <span className="muted">{ov?"manual override":"plan default"}</span></p>
    })}
   </article>
  })}</section>
 </main>
}