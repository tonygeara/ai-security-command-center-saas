import {redirect} from "next/navigation";
import {createClient} from "../../lib/supabase/server";
import SignOut from "../SignOut";
import SubscriptionControls from "../admin/SubscriptionControls";
import PairDevice from "./PairDevice";
import UpgradePlans from "./UpgradePlans";

export default async function Portal({searchParams}:{searchParams:Promise<{organization?:string}>}){
 const supabase=await createClient(); const {data:{user}}=await supabase.auth.getUser(); if(!user)redirect("/login");
 if(user.user_metadata?.must_change_password)redirect("/account/password");
 const {organization}=await searchParams;
 let member:{organization_id:string;role:string}|null=null;
 if(organization){const {data:admin}=await supabase.from("super_admins").select("user_id").eq("user_id",user.id).maybeSingle();if(!admin)redirect("/unauthorized");if(!/^[0-9a-f-]{36}$/i.test(organization))redirect("/admin");member={organization_id:organization,role:"Super admin"};}else{const {data:membership}=await supabase.from("organization_members").select("organization_id,role").eq("user_id",user.id).limit(1).maybeSingle(); member=membership;} if(!member)redirect("/onboarding");
 const [{data:org},{data:sub},{data:devices},{data:sources},{data:features},{data:site}]=await Promise.all([
  supabase.from("organizations").select("id,name,plan_code,status").eq("id",member.organization_id).single(),
  supabase.from("subscriptions").select("plan_code,status,current_period_end,cancel_at_period_end,cancellation_effective_at,provider_subscription_id").eq("organization_id",member.organization_id).maybeSingle(),
  supabase.from("edge_devices").select("id,device_name,status,last_seen_at,app_version").eq("organization_id",member.organization_id),
  supabase.from("video_sources").select("id,name,source_type,enabled").eq("organization_id",member.organization_id),
  supabase.from("feature_entitlements").select("feature_key,enabled,source").eq("organization_id",member.organization_id),
  supabase.from("sites").select("id,name").eq("organization_id",member.organization_id).limit(1).maybeSingle()
 ]);
 if(!org)redirect(organization?"/admin":"/onboarding");
 const plan=(sub?.plan_code??org?.plan_code??"trial").toUpperCase(); const online=devices?.filter(d=>d.status==="online").length??0;
 return <main className="shell"><div className="brand">AI SECURITY COMMAND CENTER</div>
 <div className="portalTop"><div><p className="eyebrow">CUSTOMER PORTAL</p><h1>{org?.name}</h1><p className="muted">{user.email} · {({owner:"Admin",admin:"Admin",member:"Editor",viewer:"Viewer"} as Record<string,string>)[member.role]||member.role}</p></div><div className="portalActions">{!organization&&<a className="btn" href="http://127.0.0.1:8081">Open Command Center</a>}<a className="ghost" href="/portal/incidents">Incidents &amp; live view</a>{["owner","admin","Super admin"].includes(member.role)&&<a className="ghost" href={organization?`/portal/users?organization=${organization}`:"/portal/users"}>Users</a>}<a className="ghost" href="#devices">Devices</a><SignOut/></div></div>
 {organization&&<aside className="card"><b>Super admin · managing {org.name}</b><p>This dashboard is scoped to this customer. Camera discovery and live video run on their paired Windows agent.</p><a className="ghost" href="/admin">Back to all customers</a></aside>}<section className="grid"><article className="card"><h2>Edge Agent</h2><strong className={online?"ok":"muted"}>{online?"Connected":"Offline"}</strong><p className="muted">{online} online Windows agent{online===1?"":"s"}</p></article>
 <article className="card"><h2>Plan</h2><strong>{plan}</strong><p className="muted">{sub?.status??org?.status}</p></article>
 <article className="card"><h2>Video devices</h2><strong>{sources?.length??0}</strong><p className="muted">{sources?.filter(s=>s.enabled).length??0} enabled</p></article>
 <article className="card"><h2>AI controls</h2><strong>{features?.filter(f=>f.enabled).length??0}</strong><p className="muted">manual feature overrides</p></article></section>
 {!organization&&<section className="card commandCard"><div><p className="eyebrow">LOCAL COMMAND CENTER</p><h2>Live cameras, AI events, people, vehicles & drones</h2><p className="muted">The Windows Edge Agent keeps video and camera credentials local. Open the Command Center on the computer running the agent to scan nearby cameras or connect your drone.</p></div><a className="btn" href="http://127.0.0.1:8081">Launch dashboard →</a><a className="ghost" href="https://downloads.aisecuritycommandcenter.com/">Get latest release</a></section>}
 <h2 id="devices">Devices</h2><section className="grid">{(sources??[]).map(s=><article className="card" key={s.id}><span className="badge">{s.source_type.toUpperCase()}</span><h2>{s.name}</h2><p className={s.enabled?"ok":"muted"}>{s.enabled?"Enabled":"Disabled"}</p></article>)}</section>
 {["owner","admin","Super admin"].includes(member.role)&&<><h2>Pair a Windows Edge Agent</h2><article className="card"><p className="muted">Generate a one-time pairing code. Camera passwords remain on the Windows machine and are never stored in this portal.</p><PairDevice orgId={member.organization_id} siteId={site?.id}/></article>
 <h2>Subscription</h2>{organization?<SubscriptionControls orgId={org.id} initialPlan={sub?.plan_code??org.plan_code} initialStatus={org.status} paid={!!sub?.provider_subscription_id}/>:<UpgradePlans currentPlan={sub?.plan_code??org?.plan_code??"trial"}/>}</>}</main>
}
