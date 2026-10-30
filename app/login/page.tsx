"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
export default function Login(){
 const [email,setEmail]=useState("");const [password,setPassword]=useState("");const [message,setMessage]=useState("");const [busy,setBusy]=useState(false);
 async function submit(e:React.FormEvent){e.preventDefault();setBusy(true);setMessage("Signing in...");try{const supabase=createClient();const {error}=await supabase.auth.signInWithPassword({email,password});if(error){setMessage(error.message);setBusy(false);return;}const {data:{user}}=await supabase.auth.getUser();if(user){const {data:admin}=await supabase.from("super_admins").select("user_id").eq("user_id",user.id).maybeSingle();window.location.assign(admin?"/admin":"/portal");}}catch(err){setMessage(err instanceof Error?err.message:"Unable to sign in.");setBusy(false)}}
 return <main className="shell"><a href="/" className="authBack">← Back to home</a><div className="brand">AI SECURITY COMMAND CENTER</div><div className="card login-card">
  <h1>Sign in</h1><p className="muted">Welcome back. Sign in to manage your system.</p>
  <form className="login-form" onSubmit={submit}>
   <label>Email<input type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={e=>setEmail(e.target.value)} required/></label>
   <label>Password<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required/></label>
   <button disabled={busy}>{busy?"Signing in...":"Sign in"}</button>
  </form>
  <p className="muted formMsg" role="status" aria-live="polite">{message}</p>
  <p className="muted">New customer? <a href="/signup">Create an account</a></p>
 </div></main>
}
