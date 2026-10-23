import Link from "next/link";
import {createClient} from "../../../lib/supabase/server";
import {buildClients, isOnline, LATEST_APP_VERSION, loadAdminData, versionBehind} from "../../../lib/admin";

export default async function Devices(){
  const data = await loadAdminData(await createClient());
  const clients = buildClients(data);
  const rows = data.devices.map(d => ({d, c: clients.find(c => c.orgId === d.organization_id), on: isOnline(d),
    srcs: data.sources.filter(s => s.edge_device_id === d.id)})).sort((a, b) => Number(a.on) - Number(b.on) || (a.c?.name ?? "").localeCompare(b.c?.name ?? ""));
  const online = rows.filter(r => r.on).length, old = rows.filter(r => versionBehind(r.d.app_version)).length;
  return <>
    <div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Devices</h1><p className="muted">Every online client's Windows PC. On-prem PCs never connect here (they run offline).</p></div></div>
    <section className="grid">
      <article className="card"><h2>Online now</h2><strong className={online < rows.length ? "locked" : "ok"}>{online}/{rows.length}</strong><p className="muted">PCs</p></article>
      <article className="card"><h2>Out of date</h2><strong className={old ? "locked" : "ok"}>{old}</strong><p className="muted">not on {LATEST_APP_VERSION}</p></article>
      <article className="card"><h2>Cameras</h2><strong>{data.sources.filter(s => s.source_type === "camera").length}</strong><p className="muted">registered</p></article>
      <article className="card"><h2>Drones</h2><strong>{data.sources.filter(s => s.source_type === "drone").length}</strong><p className="muted">registered</p></article>
    </section>
    <div className="card tableWrap"><table className="adminTable"><thead><tr><th>Client</th><th>PC</th><th>Status</th><th>Version</th><th>Cameras & drones</th></tr></thead><tbody>
      {rows.map(({d, c, on, srcs}) => <tr key={d.id}>
        <td>{c ? <Link href={"/admin/clients/" + c.key}><b>{c.name}</b></Link> : <span className="muted">unknown</span>}</td>
        <td><b>{d.device_name || "Unnamed PC"}</b><div className="muted">{d.platform} {d.last_ip ? "· " + d.last_ip : ""}</div></td>
        <td className={on ? "ok" : "locked"}>{on ? "● Online" : "○ Offline"}<div className="muted">{d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : "never connected"}</div></td>
        <td className={versionBehind(d.app_version) ? "locked" : ""}>{d.app_version || "—"}</td>
        <td>{srcs.filter(s => s.source_type === "camera").length} cam · {srcs.filter(s => s.source_type === "drone").length} drone</td></tr>)}
      {!rows.length && <tr><td colSpan={5} className="muted">No PCs paired yet.</td></tr>}
    </tbody></table></div>
  </>;
}
