"use client";
import {useState} from "react";
import {useRouter} from "next/navigation";
import {createClient} from "../../lib/supabase/client";

// Which version this client's PCs install when their Settings → Updates switch is on.
const CHANNELS: [string, string][] = [
  ["test", "Test: every new version, as soon as it's published"],
  ["normal", "Normal: the version you approve (Overview → Installers)"],
  ["pinned", "Pinned: one version you choose"],
];

export default function UpdateChannel({orgId, initialChannel, initialPinned, versions, approved}:
  {orgId: string; initialChannel: string; initialPinned: string | null; versions: string[]; approved: string | null}){
  const router = useRouter();
  const [channel, setChannel] = useState(initialChannel), [pinned, setPinned] = useState(initialPinned || versions[0] || "");
  const [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  async function save(){
    setBusy(true); setMessage("");
    const {error} = await createClient().rpc("set_update_channel", {target_org: orgId, target_channel: channel,
      target_version: channel === "pinned" ? pinned : null});
    setMessage(error ? error.message : "Saved. Their PCs pick it up within a minute.");
    setBusy(false); if(!error) router.refresh();
  }
  const runs = channel === "test" ? (versions[0] ? `the newest (now ${versions[0]})` : "the newest")
    : channel === "normal" ? (approved || "nothing yet: approve a version first") : pinned;
  return <div>
    <label>Channel<select value={channel} disabled={busy} onChange={e => setChannel(e.target.value)}>
      {CHANNELS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select></label>
    {channel === "pinned" && <label>Version<select value={pinned} disabled={busy} onChange={e => setPinned(e.target.value)}>
      {versions.map(v => <option key={v}>{v}</option>)}</select></label>}
    <p className="muted">Their PCs install: <b>{runs}</b>. Only PCs with Settings → Updates switched on update by themselves,
      and a PC never goes back to an older version on its own.</p>
    <button className="ghost" disabled={busy || (channel === "pinned" && !pinned)} onClick={save}>{busy ? "Saving..." : "Save update channel"}</button>
    <p role="status">{message}</p>
  </div>;
}
