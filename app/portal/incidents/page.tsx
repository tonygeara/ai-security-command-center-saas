import {redirect} from "next/navigation";
import {createClient} from "../../../lib/supabase/server";
import LiveView from "./LiveView";

// Phone access: incidents from the customer's Windows edge agent, and live pictures of a camera.
// The edge agent sends these only when "Phone access" is on in its Settings → System.
const LEVEL: Record<string, string> = {activity: "Activity", unknown: "Unknown face/plate", response: "Drone response"};

export default async function Incidents() {
  const supabase = await createClient();
  const {data: {user}} = await supabase.auth.getUser();
  if (!user) redirect("/login");
  if (user.user_metadata?.must_change_password) redirect("/account/password");
  const {data: member} = await supabase.from("organization_members").select("organization_id").eq("user_id", user.id).limit(1).maybeSingle();
  if (!member) redirect("/onboarding");
  const org = member.organization_id as string;
  const [{data: incidents}, {data: cams}, {data: devices}] = await Promise.all([
    supabase.from("remote_incidents").select("id,device_id,camera,title,level,severity,status,started_at,updated_at,items,photo_path")
      .eq("organization_id", org).order("updated_at", {ascending: false}).limit(50),
    supabase.from("remote_cameras").select("device_id,cameras,updated_at").eq("organization_id", org),
    supabase.from("edge_devices").select("id,device_name,status").eq("organization_id", org),
  ]);
  const paths = (incidents || []).map(i => i.photo_path).filter(Boolean) as string[];
  const signed: Record<string, string> = {};
  if (paths.length) {
    const {data} = await supabase.storage.from("edge-pictures").createSignedUrls(paths, 3600);
    for (const s of data || []) if (s.path && s.signedUrl) signed[s.path] = s.signedUrl;
  }
  const names: Record<string, string> = Object.fromEntries((devices || []).map(d => [d.id, d.device_name || "Edge agent"]));
  const t = (iso: string) => new Date(iso).toLocaleString("en-GB", {dateStyle: "medium", timeStyle: "short"});
  return <main className="shell phone">
    <div className="portalTop"><div><p className="eyebrow">PHONE ACCESS</p><h1>Incidents</h1>
      <p className="muted">Unknown faces and plates and drone responses from your site, and live pictures of your cameras.</p></div>
      <div className="portalActions"><a className="ghost" href="/portal">Back to portal</a></div></div>
    <h2>Live view</h2>
    {(cams || []).length === 0 ?
      <article className="card"><p className="muted">No cameras yet. Turn on <b>Phone access</b> in the Command Center on your PC (Settings → System).</p></article> :
      (cams || []).map(c => <article className="card" key={c.device_id}><h3>{names[c.device_id] || "Edge agent"}</h3>
        <LiveView orgId={org} deviceId={c.device_id} cameras={c.cameras || []}/></article>)}
    <h2>Recent incidents</h2>
    {(incidents || []).length === 0 && <article className="card"><p className="muted">No incidents received yet.</p></article>}
    <section className="incList">{(incidents || []).map(i => <article className={`card inc sev${i.severity}`} key={i.id}>
      <div className="incHead"><span className="badge">{LEVEL[i.level] || i.level}</span><span className="muted">{t(i.updated_at)}</span></div>
      <h3>{i.title}</h3>
      {i.photo_path && signed[i.photo_path] && <img className="incPhoto" src={signed[i.photo_path]} alt={`Snapshot from ${i.camera}`}/>}
      <details><summary>Timeline ({(i.items || []).length})</summary><ul>{(i.items || []).map((x: {t: number, text: string}, k: number) =>
        <li key={k}><span className="muted">{new Date(x.t * 1000).toLocaleTimeString("en-GB", {timeStyle: "short"})}</span> {x.text}</li>)}</ul></details>
      <p className="muted small">{names[i.device_id] || "Edge agent"} · camera {i.camera} · {i.status}</p>
    </article>)}</section>
  </main>;
}
