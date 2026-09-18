"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
export default function Login(){
 const [email,setEmail]=useState("");const [password,setPassword]=useState("");const [message,setMessage]=useState("");const [busy,setBusy]=useState(false);
 async function submit(e:React.FormEvent){e.preventDefault();setBusy(true);setMessage("Signing in...");try{const supabase=createClient();const {error}=await supabase.auth.signInWithPassword({email,password});if(error){setMessage(error.message);setBusy(false);return;}const {data:{user}}=await supabase.auth.getUser();if(user){const {data:admin}=await supabase.from("super_admins").select("user_id").eq("user_id",user.id).maybeSingle();window.location.assign(admin?"/admin":"/portal");}}catch(err){setMessage(err instanceof Error?err.message:"Unable to sign in.");setBusy(false)}}
 return <main className="shell"><div className="brand">AI SECURITY COMMAND CENTER</div><div className="card login-card"><h1>Sign in</h1><form className="login-form" onSubmit={submit}><input type="email" placeholder="Email" value={email} onChange={e=>setEmail(e.target.value)} required/><input type="password" placeholder="Password" value={password} onChange={e=>setPassword(e.target.value)} required/><button disabled={busy}>{busy?"Signing in...":"Sign in"}</button></form><p className="muted">{message}</p></div></main>
}