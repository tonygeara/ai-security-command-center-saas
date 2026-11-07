"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";

export default function Signup(){
 const [email,setEmail]=useState(""); const [password,setPassword]=useState("");
 const [confirm,setConfirm]=useState(""); const [message,setMessage]=useState(""); const [busy,setBusy]=useState(false);
 async function submit(e:React.FormEvent){
  e.preventDefault(); if(password!==confirm){setMessage("Passwords do not match.");return}
  if(password.length<8){setMessage("Use at least 8 characters.");return}
  setBusy(true); setMessage("Creating account...");
  try{
   const supabase=createClient();
   const {data,error}=await supabase.auth.signUp({email,password,options:{emailRedirectTo:window.location.origin+"/onboarding"}});
   if(error){setMessage(error.message);setBusy(false);return}
   if(data.session){window.location.assign("/onboarding");return}
   setMessage("Account created. Check your email to confirm your address, then sign in.");
  }catch(err){setMessage(err instanceof Error?err.message:"Unable to create account.")}
  setBusy(false);
 }
 return <main className="shell"><a className="brand authBrand" href="/">AI SECURITY COMMAND CENTRE</a><div className="card login-card">
  <h1>Create account</h1><p className="muted">Create your organization, then pair your Windows Edge Agent. Drone video, telemetry and patrol controls run in the local dashboard with compatible equipment.</p>
  <form className="login-form" onSubmit={submit}>
   <label htmlFor="email">Email address</label><input id="email" autoComplete="email" type="email" placeholder="Email" value={email} onChange={e=>setEmail(e.target.value)} required/>
   <label htmlFor="password">Password (at least 8 characters)</label><input id="password" minLength={8} autoComplete="new-password" type="password" placeholder="Password (8+ characters)" value={password} onChange={e=>setPassword(e.target.value)} required/>
   <label htmlFor="confirm">Confirm password</label><input id="confirm" minLength={8} autoComplete="new-password" type="password" placeholder="Confirm password" value={confirm} onChange={e=>setConfirm(e.target.value)} required/>
   <button disabled={busy}>{busy?"Creating...":"Create account"}</button>
  </form><p className="muted" role="status" aria-live="polite">{message}</p><p className="muted">Already have an account? <a href="/login">Sign in</a></p>
 </div></main>
}