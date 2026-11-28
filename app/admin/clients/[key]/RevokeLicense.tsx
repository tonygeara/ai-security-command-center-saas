"use client";
import {useState} from "react";
import {useRouter} from "next/navigation";
import {uiAlert, uiConfirm} from "../../../../lib/dialog";
import {createClient} from "../../../../lib/supabase/client";

// Mark a client's licence record as revoked (on the client page; the Licences list it used to be on is merged into Clients).
export default function RevokeLicense({id, name, onprem}: {id: string; name: string; onprem: boolean}){
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function revoke(){
    if(!await uiConfirm(`Mark ${name}'s licence as revoked?` + (onprem ? "\n\nAn on-prem file already installed keeps working until its expiry date (it is offline). Do not renew it." : ""))) return;
    setBusy(true);
    const {error} = await createClient().from("client_licenses").update({status: "revoked"}).eq("id", id);
    setBusy(false);
    if(error) uiAlert(error.message); else router.refresh();
  }
  return <button className="ghost" disabled={busy} onClick={revoke}>{busy ? "Revoking…" : "Revoke licence"}</button>;
}
