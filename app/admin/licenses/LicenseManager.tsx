"use client";
import {useEffect, useMemo, useState} from "react";
import {useRouter} from "next/navigation";
import {createClient} from "../../../lib/supabase/client";

type Lic = Record<string, any>;
const FEATURES: [string, string][] = [["camera_ai","Camera AI"],["face_ai","Face AI"],["lpr","Plate reading (LPR)"],["drone_live","Drone live"],["drone_ai","Drone AI"],["drone_tracking","Drone tracking"],["drone_control","Fly drone from PC"]];
const DEFAULT_FEATURES = ["camera_ai","face_ai","lpr","drone_live","drone_ai","drone_tracking"];
const inYear = () => { const d = new Date(); d.setFullYear(d.getFullYear() + 1); return d.toISOString().slice(0, 10); };
const blank = (): Lic => ({edition:"onprem", client_name:"", company:"", location:"", address:"", contact_name:"", phone:"", email:"", notes:"",
  price:"", currency:"USD", billing_period:"yearly", next_payment_date:"", payment_status:"pending", machine_id:"", plan:"on-prem",
  cameras:1, drones:1, features:DEFAULT_FEATURES, expires_on:inYear(), organization_id:""});
const daysLeft = (d?: string) => d ? Math.ceil((new Date(d).getTime() - Date.now()) / 86400000) : null;

function download(l: Lic){
  const doc = l.license_document; if(!doc) return;
  const name = (l.client_name || "client").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "client";
  const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], {type: "application/json"}));
  const a = Object.assign(document.createElement("a"), {href: url, download: `license-${name}-${String(l.machine_id).slice(0, 9)}.lic`});
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}

export default function LicenseManager({licenses, orgs, limits, open}: {licenses: Lic[]; orgs: Lic[]; limits: Lic[]; open?: Record<string, string>}){
  const router = useRouter();
  const [form, setForm] = useState<Lic | null>(null);
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState(""), [filter, setFilter] = useState("all");
  const set = (k: string, v: any) => setForm(f => ({...f!, [k]: v}));
  const orgName = (id?: string) => orgs.find(o => o.id === id)?.name;
  const orgLimit = (id: string, key: string) => limits.find(e => e.organization_id === id && e.feature_key === key);
  const recordedOrgs = new Set(licenses.filter(l => l.organization_id).map(l => l.organization_id));
  const shown = useMemo(() => licenses.filter(l => filter === "all" || l.edition === filter || (filter === "expiring" && (daysLeft(l.expires_on) ?? 999) <= 30)), [licenses, filter]);
  const counts = {onprem: licenses.filter(l => l.edition === "onprem").length, saas: licenses.filter(l => l.edition === "saas").length,
    expiring: licenses.filter(l => (daysLeft(l.expires_on) ?? 999) <= 30 && l.status === "active").length};

  function edit(l: Lic){ setMsg(""); setForm({...blank(), ...Object.fromEntries(Object.entries(l).map(([k, v]) => [k, v ?? ""])), features: l.features?.length ? l.features : DEFAULT_FEATURES}); }
  function renew(l: Lic){ edit(l); setForm(f => ({...f!, expires_on: inYear(), renewing: true})); }
  function fromOrg(o: Lic){ setMsg(""); const cam = orgLimit(o.id, "camera_ai"), dr = orgLimit(o.id, "drone_live");
    setForm({...blank(), edition: "saas", client_name: o.name, organization_id: o.id, plan: o.plan_code, cameras: cam?.limit_value ?? 1, drones: dr?.enabled === false ? 0 : (dr?.limit_value ?? 1)}); }

  // Opened from a client page or the overview: ?new=onprem, ?edit=<id>, ?renew=<id>, ?org=<organization id>
  useEffect(() => {
    if(!open) return;
    const rec = licenses.find(l => l.id === (open.edit || open.renew));
    if(open.renew && rec) renew(rec);
    else if(open.edit && rec) edit(rec);
    else if(open.org){ const o = orgs.find(x => x.id === open.org); if(o) fromOrg(o); }
    else if(open.new) setForm({...blank(), edition: open.new === "saas" ? "saas" : "onprem"});
  }, []);

  async function save(){
    if(!form) return;
    const f = form, cameras = Math.max(1, Math.trunc(Number(f.cameras) || 1)), drones = Math.max(0, Math.trunc(Number(f.drones) || 0));
    if(!String(f.client_name).trim()){ setMsg("Client name is required."); return; }
    setBusy(true); setMsg("");
    const sb = createClient();
    const details = {client_name: f.client_name, company: f.company, location: f.location, address: f.address, contact_name: f.contact_name, phone: f.phone,
      email: f.email, notes: f.notes, price: f.price === "" ? null : Number(f.price), currency: f.currency || "USD", billing_period: f.billing_period || null,
      next_payment_date: f.next_payment_date || null, payment_status: f.payment_status || null};
    try{
      if(f.edition === "onprem"){
        const needsNewFile = !f.id || f.renewing || !f.license_document;
        if(needsNewFile){
          const {data, error} = await sb.functions.invoke("issue-onprem-license", {body: {...details, record_id: f.id || undefined, machine_id: f.machine_id,
            expires_on: f.expires_on, plan: f.plan, cameras, drones, features: f.features}});
          if(error || !data?.ok) throw new Error(data?.error || (error as any)?.context?.statusText || error?.message || "Could not issue the licence");
          download(data.record); setMsg("Licence issued and downloaded. Send the .lic file to the client.");
        } else {
          const {error} = await sb.from("client_licenses").update(details).eq("id", f.id); if(error) throw error;
          setMsg("Client details saved. (To change cameras, drones, features or expiry, use Renew: a new file is issued.)");
        }
      } else {
        if(!f.organization_id) throw new Error("Choose the client's portal account.");
        const org = orgs.find(o => o.id === f.organization_id);
        const row = {...details, edition: "saas", organization_id: f.organization_id, plan: org?.plan_code ?? f.plan, cameras, drones, features: f.features,
          expires_on: f.expires_on || null, issued_on: f.issued_on || new Date().toISOString().slice(0, 10), status: f.status || "active"};
        const {error} = f.id ? await sb.from("client_licenses").update(row).eq("id", f.id) : await sb.from("client_licenses").insert(row);
        if(error) throw error;
        // The Windows app enforces these through the client's portal entitlements.
        for(const [feature, enabled, limit] of [["camera_ai", true, cameras], ["drone_live", drones > 0, drones]] as const){
          const {error: e} = await sb.rpc("set_feature_override", {target_org: f.organization_id, target_feature: feature, target_enabled: enabled, target_limit: limit});
          if(e) throw e;
        }
        setMsg(`Saved. ${org?.name ?? "Client"} is now limited to ${cameras} camera(s) and ${drones} drone(s).`);
      }
      setForm(null); router.refresh();
      if(open?.edit || open?.renew || open?.org) router.push(form.organization_id ? "/admin/clients/org-" + form.organization_id : form.id ? "/admin/clients/lic-" + form.id : "/admin/clients");
    } catch(e){ setMsg(e instanceof Error ? e.message : "Save failed"); }
    finally{ setBusy(false); }
  }

  async function revoke(l: Lic){
    if(!confirm(`Mark ${l.client_name}'s licence as revoked?` + (l.edition === "onprem" ? "\n\nNote: an on-prem file already installed keeps working until its expiry date (it is offline). Do not renew it." : ""))) return;
    const {error} = await createClient().from("client_licenses").update({status: "revoked"}).eq("id", l.id);
    if(error) alert(error.message); else router.refresh();
  }

  const F = (k: string, label: string, props: Lic = {}) => <label>{label}<input value={form?.[k] ?? ""} onChange={e => set(k, e.target.value)} {...props}/></label>;
  const lockedFile = form?.edition === "onprem" && form?.id && !form?.renewing;

  return <>
    <section className="grid">
      <article className="card"><h2>Clients</h2><strong>{licenses.length}</strong><p className="muted">with licence records</p></article>
      <article className="card"><h2>On-prem</h2><strong>{counts.onprem}</strong><p className="muted">offline licence files</p></article>
      <article className="card"><h2>Online (SaaS)</h2><strong>{counts.saas}</strong><p className="muted">portal accounts</p></article>
      <article className={"card"}><h2>Expiring</h2><strong className={counts.expiring ? "locked" : ""}>{counts.expiring}</strong><p className="muted">within 30 days</p></article>
    </section>
    <div className="portalTop" style={{marginTop: 24}}>
      <div className="licFilters">{[["all","All"],["onprem","On-prem"],["saas","Online (SaaS)"],["expiring","Expiring soon"]].map(([k, t]) =>
        <button key={k} className={filter === k ? "btn small" : "ghost"} onClick={() => setFilter(k)}>{t}</button>)}</div>
      <button className="btn" onClick={() => { setMsg(""); setForm(blank()); }}>+ New client / licence</button>
    </div>
    {msg && <p className="card licMsg">{msg}</p>}

    {form && <section className="card licForm">
      <h2>{form.id ? (form.renewing ? "Renew licence" : "Edit client") : "New client / licence"}</h2>
      {!form.id && <div className="licEdition">{[["onprem","On-prem (offline licence file)"],["saas","Online (SaaS portal account)"]].map(([k, t]) =>
        <label key={k} className="radio"><input type="radio" checked={form.edition === k} onChange={() => set("edition", k)}/> {t}</label>)}</div>}
      <h3>Client</h3>
      <div className="licGrid">{F("client_name", "Client name *")}{F("company", "Company")}{F("location", "City / country")}{F("address", "Site address")}</div>
      <h3>Contact</h3>
      <div className="licGrid">{F("contact_name", "Contact person")}{F("phone", "Phone / WhatsApp")}{F("email", "Email", {type: "email"})}</div>
      <h3>Licence</h3>
      <div className="licGrid">
        {form.edition === "onprem" ? F("machine_id", "Machine ID * (from the client's License page)", {placeholder: "XXXX-XXXX-XXXX-XXXX-XXXX", disabled: lockedFile, style: {textTransform: "uppercase"}})
          : <label>Portal account *<select value={form.organization_id} disabled={!!form.id} onChange={e => set("organization_id", e.target.value)}><option value="">Choose…</option>
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name} ({String(o.plan_code).toUpperCase()})</option>)}</select></label>}
        {F("cameras", "Cameras (max) *", {type: "number", min: 1, disabled: lockedFile})}
        {F("drones", "Drones (max, 0 = none)", {type: "number", min: 0, disabled: lockedFile})}
        {F("expires_on", form.edition === "onprem" ? "Expires *" : "Contract ends", {type: "date", disabled: lockedFile})}
        {form.edition === "onprem" && F("plan", "Plan label", {disabled: lockedFile})}
      </div>
      <div className="licFeatures">{FEATURES.map(([k, t]) => <label key={k} className="radio"><input type="checkbox" disabled={!!lockedFile || form.edition === "saas"}
        checked={form.features.includes(k)} onChange={e => set("features", e.target.checked ? [...form.features, k] : form.features.filter((x: string) => x !== k))}/> {t}</label>)}</div>
      {form.edition === "saas" && <p className="muted">Online clients get their features from their plan (set in the Operations Console). Cameras and drones above are applied as their limits.</p>}
      {lockedFile && <p className="muted">This licence file is signed and cannot be changed. Use <b>Renew</b> to issue a new file with different limits or a new expiry date.</p>}
      <h3>Price & payment</h3>
      <div className="licGrid">{F("price", "Price", {type: "number", min: 0, step: "0.01"})}{F("currency", "Currency", {maxLength: 3})}
        <label>Billing<select value={form.billing_period} onChange={e => set("billing_period", e.target.value)}><option value="one-time">One-time</option><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select></label>
        {F("next_payment_date", "Next payment", {type: "date"})}
        <label>Payment status<select value={form.payment_status} onChange={e => set("payment_status", e.target.value)}><option value="pending">Pending</option><option value="paid">Paid</option><option value="overdue">Overdue</option></select></label></div>
      <label>Notes<textarea rows={3} value={form.notes ?? ""} onChange={e => set("notes", e.target.value)}/></label>
      <div className="actions"><button className="btn" disabled={busy} onClick={save}>{busy ? "Saving…" : form.edition === "onprem" && (!form.id || form.renewing) ? "Issue & download licence" : "Save"}</button>
        <button className="ghost" disabled={busy} onClick={() => setForm(null)}>Cancel</button></div>
    </section>}

    <div className="card tableWrap"><table className="adminTable"><thead><tr><th>Client</th><th>Type</th><th>Contact</th><th>Licence</th><th>Expires</th><th>Payment</th><th></th></tr></thead><tbody>
      {shown.map(l => { const d = daysLeft(l.expires_on); return <tr key={l.id}>
        <td><b>{l.client_name}</b>{l.company && <div className="muted">{l.company}</div>}<div className="muted">{[l.location, l.address].filter(Boolean).join(" · ")}</div></td>
        <td><span className="badge">{l.edition === "onprem" ? "ON-PREM" : "SaaS"}</span>{l.status === "revoked" && <div className="locked">revoked</div>}</td>
        <td>{l.contact_name}<div className="muted">{l.phone}</div><div className="muted">{l.email}</div></td>
        <td>{l.cameras} camera{l.cameras === 1 ? "" : "s"} · {l.drones} drone{l.drones === 1 ? "" : "s"}
          <div className="muted">{l.edition === "onprem" ? `Machine ${l.machine_id}` : orgName(l.organization_id) ?? "account removed"}</div>
          {l.license_id && <div className="muted" title="Shown on the client's License page">ID {String(l.license_id).slice(0, 8).toUpperCase()}</div>}</td>
        <td className={d !== null && d <= 0 ? "locked" : d !== null && d <= 30 ? "locked" : ""}>{l.expires_on ?? "—"}{d !== null && <div className="muted">{d <= 0 ? "expired" : `${d} days`}</div>}</td>
        <td>{l.price != null ? `${l.price} ${l.currency}` : "—"}<div className="muted">{[l.billing_period, l.payment_status].filter(Boolean).join(" · ")}</div>{l.next_payment_date && <div className="muted">next {l.next_payment_date}</div>}</td>
        <td className="licActions">{l.edition === "onprem" && l.license_document && <button className="ghost" onClick={() => download(l)}>Download .lic</button>}
          {l.edition === "onprem" && <button className="ghost" onClick={() => renew(l)}>Renew</button>}
          <button className="ghost" onClick={() => edit(l)}>Edit</button>
          {l.status !== "revoked" && <button className="ghost" onClick={() => revoke(l)}>Revoke</button>}</td>
      </tr>; })}
      {!shown.length && <tr><td colSpan={7} className="muted">No clients here yet. Use “+ New client / licence”.</td></tr>}
    </tbody></table></div>

    {orgs.some(o => !recordedOrgs.has(o.id)) && <><h2>Online accounts without client details</h2><div className="card tableWrap"><table className="adminTable"><tbody>
      {orgs.filter(o => !recordedOrgs.has(o.id)).map(o => <tr key={o.id}><td><b>{o.name}</b><div className="muted">{String(o.plan_code).toUpperCase()} · {o.status}</div></td>
        <td style={{textAlign: "right"}}><button className="ghost" onClick={() => fromOrg(o)}>Add client details & limits</button></td></tr>)}
    </tbody></table></div></>}
  </>;
}
