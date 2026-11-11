import {createClient} from "../../../lib/supabase/server";
import {buildClients, loadAdminData} from "../../../lib/admin";
import AdminUsers from "./AdminUsers";

export default async function Users(){
  const data = await loadAdminData(await createClient());
  const clients = buildClients(data);
  const keyOf = (orgId?: string | null) => clients.find(c => c.orgId === orgId)?.key ?? null;
  const rows = data.users.map(u => ({user_id: u.user_id, email: u.email, full_name: u.full_name ?? null, last_sign_in_at: u.last_sign_in_at ?? null,
    organization_id: u.organization_id ?? null, organization_name: u.organization_name ?? null, role: u.role ?? null, client_key: keyOf(u.organization_id)}));
  return <>
    <div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Users</h1>
      <p className="muted">Every portal account across all clients: add, edit, block, reset passwords, give super admin rights or delete.</p></div></div>
    <AdminUsers rows={rows} clients={clients.filter(c => c.orgId).map(c => ({orgId: c.orgId!, name: c.name}))}/>
  </>;
}
