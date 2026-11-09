"use client";
import {useState} from "react";
import {createClient} from "../../../lib/supabase/client";

// Super admin: make an online client and its admin in one go. The admin gets a temporary password.
export default function NewClient() {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [msg, setMsg] = useState("");
  const [f, setF] = useState({name: "", admin_email: "", admin_name: "", status: "trial"});
  const [done, setDone] = useState<{org: string, password: string | null, email: string} | null>(null);
  const set = (k: string, v: string) => setF(x => ({...x, [k]: v}));
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setMsg("");
    const {data, error} = await createClient().functions.invoke("manage-users", {body: {action: "create_client", ...f}});
    if (error) {
      let m = error.message;
      try { const j = await (error as {context?: Response}).context?.json(); if (j?.error) m = j.error; } catch {}
      setMsg(m); setBusy(false); return;
    }
    setDone({org: data.org, password: data.temp_password, email: f.admin_email}); setBusy(false);
  }
  if (!open) return <button className="btn" onClick={() => setOpen(true)}>+ New online client</button>;
  return <div className="card newClient">
    {done ? <>
      <h3>Client created</h3>
      <p>Admin: <b>{done.email}</b></p>
      {done.password ? <><p>Temporary password (shown only now):</p><code className="secret">{done.password}</code>
        <p className="muted small">Give it to them privately; they choose their own at first sign-in.</p></>
        : <p className="muted">That email already had an account; it keeps its password.</p>}
      <p className="muted small">Next: set their cameras, drones and user places on the Licences page.</p>
      <div className="actions"><a className="btn small" href={`/admin/licenses?org=${done.org}`}>Set their licence</a>
        <button className="ghost" onClick={() => window.location.reload()}>Close</button></div>
    </> : <form onSubmit={submit} className="login-form">
      <h3>New online client</h3>
      <input placeholder="Company name" value={f.name} onChange={e => set("name", e.target.value)} required/>
      <input type="email" placeholder="Admin's email" value={f.admin_email} onChange={e => set("admin_email", e.target.value)} required/>
      <input placeholder="Admin's full name" value={f.admin_name} onChange={e => set("admin_name", e.target.value)}/>
      <select value={f.status} onChange={e => set("status", e.target.value)}><option value="trial">Trial</option><option value="active">Active</option></select>
      <div className="actions"><button disabled={busy}>{busy ? "Creating…" : "Create client and admin"}</button>
        <button type="button" className="ghost" onClick={() => setOpen(false)}>Cancel</button></div>
      <p className="locked">{msg}</p>
    </form>}
  </div>;
}
