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
  supabase.from("subscriptions").select("plan_code,status,current_period_end,cancel_at_period_end,canceled_at,cancellation_effective_at").eq("organization_id",member.organization_id).maybeSingle(),
  supabase.from("edge_devices").select("id,device_name,status,last_seen_at,app_version").eq("organization_id",member.organization_id),
  supabase.from("feature_entitlements").select("feature_key,enabled,source").eq("organization_id",member.organization_id),
  supabase.from("sites").select("id,name").eq("organization_id",member.organization_id).limit(1).maybeSingle()
 ]);
 const plan=(sub?.plan_code??org?.plan_code??"trial").toUpperCase();
 const online=devices?.filter(d=>d.status==="online").length??0;
 return <main className="shell">
  <div className="brand">AI SECURITY COMMAND CENTER</div>
  <div style={{display:"flex",justifyContent:"space-between",gap:16,alignItems:"center",flexWrap:"wrap"}}>
   <div><h1 style={{marginBottom:6}}>Security Command Center</h1><p className="muted" style={{marginTop:0}}>{org?.name} · {user.email}</p></div>
   <div style={{display:"flex",gap:10}}><span className="card" style={{padding:"10px 14px"}}>Plan: <strong>{plan}</strong></span><span className="card" style={{padding:"10px 14px"}}><strong>{online}</strong> device{online===1?"":"s"} online</span></div>
  </div>
  <section className="grid">
   <article className="card"><h2>System</h2><strong className={online?"ok":"muted"}>{online?"Connected":"Waiting for Edge Agent"}</strong><p className="muted">Local-first video processing with cloud account and entitlement control.</p></article>
   <article className="card"><h2>Subscription</h2><strong>{plan}</strong><p className="muted">Status: {sub?.cancel_at_period_end?"Cancellation scheduled":sub?.status??org?.status}</p>{sub?.cancel_at_period_end&&<p className="muted">Ends {new Date(sub.cancellation_effective_at??sub.current_period_end).toLocaleDateString()}.</p>}</article>
   <article className="card"><h2>Feature controls</h2><strong>{features?.filter(f=>f.enabled).length??0} overrides active</strong><p className="muted">Features and limits are enforced by your plan and administrator settings.</p></article>
  </section>
  <h2>Windows Edge Agent</h2>
  <section className="grid">{(devices??[]).map(d=><article className="card" key={d.id}><h2>{d.device_name}</h2><p>Status: <span className={d.status==="online"?"ok":"muted"}>{d.status}</span></p><p className="muted">Version: {d.app_version??"unknown"}</p><p className="muted">Last heartbeat: {d.last_seen_at?new Date(d.last_seen_at).toLocaleString():"Never"}</p></article>)}</section>
  <h2>Add / pair a device</h2><article className="card"><p className="muted">Generate a one-time code, then enter it in the Windows customer app. Camera credentials remain on the local Windows machine.</p><PairDevice orgId={member.organization_id} siteId={site?.id}/></article>
  <h2>Manage plan</h2><UpgradePlans currentPlan={sub?.plan_code??org?.plan_code??"trial"}/>
 </main>
}