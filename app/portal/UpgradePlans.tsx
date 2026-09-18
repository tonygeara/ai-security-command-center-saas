"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
const PLANS=[["home","Home","C$19/mo"],["pro","Pro","C$49/mo"],["business","Business","C$129/mo"]] as const;
export default function UpgradePlans(){
 const [busy,setBusy]=useState("");
 async function buy(plan:string){setBusy(plan);const sb=createClient();const {data:{session}}=await sb.auth.getSession();if(!session){location.href="/login";return}
 const r=await fetch("https://qfnxwuejfotofuxlyqjd.supabase.co/functions/v1/create-checkout-session",{method:"POST",headers:{"Content-Type":"application/json",Authorization:`Bearer ${session.access_token}`,apikey:process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY||""},body:JSON.stringify({plan_code:plan})});
 const d=await r.json();if(d.url)location.href=d.url;else{alert(d.error||"Unable to start checkout");setBusy("")}}
 return <section className="grid">{PLANS.map(([code,name,price])=><article className="card" key={code}><h2>{name}</h2><strong>{price}</strong><p><button onClick={()=>buy(code)} disabled={!!busy}>{busy===code?"Opening Stripe...":"Choose plan"}</button></p></article>)}</section>
}