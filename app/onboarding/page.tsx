"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
export default function Onboarding(){
 const [name,setName]=useState(""); const [busy,setBusy]=useState(false); const [msg,setMsg]=useState("");
 async function create(e:React.FormEvent){e.preventDefault();setBusy(true);const {error}=await createClient().rpc("create_my_organization",{target_name:name});if(error){setMsg(error.message);setBusy(false);return;}window.location.assign("/portal")}
 return <main className="shell"><div className="brand">AI SECURITY COMMAND CENTER</div><div className="card login-card"><h1>Set up your account</h1><p className="muted">Create your organization and first site.</p><form className="login-form" onSubmit={create}><input value={name} onChange={e=>setName(e.target.value)} placeholder="Company or account name" required/><button disabled={busy}>{busy?"Creating...":"Create account"}</button></form><p className="muted">{msg}</p></div></main>
}