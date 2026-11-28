"use client";
import {useEffect, useState} from "react";
import {useRouter} from "next/navigation";
import {createClient} from "../../../lib/supabase/client";

type Lic = Record<string, any>;
const FEATURES: [string, string][] = [["camera_ai","Camera AI"],["face_ai","Face AI"],["lpr","Plate reading (LPR)"],["drone_live","Drone live"],["drone_ai","Drone AI"],["drone_tracking","Drone tracking"],["drone_control","Fly drone from PC"],["drone_dock","DJI Docks"],["handoff","Camera-to-drone handoff"],["smart_patrol","Smart patrol"],["verified_alarms","Drone-verified alarms"],["incident_replay","4D incident replay"],["phone_access","Phone access"],["satellite","Satellite view"],["drone_detector","Detector drones"]];
// The newer features: a licence record saved before they were listed had them all (nothing could turn them off).
const PREMIUM = ["handoff","smart_patrol","verified_alarms","incident_replay","phone_access"];
const DEFAULT_FEATURES = ["camera_ai","face_ai","lpr","drone_live","drone_ai","drone_tracking","handoff","smart_patrol","verified_alarms","incident_replay","phone_access"];
const inYear = () => { const d = new Date(); d.setFullYear(d.getFullYear() + 1); return d.toISOString().slice(0, 10); };
const blank = (): Lic => ({edition:"onprem", client_name:"", company:"", location:"", address:"", contact_name:"", phone:"", email:"", notes:"",
  price:"", currency:"USD", billing_period:"yearly", next_payment_date:"", payment_status:"pending", machine_id:"", plan:"on-prem",
  cameras:1, drones:1, docks:0, max_users:5, features:DEFAULT_FEATURES, expires_on:inYear(), organization_id:""});

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
  const [busy, setBusy] = useState(false), [msg, setMsg] = useState(""), [done, setDone] = useState("");
  const set = (k: string, v: any) => setForm(f => ({...f!, [k]: v}));
  const orgName = (id?: string) => orgs.find(o => o.id === id)?.name;
  const orgLimit = (id: string, key: string) => limits.find(e => e.organization_id === id && e.feature_key === key);

  function edit(l: Lic){ setMsg(""); setForm({...blank(), ...Object.fromEntries(Object.entries(l).map(([k, v]) => [k, v ?? ""])), features: l.features?.length ? (l.features.some((f: string) => PREMIUM.includes(f)) ? l.features : [...l.features, ...PREMIUM]) : DEFAULT_FEATURES}); }
  function renew(l: Lic){ edit(l); setForm(f => ({...f!, expires_on: inYear(), renewing: true})); }
  function fromOrg(o: Lic){ setMsg(""); const cam = orgLimit(o.id, "camera_ai"), dr = orgLimit(o.id, "drone_live"), dk = orgLimit(o.id, "drone_dock");
    setForm({...blank(), edition: "saas", client_name: o.name, organization_id: o.id, plan: o.plan_code, cameras: cam?.limit_value ?? 1, drones: dr?.enabled === false ? 0 : (dr?.limit_value ?? 1),
      docks: dk?.enabled ? (dk.limit_value ?? 0) : 0}); }

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
    const docks = Math.min(50, Math.max(0, Math.trunc(Number(f.docks) || 0)));
    if(!String(f.client_name).trim()){ setMsg("Client name is required."); return; }
    setBusy(true); setMsg("");
    const sb = createClient();
    let newId = "";
    const details = {client_name: f.client_name, company: f.company, location: f.location, address: f.address, contact_name: f.contact_name, phone: f.phone,
      email: f.email, notes: f.notes, price: f.price === "" ? null : Number(f.price), currency: f.currency || "USD", billing_period: f.billing_period || null,
      next_payment_date: f.next_payment_date || null, payment_status: f.payment_status || null};
    try{
      if(f.edition === "onprem"){
        const needsNewFile = !f.id || f.renewing || !f.license_document;
        if(needsNewFile){
          const {data, error} = await sb.functions.invoke("issue-onprem-license", {body: {...details, record_id: f.id || undefined, machine_id: f.machine_id,
            expires_on: f.expires_on, plan: f.plan, cameras, drones, docks, features: f.features}});
          if(error || !data?.ok) throw new Error(data?.error || (error as any)?.context?.statusText || error?.message || "Could not issue the licence");
          download(data.record); newId = data.record?.id || ""; setMsg("Licence issued and downloaded. Send the .lic file to the client.");
        } else {
          const {error} = await sb.from("client_licenses").update(details).eq("id", f.id); if(error) throw error;
          setMsg("Client details saved. (To change cameras, drones, features or expiry, use Renew: a new file is issued.)");
        }
      } else {
        if(!f.organization_id) throw new Error("Choose the client's portal account.");
        const org = orgs.find(o => o.id === f.organization_id);
        const max_users = Math.min(1000, Math.max(1, Math.trunc(Number(f.max_users) || 5)));
        const row = {...details, edition: "saas", organization_id: f.organization_id, plan: org?.plan_code ?? f.plan, cameras, drones, docks, max_users, features: f.features,
          expires_on: f.expires_on || null, issued_on: f.issued_on || new Date().toISOString().slice(0, 10), status: f.status || "active"};
        const {error} = f.id ? await sb.from("client_licenses").update(row).eq("id", f.id) : await sb.from("client_licenses").insert(row);
        if(error) throw error;
        // The Windows app enforces these through the client's portal entitlements.
        for(const [feature] of FEATURES){
          // DJI Docks: on only with at least one dock; the dock count is its limit (each dock carries its own drone).
          // Detector drones doesn't need drones of the client's own (it watches for other people's).
          const on = f.features.includes(feature) && (feature === "drone_dock" ? docks > 0 : feature === "drone_detector" || !feature.startsWith("drone") || drones > 0);
          const limit = feature === "camera_ai" ? cameras : feature === "drone_live" ? drones : feature === "drone_dock" ? docks : null;
          const {error: e} = await sb.rpc("set_feature_override", {target_org: f.organization_id, target_feature: feature, target_enabled: feature === "camera_ai" || on, target_limit: limit});
          if(e) throw e;
        }
        setMsg(`Saved. ${org?.name ?? "Client"}: ${cameras} camera(s), ${drones} drone(s), ${docks} dock(s), ${f.features.length} feature(s).`);
      }
      const target = f.organization_id ? "/admin/clients/org-" + f.organization_id : f.id ? "/admin/clients/lic-" + f.id : newId ? "/admin/clients/lic-" + newId : "/admin/clients";
      setForm(null); setDone(target);
      if(f.id || f.edition === "saas") router.push(target);  // a new licence file stays here so its download message is seen
    } catch(e){ setMsg(e instanceof Error ? e.message : "Save failed"); }
    finally{ setBusy(false); }
  }

  const F = (k: string, label: string, props: Lic = {}) => <label>{label}<input value={form?.[k] ?? ""} onChange={e => set(k, e.target.value)} {...props}/></label>;
  const lockedFile = form?.edition === "onprem" && form?.id && !form?.renewing;

  // The list of clients is on the Clients page; this page is the licence form (new, edit, renew, add details).
  return <>
    <p><a className="muted" href="/admin/clients">← All clients</a></p>
    {msg && <p className="card licMsg">{msg}</p>}
    {done && <p><a className="btn" href={done}>Open the client</a> <a className="ghost" href="/admin/clients">All clients</a></p>}
    {!form && !done && <p className="muted">Open a client to edit or renew its licence, or start a new one from the Clients page.</p>}
    {form && <section className="card licForm">
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
        {F("docks", "DJI Docks (max, 0 = none)", {type: "number", min: 0, max: 50, disabled: lockedFile, title: "Needs “DJI Docks” ticked below. Each dock carries its own drone."})}
        {form.edition === "saas" && F("max_users", "Portal users (max)", {type: "number", min: 1, max: 1000})}
        {F("expires_on", form.edition === "onprem" ? "Expires *" : "Contract ends", {type: "date", disabled: lockedFile})}
        {form.edition === "onprem" && F("plan", "Plan label", {disabled: lockedFile})}
      </div>
      <div className="licFeatures">{FEATURES.map(([k, t]) => <label key={k} className="radio"><input type="checkbox" disabled={!!lockedFile}
        checked={form.features.includes(k)} onChange={e => set("features", e.target.checked ? [...form.features, k] : form.features.filter((x: string) => x !== k))}/> {t}</label>)}</div>
      {form.edition === "saas" && <p className="muted">Applied to the client's online account within a minute: the ticked features and the camera/drone limits replace what their plan includes.</p>}
      {lockedFile && <p className="muted">This licence file is signed and cannot be changed. Use <b>Renew</b> to issue a new file with different limits or a new expiry date.</p>}
      <h3>Price & payment</h3>
      <div className="licGrid">{F("price", "Price", {type: "number", min: 0, step: "0.01"})}{F("currency", "Currency", {maxLength: 3})}
        <label>Billing<select value={form.billing_period} onChange={e => set("billing_period", e.target.value)}><option value="one-time">One-time</option><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select></label>
        {F("next_payment_date", "Next payment", {type: "date"})}
        <label>Payment status<select value={form.payment_status} onChange={e => set("payment_status", e.target.value)}><option value="pending">Pending</option><option value="paid">Paid</option><option value="overdue">Overdue</option></select></label></div>
      <label>Notes<textarea rows={3} value={form.notes ?? ""} onChange={e => set("notes", e.target.value)}/></label>
      <div className="actions"><button className="btn" disabled={busy} onClick={save}>{busy ? "Saving…" : form.edition === "onprem" && (!form.id || form.renewing) ? "Issue & download licence" : "Save"}</button>
        <button className="ghost" disabled={busy} onClick={() => history.length > 1 ? history.back() : router.push("/admin/clients")}>Cancel</button></div>
    </section>}

  </>;
}
