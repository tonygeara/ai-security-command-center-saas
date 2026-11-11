import Link from "next/link";
import {notFound} from "next/navigation";
import {createClient} from "../../../../lib/supabase/server";
import {buildClients, daysLeft, isOnline, LATEST_APP_VERSION, loadAdminData, versionBehind} from "../../../../lib/admin";
import SubscriptionControls from "../../SubscriptionControls";
import FeatureToggle from "../../FeatureToggle";
import DownloadLicense from "./DownloadLicense";
import RemoveButton from "../../RemoveButton";
import UserManager from "../../../components/UserManager";
import {PcName, PcSwitch, RenameClient, SourceSwitch} from "../../DeviceControls";

const FEATURES: [string, string][] = [["camera_ai", "Camera AI"], ["face_ai", "Face AI"], ["lpr", "Licence plate reading"], ["drone_live", "Drone live"], ["drone_ai", "Drone AI"], ["drone_tracking", "Drone tracking"], ["drone_control", "Fly drone from PC"]];
const FEATURE_LABEL = Object.fromEntries(FEATURES);

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
          // Until "Fly drone from PC" is set for a client, the PC allows flying whenever Drone live is on.
          const live = overrides?.find(e => e.feature_key === "drone_live") ?? defaults?.find(e => e.feature_key === "drone_live");
          const follows = k === "drone_control" && !ov && !def;
          const initial = ov?.enabled ?? def?.enabled ?? (follows ? !!live?.enabled : false);
          return <p key={k} className="toggleRow"><span>{label}{lim != null && <span className="muted"> · max {lim}</span>}{follows && <span className="muted"> · follows Drone live until set</span>}</span><FeatureToggle orgId={o.id} feature={k} initial={initial}/></p>; })}</article>
      </section>
      <h2>PCs (Edge Agents)</h2>
      <div className="card tableWrap"><table className="adminTable"><thead><tr><th>PC</th><th>Status</th><th>Version</th><th>Cameras & drones</th><th></th></tr></thead><tbody>
        {devices.map(d => { const on = isOnline(d), srcs = sources.filter(s => s.edge_device_id === d.id); return <tr key={d.id}>
          <td><PcName id={d.id} name={d.device_name || ""}/><div className="muted">{d.platform} {d.last_ip ? "· " + d.last_ip : ""}</div></td>
          <td className={d.status === "disabled" ? "locked" : on ? "ok" : "locked"}>{d.status === "disabled" ? "⏸ Switched off" : on ? "● Online" : "○ Offline"}<div className="muted">{d.last_seen_at ? "last seen " + new Date(d.last_seen_at).toLocaleString() : "never connected"}</div></td>
          <td className={versionBehind(d.app_version) ? "locked" : ""}>{d.app_version || "—"}{versionBehind(d.app_version) && <div className="muted">update to {LATEST_APP_VERSION}</div>}</td>
          <td>{srcs.length ? srcs.map(s => <SourceSwitch key={s.id} id={s.id} name={s.name} type={s.source_type} enabled={s.enabled !== false}/>) : <span className="muted">none</span>}</td>
          <td><div className="rowActions"><PcSwitch id={d.id} name={d.device_name || ""} disabled={d.status === "disabled"}/><RemoveButton rpc="admin_remove_device" args={{target_device: d.id}} label="Remove PC"
            confirmText={`Remove PC "${d.device_name || "Unnamed PC"}"${on ? " (it is ONLINE now and will stop working)" : ""} and its ${srcs.length} camera(s)/drone(s)?

It can be paired again later with a new code.`}/></div></td></tr>; })}
        {!devices.length && <tr><td colSpan={5} className="muted">No PC paired yet. The client pairs one from their portal (“Pair a Windows Edge Agent”).</td></tr>}
        {sources.filter(s => !s.edge_device_id).map(s => <tr key={s.id}><td colSpan={3} className="muted">Not linked to a PC</td><td>{s.source_type === "drone" ? "✈" : "▣"} {s.name}</td></tr>)}
      </tbody></table></div>
      <h2>Users</h2>
      <p className="muted">You can add an Admin (manages this company), Editors and Viewers, change roles, reset passwords and remove anyone. Their admin can manage Editors and Viewers within the user places on their licence.</p>
      <div className="card"><UserManager orgId={o.id}/></div>
    </>;
  }

  return <>
    <p><Link className="muted" href="/admin/clients">← All clients</Link></p>
    <div className="portalTop"><div><span className={"badge " + (c.type === "onprem" ? "badgeOnprem" : "badgeSaas")}>{c.type === "onprem" ? "ON-PREM" : "ONLINE"}</span>
      {["suspended", "revoked", "cancelled"].includes(c.status) && <span className="badge locked" style={{marginLeft: 8}}>{c.status.toUpperCase()}</span>}
      <h1>{c.name}</h1><p className="muted">{[c.company, c.location].filter(Boolean).join(" · ") || "No company / location yet"}</p></div>
      <div className="portalActions">
        {c.type === "onprem" && l && <><DownloadLicense license={l}/><Link className="btn" href={"/admin/licenses?renew=" + l.id}>Renew</Link></>}
        {c.orgId && <RenameClient orgId={c.orgId} name={c.org?.name ?? c.name}/>}
        <Link className="ghost" href={l ? "/admin/licenses?edit=" + l.id : "/admin/licenses?org=" + c.orgId}>{l ? "Edit details" : "Add contact & limits"}</Link>
        {c.type === "onprem" && l ? <RemoveButton rpc="admin_remove_client_license" args={{target_license: l.id}} label="Remove" small={false} goTo="/admin/clients"
            confirmText={`Remove ${c.name} and its licence record from the portal?

An on-prem licence already installed on their PC keeps working until ${c.expires}.`}/>
          : c.orgId && <RemoveButton rpc="admin_remove_organization" args={{target_org: c.orgId}} label="Remove client" small={false} goTo="/admin/clients"
            confirmText={`Permanently remove the online account "${c.name}" with all its PCs, cameras, users' access, subscription record and history?

This cannot be undone.`}/>}</div></div>

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
