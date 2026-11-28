"use client";
import {uiConfirm} from "../../lib/dialog";
import {useEffect, useState} from "react";
import {useRouter} from "next/navigation";
import {createClient} from "../../lib/supabase/client";
import {useEdgeVersions} from "../../lib/useEdgeVersions";

// The version clients on the "Normal" update channel install (their PCs with Settings → Updates on).
export default function ApproveVersion({approved, versions: fromServer}: {approved: string | null; versions: string[]}){
  const router = useRouter();
  const {versions, loading} = useEdgeVersions(fromServer);
  const [v, setV] = useState(versions[0] || ""), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  useEffect(() => { if(!v && versions[0]) setV(versions[0]); }, [versions, v]);
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
    <span role="status" className="muted">{message || (loading ? "Loading the published versions…" : !versions.length ? "Couldn't load the published versions from GitHub; reload the page in a minute." : "")}</span>
  </div>;
}
