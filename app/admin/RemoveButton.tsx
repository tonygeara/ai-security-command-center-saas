"use client";
import {useState} from "react";
import {useRouter} from "next/navigation";
import {createClient} from "../../lib/supabase/client";

// Calls one of the admin_remove_* functions after a confirmation; then refreshes or goes elsewhere.
export default function RemoveButton({rpc, args, label, confirmText, goTo, small = true}: {rpc: string; args: Record<string, string>; label: string; confirmText: string; goTo?: string; small?: boolean}){
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function run(e: React.MouseEvent){
    e.stopPropagation();
    if(!confirm(confirmText)) return;
    setBusy(true);
    const {error} = await createClient().rpc(rpc, args);
    setBusy(false);
    if(error){ alert(error.message); return; }
    if(goTo) router.push(goTo); else router.refresh();
  }
  return <button className={"ghost danger" + (small ? " small" : "")} disabled={busy} onClick={run}>{busy ? "Removing…" : label}</button>;
}
