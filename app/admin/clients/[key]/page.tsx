import Link from "next/link";
import {notFound} from "next/navigation";
import {createClient} from "../../../../lib/supabase/server";
import {buildClients, daysLeft, isOnline, LATEST_APP_VERSION, loadAdminData, versionBehind} from "../../../../lib/admin";
import SubscriptionControls from "../../SubscriptionControls";
import FeatureToggle from "../../FeatureToggle";
import DownloadLicense from "./DownloadLicense";

const FEATURES: [string, string][] = [["camera_ai", "Camera AI"], ["face_ai", "Face AI"], ["lpr", "Licence plate reading"], ["drone_live", "Drone live"], ["drone_ai", "Drone AI"], ["drone_tracking", "Drone tracking"]];
const FEATURE_LABEL = Object.fromEntries([...FEATURES, ["drone_control", "Fly drone from PC"]]);

function Contact({c}: {c: Record<string, any>}){
  const wa = String(c.phone || "").replace(/[^\d]/g, "");
  return <div className="contactBtns">
    {c.phone && <a className="ghost" href={"tel:" + c.phone}>📞 Call</a>}
    {wa && <a className="ghost" href={"https://wa.me/" + wa} target="_blank">💬 WhatsApp</a>}
    {c.email && <a className="ghost" href={"mailto:" + c.email}>✉ Email</a>}
  </div>;
}

export default async function ClientPage({params}: {params: Promise<{key: string}>}){
  const {key} = await params;
  const supabase = await createClient();
  const data = await loadAdminData(supabase);
  const c = buildClients(data).find(x => x.key === key);
  if(!c) notFound();
  const l = c.license, left = daysLeft(c.expires);
  const activityQuery = supabase.from("audit_logs").select("action,metadata,created_at").order("created_at", {ascending: false}).limit(20);
  const {data: activity} = c.orgId ? await activityQuery.eq("organization_id", c.orgId) : await activityQuery.eq("target_id", l!.id);

  let saas: React.ReactNode = null;
  if(c.type === "saas" && c.org){
    const o = c.org, sub = data.subs.find(s => s.organization_id === o.id);
    const [{data: overrides}, {data: defaults}] = await Promise.all([
      supabase.from("feature_entitlements").select("feature_key,enabled,limit_value").eq("organization_id", o.id),
      supabase.from("plan_features").select("feature_key,enabled,limit_value").eq("plan_code", c.plan)]);
    const devices = data.devices.filter(d => d.organization_id === o.id), sources = data.sources.filter(s => s.organization_id === o.id);
    const users = data.users.filter(u => u.organization_id === o.id);
    saas = <>
      <section className="detailGrid">
        <article className="card"><h3>Account</h3>
          <SubscriptionControls orgId={o.id} initialPlan={c.plan} initialStatus={o.status} paid={!!sub?.provider_subscription_id}/>
          <p className="muted">{sub?.provider_subscription_id ? "Paid via Stripe" : "No Stripe subscription"}{sub?.current_period_end ? ` · period ends ${String(sub.current_period_end).slice(0, 10)}` : ""}{sub?.cancel_at_period_end ? " · cancels at period end" : ""}</p>
          <p><a className="btn small" href={"/portal?organization=" + encodeURIComponent(o.id)}>Open their dashboard</a></p></article>
        <article className="card"><h3>Feature access</h3>{FEATURES.map(([k, label]) => {
          const ov = overrides?.find(e => e.feature_key === k), def = defaults?.find(e => e.feature_key === k), lim = ov?.limit_value ?? def?.limit_value;
          return <p key={k} className="toggleRow"><span>{label}{lim != null && <span className="muted"> · max {lim}</span>}</span><FeatureToggle orgId={o.id} feature={k} initial={ov?.enabled ?? def?.enabled ?? false}/></p>; })}</article>
      </section>
      <h2>PCs (Edge Agents)</h2>
      <div className="card tableWrap"><table className="adminTable"><thead><tr><th>PC</th><th>Status</th><th>Version</th><th>Cameras & drones</th></tr></thead><tbody>
        {devices.map(d => { const on = isOnline(d), srcs = sources.filter(s => s.edge_device_id === d.id); return <tr key={d.id}>
          <td><b>{d.device_name || "Unnamed PC"}</b><div className="muted">{d.platform} {d.last_ip ? "· " + d.last_ip : ""}</div></td>
          <td className={on ? "ok" : "locked"}>{on ? "● Online" : "○ Offline"}<div className="muted">{d.last_seen_at ? "last seen " + new Date(d.last_seen_at).toLocaleString() : "never connected"}</div></td>
          <td className={versionBehind(d.app_version) ? "locked" : ""}>{d.app_version || "—"}{versionBehind(d.app_version) && <div className="muted">update to {LATEST_APP_VERSION}</div>}</td>
          <td>{srcs.length ? srcs.map(s => <div key={s.id}>{s.source_type === "drone" ? "✈" : "▣"} {s.name}{!s.enabled && <span className="muted"> (off)</span>}</div>) : <span className="muted">none</span>}</td></tr>; })}
        {!devices.length && <tr><td colSpan={4} className="muted">No PC paired yet. The client pairs one from their portal (“Pair a Windows Edge Agent”).</td></tr>}
        {sources.filter(s => !s.edge_device_id).map(s => <tr key={s.id}><td colSpan={3} className="muted">Not linked to a PC</td><td>{s.source_type === "drone" ? "✈" : "▣"} {s.name}</td></tr>)}
      </tbody></table></div>
      <h2>Users</h2>
      <div className="card tableWrap"><table className="adminTable"><tbody>{users.map(u => <tr key={u.user_id}><td><b>{u.full_name || u.email}</b><div className="muted">{u.email}</div></td><td>{u.role}</td>
        <td className="muted">{u.last_sign_in_at ? "last sign-in " + new Date(u.last_sign_in_at).toLocaleString() : "never signed in"}</td></tr>)}
        {!users.length && <tr><td className="muted">No users.</td></tr>}</tbody></table></div>
    </>;
  }

  return <>
    <p><Link className="muted" href="/admin/clients">← All clients</Link></p>
    <div className="portalTop"><div><span className={"badge " + (c.type === "onprem" ? "badgeOnprem" : "badgeSaas")}>{c.type === "onprem" ? "ON-PREM" : "ONLINE"}</span>
      {["suspended", "revoked", "cancelled"].includes(c.status) && <span className="badge locked" style={{marginLeft: 8}}>{c.status.toUpperCase()}</span>}
      <h1>{c.name}</h1><p className="muted">{[c.company, c.location].filter(Boolean).join(" · ") || "No company / location yet"}</p></div>
      <div className="portalActions">
        {c.type === "onprem" && l && <><DownloadLicense license={l}/><Link className="btn" href={"/admin/licenses?renew=" + l.id}>Renew</Link></>}
        <Link className="ghost" href={l ? "/admin/licenses?edit=" + l.id : "/admin/licenses?org=" + c.orgId}>{l ? "Edit details" : "Add contact & limits"}</Link></div></div>

    <section className="detailGrid">
      <article className="card"><h3>Contact</h3>
        {c.contact || c.phone || c.email ? <><p><b>{c.contact || "—"}</b></p><p className="muted">{c.phone}<br/>{c.email}</p><Contact c={c}/></> : <p className="muted">No contact details yet.</p>}
        {l?.address && <p className="muted">📍 {l.address}</p>}</article>
      <article className="card"><h3>Licence</h3>
        <p><b>{c.cameras ?? "plan"}</b> camera{c.cameras === 1 ? "" : "s"} · <b>{c.drones ?? "plan"}</b> drone{c.drones === 1 ? "" : "s"}</p>
        <p className={left !== null && left <= 30 ? "locked" : ""}>{c.expires ? `Expires ${c.expires}${left !== null ? (left <= 0 ? " (expired)" : ` · ${left} days left`) : ""}` : "No end date"}</p>
        {c.type === "onprem" && l && <><p className="muted">Machine ID {l.machine_id}<br/>Licence ID {String(l.license_id || "").slice(0, 8).toUpperCase()} · issued {l.issued_on}</p>
          <p className="muted">{(l.features || []).map((f: string) => FEATURE_LABEL[f] ?? f).join(" · ")}</p></>}
        {c.type === "saas" && <p className="muted">Plan {c.plan.toUpperCase()} · {c.status}</p>}</article>
      <article className="card"><h3>Payment</h3>
        {c.price ? <><p><b>{c.price}</b></p><p className={c.paymentStatus === "overdue" ? "locked" : "muted"}>{c.paymentStatus || "status not set"}{c.nextPayment ? ` · next ${c.nextPayment}` : ""}</p></> : <p className="muted">No price recorded.</p>}
        {l?.notes && <><h3>Notes</h3><p className="muted" style={{whiteSpace: "pre-wrap"}}>{l.notes}</p></>}</article>
    </section>
    {saas}
    <h2>Activity</h2>
    <div className="card tableWrap"><table className="adminTable"><tbody>{(activity ?? []).map((e: any, i: number) => <tr key={i}>
      <td className="muted" style={{whiteSpace: "nowrap"}}>{new Date(e.created_at).toLocaleString()}</td><td><b>{e.action.replace(/_/g, " ")}</b></td>
      <td className="muted">{e.metadata?.feature ? `${FEATURE_LABEL[e.metadata.feature] ?? e.metadata.feature}: ${e.metadata.enabled ? "on" : "off"}` : e.metadata?.cameras != null ? `${e.metadata.cameras} cam · ${e.metadata.drones} drone · until ${e.metadata.expires_on ?? "—"}` : ""}</td></tr>)}
      {!activity?.length && <tr><td className="muted">No activity recorded yet.</td></tr>}</tbody></table></div>
  </>;
}
