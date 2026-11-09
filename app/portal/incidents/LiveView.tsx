"use client";
import {useEffect, useRef, useState} from "react";
import {createClient} from "../../../lib/supabase/client";

// Asks the edge agent for live pictures of one camera (a live_requests row, 2 minutes at a time),
// then shows the newest picture every 3 seconds. While the page stays open the request is extended.
export default function LiveView({orgId, deviceId, cameras}: {orgId: string, deviceId: string, cameras: string[]}) {
  const [camera, setCamera] = useState("");
  const [img, setImg] = useState("");
  const [note, setNote] = useState("");
  const req = useRef<string | null>(null);

  useEffect(() => {
    if (!camera) return;
    const supabase = createClient();
    let stop = false, last = "";
    const until = () => new Date(Date.now() + 115_000).toISOString();
    (async () => {
      setImg(""); setNote("Asking the PC for pictures… (the first one can take up to 20 s)");
      const {data, error} = await supabase.from("live_requests")
        .insert({organization_id: orgId, device_id: deviceId, camera, active_until: until()}).select("id").single();
      if (error || !data) { setNote(error?.message || "Could not ask for live pictures."); return; }
      req.current = data.id;
      let extended = Date.now();
      while (!stop) {
        const {data: r} = await supabase.from("live_requests").select("last_frame_at,frame_path").eq("id", data.id).single();
        if (r?.frame_path && r.last_frame_at && r.last_frame_at !== last) {
          last = r.last_frame_at;
          const {data: s} = await supabase.storage.from("edge-pictures").createSignedUrl(r.frame_path, 60);
          if (s?.signedUrl) { setImg(s.signedUrl); setNote(`Live · ${new Date(last).toLocaleTimeString()}`); }
        }
        if (Date.now() - extended > 60_000) {  // keep watching: extend by another 2 minutes
          extended = Date.now();
          await supabase.from("live_requests").update({active_until: until()}).eq("id", data.id);
        }
        await new Promise(res => setTimeout(res, 3000));
      }
    })();
    return () => {
      stop = true;
      if (req.current) void supabase.from("live_requests").update({active_until: new Date().toISOString()}).eq("id", req.current);
      req.current = null;
    };
  }, [camera, orgId, deviceId]);

  return <div>
    <div className="liveCams">{cameras.map(c =>
      <button key={c} className={c === camera ? "btn small" : "ghost"} onClick={() => setCamera(c === camera ? "" : c)}>{c === camera ? `■ ${c}` : `▶ ${c}`}</button>)}</div>
    {camera && <div className="liveBox">{img ? <img src={img} alt={`Live picture from ${camera}`}/> : null}<p className="muted small">{note}</p></div>}
  </div>;
}
