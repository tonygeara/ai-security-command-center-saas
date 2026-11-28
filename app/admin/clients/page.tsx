import Link from "next/link";
import {createClient} from "../../../lib/supabase/server";
import {buildClients, loadAdminData} from "../../../lib/admin";
import ClientsTable from "./ClientsTable";
import NewClient from "./NewClient";

export default async function Clients(){
  const clients = buildClients(await loadAdminData(await createClient()));
  // Only what the table needs (no licence files) goes to the browser.
  const rows = clients.map(({license, org, ...c}) => ({...c, hasDetails: !!license}));
  return <>
    <div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Clients</h1><p className="muted">Every client, online (SaaS) and on-prem, with their licence, contact and payment. Click a client for everything about them: licence file, renew, edit, revoke.</p></div>
      <div className="portalActions"><NewClient/><Link className="ghost" href="/admin/licenses?new=onprem">+ New on-prem client</Link></div></div>
    <ClientsTable rows={rows}/>
  </>;
}
