"use client";
import {uiConfirm} from "../../lib/dialog";
import {useState} from "react";
import {useRouter} from "next/navigation";
import {createClient} from "../../lib/supabase/client";

// The version clients on the "Normal" update channel install (their PCs with Settings → Updates on).
export default function ApproveVersion({approved, versions}: {approved: string | null; versions: string[]}){
  const router = useRouter();
  const [v, setV] = useState(versions[0] || ""), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  async function approve(){
    if(!await uiConfirm(`Approve ${v}? Every client on the Normal channel installs it (their PCs with Updates on).`)) return;
    setBusy(true); setMessage("");
    const {error} = await createClient().rpc("approve_edge_version", {target_version: v});
    setMessage(error ? error.message : `${v} approved for Normal clients.`);
    setBusy(false); if(!error) router.refresh();
  }
  return <div className="rowActions">
    <span>Approved for Normal clients: <b>{approved || "none yet"}</b></span>
    <select value={v} disabled={busy} onChange={e => setV(e.target.value)}>{versions.map(x => <option key={x}>{x}</option>)}</select>
    <button className="btn small" disabled={busy || !v || v === approved} onClick={approve}
      title={v === approved ? `${v} is already the approved version` : !v ? "No published versions found" : undefined}>
      {busy ? "Saving..." : v && v === approved ? "Approved ✓" : "Approve"}</button>
    <span role="status" className="muted">{message || (!versions.length ? "Couldn't load the published versions from GitHub; reload the page in a minute." : "")}</span>
  </div>;
}
