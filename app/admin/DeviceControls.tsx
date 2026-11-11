"use client";
// Super admin: rename a client's PC, switch it off (its app is refused by the cloud until switched on again)
// or on, and switch single cameras or drones off or on.
import {useState} from "react";
import {useRouter} from "next/navigation";
import {createClient} from "../../lib/supabase/client";

async function rpc(name: string, args: Record<string, unknown>) {
  const {error} = await createClient().rpc(name, args);
  if (error) throw new Error(error.message);
}

export function PcName({id, name}: {id: string; name: string}){
  const router = useRouter();
  const [editing, setEditing] = useState(false), [value, setValue] = useState(name), [busy, setBusy] = useState(false);
  if (!editing) return <span className="deviceEdit"><b>{name || "Unnamed PC"}</b>
    <button className="ghost small" onClick={e => { e.stopPropagation(); setEditing(true); }} title="Rename this PC">Rename</button></span>;
  return <form className="deviceEdit" onSubmit={async e => { e.preventDefault(); setBusy(true);
      try { await rpc("admin_update_device", {target_device: id, new_name: value}); setEditing(false); router.refresh(); }
      catch (err) { alert((err as Error).message); } finally { setBusy(false); } }}>
    <input value={value} maxLength={80} required autoFocus onChange={e => setValue(e.target.value)} aria-label="PC name"/>
    <button className="btn small" disabled={busy}>Save</button><button type="button" className="ghost small" onClick={() => { setValue(name); setEditing(false); }}>Cancel</button>
  </form>;
}

export function PcSwitch({id, name, disabled}: {id: string; name: string; disabled: boolean}){
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function flip(){
    if (!disabled && !confirm(`Switch off PC "${name || "Unnamed PC"}"?\n\nIts app stops syncing and is refused by the cloud (no incidents, live pictures or licence checks) until you switch it on again.`)) return;
    setBusy(true);
    try { await rpc("admin_update_device", {target_device: id, enabled: disabled}); router.refresh(); }
    catch (e) { alert((e as Error).message); } finally { setBusy(false); }
  }
  return <button className={disabled ? "btn small" : "ghost small"} disabled={busy} onClick={flip}>{busy ? "Saving…" : disabled ? "Switch on" : "Switch off"}</button>;
}

export function SourceSwitch({id, name, type, enabled}: {id: string; name: string; type: string; enabled: boolean}){
  const router = useRouter();
  const [on, setOn] = useState(enabled), [busy, setBusy] = useState(false);
  async function flip(){
    setBusy(true);
    try { await rpc("admin_set_source_enabled", {target_source: id, enabled: !on}); setOn(!on); router.refresh(); }
    catch (e) { alert((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="srcToggle">{type === "drone" ? "✈" : "▣"} {name}
    <button className={on ? "on" : ""} disabled={busy} onClick={flip} title={on ? "Switch off" : "Switch on"}>{on ? "ON" : "OFF"}</button></div>;
}

export function RenameClient({orgId, name}: {orgId: string; name: string}){
  const router = useRouter();
  const [editing, setEditing] = useState(false), [value, setValue] = useState(name), [busy, setBusy] = useState(false);
  if (!editing) return <button className="ghost" onClick={() => setEditing(true)}>Rename</button>;
  return <form className="deviceEdit" onSubmit={async e => { e.preventDefault(); setBusy(true);
      try { await rpc("admin_rename_organization", {target_org: orgId, new_name: value}); setEditing(false); router.refresh(); }
      catch (err) { alert((err as Error).message); } finally { setBusy(false); } }}>
    <input value={value} minLength={2} maxLength={120} required autoFocus onChange={e => setValue(e.target.value)} aria-label="Client name"/>
    <button className="btn small" disabled={busy}>Save</button><button type="button" className="ghost small" onClick={() => { setValue(name); setEditing(false); }}>Cancel</button>
  </form>;
}
