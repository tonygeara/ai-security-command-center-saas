import Link from "next/link";
import {createClient} from "../../../lib/supabase/server";
import {buildClients, loadAdminData} from "../../../lib/admin";

export default async function Users(){
  const data = await loadAdminData(await createClient());
  const clients = buildClients(data);
  return <>
    <div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Users</h1><p className="muted">Everyone with a portal account and the client they belong to.</p></div></div>
    <div className="card tableWrap"><table className="adminTable"><thead><tr><th>User</th><th>Client</th><th>Role</th><th>Last sign-in</th></tr></thead><tbody>
      {data.users.map(u => { const c = clients.find(x => x.orgId === u.organization_id); return <tr key={u.user_id + String(u.organization_id)}>
        <td><b>{u.full_name || u.email}</b><div className="muted">{u.email}</div></td>
        <td>{c ? <Link href={"/admin/clients/" + c.key}>{c.name}</Link> : u.organization_name || "—"}</td><td>{u.role || "—"}</td>
        <td className="muted">{u.last_sign_in_at ? new Date(u.last_sign_in_at).toLocaleString() : "Never"}</td></tr>; })}
      {!data.users.length && <tr><td colSpan={4} className="muted">No users.</td></tr>}
    </tbody></table></div>
  </>;
}
