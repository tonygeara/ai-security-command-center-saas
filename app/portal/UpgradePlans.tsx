"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
const PLANS=[["home","Home","C$19/mo"],["pro","Pro","C$49/mo"],["business","Business","C$129/mo"]] as const;
export default function UpgradePlans(){
 const [busy,setBusy]=useState("");
 async function buy(plan:string){setBusy(plan);const sb=createClient();const {data:{session}}=await sb.auth.getSession();if(!session){location.href="/login";return}
 const {data,error}=await sb.functions.invoke("create-checkout-session",{body:{plan_code:plan}});if(error){alert(`Checkout error: ${error.message}`);setBusy("");return}if(data?.url)location.href=data.url;else{alert(data?.error||"Unable to start checkout");setBusy("")}}
 return <section className="grid">{PLANS.map(([code,name,price])=><article className="card" key={code}><h2>{name}</h2><strong>{price}</strong><p><button onClick={()=>buy(code)} disabled={!!busy}>{busy===code?"Opening Stripe...":"Choose plan"}</button></p></article>)}</section>
}