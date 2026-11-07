"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
export default function Onboarding(){
 const [name,setName]=useState(""); const [busy,setBusy]=useState(false); const [msg,setMsg]=useState("");
 async function create(e:React.FormEvent){e.preventDefault();setBusy(true);setMsg("");try{const {error}=await createClient().rpc("create_my_organization",{target_name:name});if(error){setMsg(error.message);setBusy(false);return;}window.location.assign("/portal")}catch(err){setMsg(err instanceof Error?err.message:"Unable to set up your organization. Please try again.");setBusy(false)}}
 return <main className="shell"><a className="brand authBrand" href="/">AI SECURITY COMMAND CENTRE</a><div className="card login-card"><h1>Set up your account</h1><p className="muted">Create your organization and first site, then pair the Windows Edge Agent for local drone and security operations.</p><form className="login-form" onSubmit={create}><label htmlFor="organization">Organization name</label><input id="organization" autoComplete="organization" value={name} onChange={e=>setName(e.target.value)} placeholder="Company or account name" required/><button disabled={busy}>{busy?"Creating...":"Create account"}</button></form><p className="muted" role="status" aria-live="polite">{msg}</p></div></main>
}