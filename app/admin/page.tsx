import Link from "next/link";
import {createClient} from "../../lib/supabase/server";
import {buildClients, isOnline, loadAdminData, needsAttention} from "../../lib/admin";

const ICON: Record<string, string> = {expiry: "⏳", payment: "$", trial: "★", offline: "⚠", version: "⬆", suspended: "⏸"};

export default async function Overview(){
  const supabase = await createClient();
  const data = await loadAdminData(supabase);
  const clients = buildClients(data), alerts = needsAttention(data, clients);
  const online = data.devices.filter(d => isOnline(d)).length;
  const {data: activity} = await supabase.from("audit_logs").select("action,metadata,created_at,organization_id,target_type").order("created_at", {ascending: false}).limit(8);
  return <>
    <div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Overview</h1><p className="muted">What needs your attention today</p></div>
      <div className="portalActions"><Link className="btn" href="/admin/licenses?new=onprem">+ New on-prem licence</Link><Link className="ghost" href="/admin/clients">All clients</Link></div></div>
    <section className="grid">
      <Link className="card statLink" href="/admin/clients"><h2>Clients</h2><strong>{clients.length}</strong><p className="muted">{clients.filter(c => c.type === "saas").length} online · {clients.filter(c => c.type === "onprem").length} on-prem</p></Link>
      <Link className="card statLink" href="/admin/devices"><h2>PCs online</h2><strong className={online < data.devices.length ? "locked" : "ok"}>{online}/{data.devices.length}</strong><p className="muted">client Edge Agents</p></Link>
      <Link className="card statLink" href="/admin/devices"><h2>Cameras & drones</h2><strong>{data.sources.length}</strong><p className="muted">registered by online clients</p></Link>
      <Link className="card statLink" href="/admin/users"><h2>Users</h2><strong>{data.users.length}</strong><p className="muted">accounts</p></Link>
    </section>
    <h2>Needs attention {alerts.length > 0 && <span className="badge">{alerts.length}</span>}</h2>
    <div className="card attention">{alerts.length ? alerts.map((a, i) => <Link key={i} href={a.href} className={"alertRow " + a.level}>
      <i>{ICON[a.kind] ?? "•"}</i><div><b>{a.title}</b><div className="muted">{a.detail}</div></div><span className="alertLevel">{a.level === "high" ? "urgent" : a.level === "medium" ? "soon" : "info"}</span></Link>)
      : <p className="ok">✓ All clear: no expiring licences, overdue payments or offline PCs.</p>}</div>
    <h2>Recent activity</h2>
    <div className="card tableWrap"><table className="adminTable"><tbody>{(activity ?? []).map((e: any, i: number) => <tr key={i}>
      <td className="muted" style={{whiteSpace: "nowrap"}}>{new Date(e.created_at).toLocaleString()}</td>
      <td><b>{e.action.replace(/_/g, " ")}</b></td><td>{e.metadata?.client ?? clients.find(c => c.orgId === e.organization_id)?.name ?? ""}</td>
      <td className="muted">{e.metadata?.feature ?? (e.metadata?.cameras != null ? `${e.metadata.cameras} cam · ${e.metadata.drones} drone` : "")}</td></tr>)}
      {!activity?.length && <tr><td className="muted">No activity yet.</td></tr>}</tbody></table></div>
  </>;
}
