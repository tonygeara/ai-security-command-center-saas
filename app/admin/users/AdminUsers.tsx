"use client";
// Super admin: every account, whatever company it belongs to. Add anyone to any client, edit, block,
// new password, super admin rights, delete. The rules live in the manage-users function.
import {useCallback, useEffect, useMemo, useState} from "react";
import Link from "next/link";
import {useRouter} from "next/navigation";
import {createClient} from "../../../lib/supabase/client";

type Row = {user_id: string; email: string; full_name: string | null; last_sign_in_at: string | null; organization_id: string | null;
  organization_name: string | null; role: string | null; client_key: string | null};
type Acc = {user_id: string; blocked: boolean; super: boolean; must_change_password: boolean};
const ROLE: Record<string, string> = {owner: "Admin", admin: "Admin", member: "Editor", viewer: "Viewer"};

async function call(body: Record<string, unknown>) {
  const {data, error} = await createClient().functions.invoke("manage-users", {body});
  if (error) {
    let msg = error.message;
    try { const j = await (error as {context?: Response}).context?.json(); if (j?.error) msg = j.error; } catch {}
    throw new Error(msg);
  }
  return data;
}

export default function AdminUsers({rows, clients}: {rows: Row[]; clients: {orgId: string; name: string}[]}){
  const router = useRouter();
  const [acc, setAcc] = useState<Record<string, Acc>>({}), [me, setMe] = useState("");
  const [q, setQ] = useState(""), [msg, setMsg] = useState(""), [bad, setBad] = useState(false), [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<{who: string; password: string} | null>(null), [arm, setArm] = useState("");
  const [edit, setEdit] = useState<{user_id: string; email: string; full_name: string} | null>(null);
  const [add, setAdd] = useState({org: clients[0]?.orgId ?? "", email: "", full_name: "", role: "viewer"}), [superEmail, setSuperEmail] = useState("");

  const load = useCallback(async () => {
    try { const d = await call({action: "account_list"}); setMe(d.me); setAcc(Object.fromEntries(d.accounts.map((a: Acc) => [a.user_id, a]))); }
    catch (e) { setBad(true); setMsg((e as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function run(label: string, body: Record<string, unknown>, who = "") {
    setBusy(true); setMsg(""); setBad(false);
    try {
      const d = await call(body);
      if (d?.temp_password) setSecret({who, password: d.temp_password});
      setMsg(label); await load(); router.refresh(); return true;
    } catch (e) { setBad(true); setMsg((e as Error).message); return false; }
    finally { setBusy(false); setArm(""); }
  }
  const confirmRun = (key: string, label: string, body: Record<string, unknown>, who = "") => arm === key ? run(label, body, who) : setArm(key);

  // one line per account, with all the companies it belongs to
  const people = useMemo(() => {
    const m = new Map<string, Row & {orgs: Row[]}>();
    for (const r of rows) { const p = m.get(r.user_id) ?? {...r, orgs: []}; if (r.organization_id) p.orgs.push(r); m.set(r.user_id, p); }
    const s = q.trim().toLowerCase();
    return [...m.values()].filter(p => !s || [p.email, p.full_name, ...p.orgs.map(o => o.organization_name)].join(" ").toLowerCase().includes(s));
  }, [rows, q]);

  return <>
    {secret && <div className="card secretBox"><b>Temporary password for {secret.who}</b><code>{secret.password}</code>
      <p className="muted small">Give it to them privately. It is shown only now; they choose their own password when they first sign in.</p>
      <button className="ghost" onClick={() => setSecret(null)}>Done</button></div>}
    {msg && <p className={bad ? "locked" : "ok"} role="status">{msg}</p>}
    <div className="clientTools"><input className="search" placeholder="Search name, email or client…" value={q} onChange={e => setQ(e.target.value)}/></div>
    <div className="card tableWrap"><table className="adminTable"><thead><tr><th>User</th><th>Client & role</th><th>Last sign-in</th><th>Actions</th></tr></thead><tbody>
      {people.map(p => { const a = acc[p.user_id], mine = p.user_id === me; return <tr key={p.user_id}>
        <td>{edit?.user_id === p.user_id ? <form className="inlineEdit" onSubmit={e => { e.preventDefault();
            void run(`${edit.email} saved.`, {action: "account_update", user_id: p.user_id, email: edit.email, full_name: edit.full_name}).then(ok => ok && setEdit(null)); }}>
            <input value={edit.full_name} placeholder="Full name" onChange={e => setEdit({...edit, full_name: e.target.value})}/>
            <input type="email" value={edit.email} required onChange={e => setEdit({...edit, email: e.target.value})}/>
            <div className="rowActions"><button className="btn small" disabled={busy}>Save</button><button type="button" className="ghost" onClick={() => setEdit(null)}>Cancel</button></div></form>
          : <><b>{p.full_name || p.email}</b>{mine && <span className="muted"> (you)</span>}<div className="muted">{p.email}</div>
            <div className="tags">{a?.super && <span className="badge">SUPER ADMIN</span>}{a?.blocked && <span className="badge locked">BLOCKED</span>}
              {a?.must_change_password && <span className="muted small">has not chosen a password yet</span>}</div></>}</td>
        <td>{p.orgs.length ? p.orgs.map(o => <div key={o.organization_id}>{o.client_key ? <Link href={"/admin/clients/" + o.client_key}>{o.organization_name}</Link> : o.organization_name}
            <span className="muted"> · {ROLE[o.role ?? ""] ?? o.role}</span></div>) : <span className="muted">No client</span>}</td>
        <td className="muted">{p.last_sign_in_at ? new Date(p.last_sign_in_at).toLocaleString() : "Never"}</td>
        <td>{mine ? <Link className="ghost small" href="/account/password">Change my password</Link> : <div className="rowActions">
          <button className="ghost" disabled={busy} onClick={() => setEdit({user_id: p.user_id, email: p.email, full_name: p.full_name ?? ""})}>Edit</button>
          <button className="ghost" disabled={busy} onClick={() => run(`New temporary password made for ${p.email}.`, {action: "account_password", user_id: p.user_id}, p.email)}>New password</button>
          <button className="ghost" disabled={busy || !a} onClick={() => confirmRun("b" + p.user_id, `${p.email} ${a?.blocked ? "can sign in again" : "is blocked"}.`, {action: "account_block", user_id: p.user_id, blocked: !a?.blocked})}>
            {arm === "b" + p.user_id ? "Click again to confirm" : a?.blocked ? "Unblock" : "Block sign-in"}</button>
          <button className="ghost" disabled={busy || !a} onClick={() => confirmRun("s" + p.user_id, `${p.email} ${a?.super ? "is no longer" : "is now"} a super admin.`, {action: "account_super", user_id: p.user_id, on: !a?.super})}>
            {arm === "s" + p.user_id ? "Click again to confirm" : a?.super ? "Remove super admin" : "Make super admin"}</button>
          <button className="ghost danger" disabled={busy} onClick={() => confirmRun("d" + p.user_id, `${p.email} deleted.`, {action: "account_delete", user_id: p.user_id})}>
            {arm === "d" + p.user_id ? "Click again to delete" : "Delete account"}</button></div>}</td></tr>; })}
      {!people.length && <tr><td colSpan={4} className="muted">No users match.</td></tr>}
    </tbody></table></div>
    <p className="muted">{people.length} account{people.length === 1 ? "" : "s"}. Role changes for a company&apos;s users are on that client&apos;s page.</p>

    <section className="detailGrid">
      <form className="card addUser" onSubmit={async e => { e.preventDefault();
        if (await run(`${add.email} added.`, {action: "create", org: add.org, email: add.email.trim().toLowerCase(), full_name: add.full_name, role: add.role}, add.email))
          setAdd({...add, email: "", full_name: ""}); }}>
        <h3>Add a user to a client</h3>
        <select value={add.org} required onChange={e => setAdd({...add, org: e.target.value})} aria-label="Client">
          {!clients.length && <option value="">No online clients yet</option>}
          {clients.map(c => <option key={c.orgId} value={c.orgId}>{c.name}</option>)}</select>
        <input type="email" placeholder="Email" required value={add.email} onChange={e => setAdd({...add, email: e.target.value})}/>
        <input placeholder="Full name" value={add.full_name} onChange={e => setAdd({...add, full_name: e.target.value})}/>
        <select value={add.role} onChange={e => setAdd({...add, role: e.target.value})} aria-label="Role">
          <option value="admin">Admin</option><option value="member">Editor</option><option value="viewer">Viewer</option></select>
        <button disabled={busy || !add.org}>{busy ? "Working…" : "Add user"}</button>
      </form>
      <form className="card addUser" onSubmit={async e => { e.preventDefault();
        if (await run(`${superEmail} is now a super admin.`, {action: "account_add_super", email: superEmail.trim()})) setSuperEmail(""); }}>
        <h3>Add a super admin</h3>
        <p className="muted small" style={{gridColumn: "1/-1", margin: 0}}>Gives an existing account full control of every client, like you. Only for people you fully trust.</p>
        <input type="email" placeholder="Their account email" required value={superEmail} onChange={e => setSuperEmail(e.target.value)}/>
        <button disabled={busy}>Make super admin</button>
      </form>
    </section>
  </>;
}
