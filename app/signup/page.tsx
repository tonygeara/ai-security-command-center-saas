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
 return <main className="shell"><a href="/" className="authBack">← Back to home</a><div className="brand">AI SECURITY COMMAND CENTER</div><div className="card login-card">
  <h1>Create your account</h1><p className="muted">Sign up here, then install the Command Center app on a Windows PC and pair it with your account.</p>
  <form className="login-form" onSubmit={submit}>
   <label>Email<input type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={e=>setEmail(e.target.value)} required/></label>
   <label>Password<input type="password" autoComplete="new-password" placeholder="At least 8 characters" minLength={8} value={password} onChange={e=>setPassword(e.target.value)} required/></label>
   <label>Confirm password<input type="password" autoComplete="new-password" value={confirm} onChange={e=>setConfirm(e.target.value)} required/></label>
   <button disabled={busy}>{busy?"Creating...":"Create account"}</button>
  </form><p className="muted formMsg" role="status" aria-live="polite">{message}</p><p className="muted">Already have an account? <a href="/login">Sign in</a></p>
 </div></main>
}