import Link from "next/link";
import {createClient} from "../../../lib/supabase/server";
import {buildClients, loadAdminData} from "../../../lib/admin";
import ClientsTable from "./ClientsTable";

export default async function Clients(){
  const clients = buildClients(await loadAdminData(await createClient()));
  // Only what the table needs (no licence files) goes to the browser.
  const rows = clients.map(({license, org, ...c}) => c);
  return <>
    <div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Clients</h1><p className="muted">Online (SaaS) and on-prem clients in one list. Click a client for everything about them.</p></div>
      <div className="portalActions"><Link className="btn" href="/admin/licenses?new=onprem">+ New on-prem client</Link><Link className="ghost" href="/signup" target="_blank">Online sign-up page ↗</Link></div></div>
    <ClientsTable rows={rows}/>
  </>;
}
