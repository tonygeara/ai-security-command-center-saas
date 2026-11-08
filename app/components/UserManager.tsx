"use client";
import {useCallback, useEffect, useState} from "react";
import {createClient} from "../../lib/supabase/client";

// One company's portal users: list, add, change role, reset password, remove. Used by the client's admin
// (/portal/users: Viewers and Editors) and by the super admin (client page: any role). The rules live in
// the manage-users function; this only shows what it allows.
type U = {user_id: string, email: string, full_name: string, role: string, role_name: string, last_sign_in_at: string | null,
          must_change_password: boolean, is_me: boolean, can_manage: boolean};
type Seats = {used: number, max_users: number, can_add: boolean, reason: string};
const ROLE_LABEL: Record<string, string> = {admin: "Admin: manages the company's users and PCs", member: "Editor: can change cameras, sites and PCs",
  viewer: "Viewer: can see everything, change nothing"};
const SHORT: Record<string, string> = {admin: "Admin", owner: "Admin", member: "Editor", viewer: "Viewer"};

async function call(body: Record<string, unknown>) {
  const {data, error} = await createClient().functions.invoke("manage-users", {body});
  if (error) {
    let msg = error.message;
    try { const j = await (error as {context?: Response}).context?.json(); if (j?.error) msg = j.error; } catch {}
    throw new Error(msg);
  }
  return data;
}

export default function UserManager({orgId}: {orgId: string}) {
  const [users, setUsers] = useState<U[]>([]), [seats, setSeats] = useState<Seats | null>(null), [roles, setRoles] = useState<string[]>([]);
  const [email, setEmail] = useState(""), [name, setName] = useState(""), [role, setRole] = useState("viewer");
  const [msg, setMsg] = useState(""), [bad, setBad] = useState(false), [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<{who: string, password: string} | null>(null), [arm, setArm] = useState("");

  const load = useCallback(async () => {
    try { const d = await call({action: "list", org: orgId}); setUsers(d.users); setSeats(d.seats); setRoles(d.roles); }
    catch (e) { setBad(true); setMsg((e as Error).message); }
  }, [orgId]);
  useEffect(() => { void load(); }, [load]);

  async function run(label: string, body: Record<string, unknown>, who = "") {
    setBusy(true); setMsg(""); setBad(false);
    try {
      const d = await call({org: orgId, ...body});
      if (d?.temp_password) setSecret({who, password: d.temp_password});
      setMsg(label); await load();
      return true;
    } catch (e) { setBad(true); setMsg((e as Error).message); return false; }
    finally { setBusy(false); setArm(""); }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (await run(`${email} added.`, {action: "create", email, full_name: name, role}, email)) { setEmail(""); setName(""); }
  }

  return <div className="userMgr">
    {seats && <p className="muted">{seats.used} of {seats.max_users} user places used.{!seats.can_add && seats.reason ? " " + seats.reason : ""}</p>}
    {secret && <div className="card secretBox"><b>Temporary password for {secret.who}</b>
      <code>{secret.password}</code>
      <p className="muted small">Give it to them privately. It is shown only now; they choose their own password when they first sign in.</p>
      <button className="ghost" onClick={() => setSecret(null)}>Done</button></div>}
    <div className="tableWrap"><table className="adminTable"><thead><tr><th>User</th><th>Role</th><th>Last sign-in</th><th></th></tr></thead><tbody>
      {users.map(u => <tr key={u.user_id}>
        <td><b>{u.full_name || u.email}</b>{u.is_me && <span className="muted"> (you)</span>}<div className="muted">{u.email}</div>
          {u.must_change_password && <div className="muted small">Has not chosen a password yet</div>}</td>
        <td>{u.can_manage ? <select value={u.role === "owner" ? "admin" : u.role} disabled={busy}
            onChange={e => run(`${u.email} is now ${SHORT[e.target.value]}.`, {action: "set_role", user_id: u.user_id, role: e.target.value})}>
            {[...new Set([...(roles.includes(u.role) ? [] : [u.role === "owner" ? "admin" : u.role]), ...roles])].map(r => <option key={r} value={r}>{SHORT[r]}</option>)}</select>
          : SHORT[u.role] || u.role}</td>
        <td className="muted">{u.last_sign_in_at ? new Date(u.last_sign_in_at).toLocaleString() : "Never"}</td>
        <td>{u.can_manage && <div className="rowActions">
          <button className="ghost" disabled={busy} onClick={() => run(`New temporary password made for ${u.email}.`, {action: "reset_password", user_id: u.user_id}, u.email)}>New password</button>
          <button className="ghost danger" disabled={busy} onClick={() => arm === u.user_id ? run(`${u.email} removed.`, {action: "remove", user_id: u.user_id}) : setArm(u.user_id)}>
            {arm === u.user_id ? "Click again to remove" : "Remove"}</button></div>}</td>
      </tr>)}
      {!users.length && <tr><td colSpan={4} className="muted">Loading…</td></tr>}
    </tbody></table></div>
    <form className="addUser" onSubmit={add}>
      <h3>Add a user</h3>
      <input type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} required/>
      <input placeholder="Full name" value={name} onChange={e => setName(e.target.value)}/>
      <select value={role} onChange={e => setRole(e.target.value)}>{roles.map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select>
      <button disabled={busy || (seats ? !seats.can_add && !roles.includes("admin") : false)}>{busy ? "Working…" : "Add user"}</button>
    </form>
    <p className={bad ? "locked" : "ok"}>{msg}</p>
  </div>;
}
