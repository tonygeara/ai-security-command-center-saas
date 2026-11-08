"use client";
import {useState} from "react";
import {createClient} from "../../../lib/supabase/client";

// Choose your own password: required after an admin made your account or reset your password.
export default function ChangePassword() {
  const [p1, setP1] = useState(""), [p2, setP2] = useState(""), [msg, setMsg] = useState(""), [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (p1.length < 10) { setMsg("Use at least 10 characters."); return; }
    if (p1 !== p2) { setMsg("The two passwords are different."); return; }
    setBusy(true); setMsg("Saving…");
    const supabase = createClient();
    const {error} = await supabase.auth.updateUser({password: p1, data: {must_change_password: false}});
    if (error) { setMsg(error.message); setBusy(false); return; }
    const {data: {user}} = await supabase.auth.getUser();
    const {data: sa} = user ? await supabase.from("super_admins").select("user_id").eq("user_id", user.id).maybeSingle() : {data: null};
    window.location.assign(sa ? "/admin" : "/portal");
  }
  return <main className="shell"><div className="brand">AI SECURITY COMMAND CENTER</div>
    <div className="card login-card"><h1>Choose your password</h1>
      <p className="muted">Your account was made (or its password reset) by an admin. Choose a password only you know.</p>
      <form className="login-form" onSubmit={submit}>
        <input type="password" placeholder="New password (10+ characters)" autoComplete="new-password" value={p1} onChange={e => setP1(e.target.value)} required/>
        <input type="password" placeholder="New password again" autoComplete="new-password" value={p2} onChange={e => setP2(e.target.value)} required/>
        <button disabled={busy}>{busy ? "Saving…" : "Save password"}</button>
      </form><p className="muted">{msg}</p></div></main>;
}
