"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
const PLANS=[["home","Home","C$19/mo"],["pro","Pro","C$49/mo"],["business","Business","C$129/mo"]] as const;
export default function UpgradePlans({currentPlan}:{currentPlan:string}){
 const [busy,setBusy]=useState("");
 const rank:Record<string,number>={trial:0,home:1,pro:2,business:3};
 async function buy(plan:string){setBusy(plan);const sb=createClient();const {data:{session}}=await sb.auth.getSession();if(!session){location.href="/login";return}
 const {data,error}=await sb.functions.invoke("create-checkout-session",{body:{plan_code:plan}});if(error){alert(`Checkout error: ${error.message}`);setBusy("");return}if(data?.url)location.href=data.url;else{alert(data?.error||"Unable to start checkout");setBusy("")}}
 return <section className="grid">{PLANS.map(([code,name,price])=>{const current=code===currentPlan;const upgrade=(rank[code]??0)>(rank[currentPlan]??0);return <article className="card" key={code}><h2>{name}</h2><strong>{price}</strong>{current?<><p className="ok">✓ Current plan</p><button disabled>Current plan</button></>:<p><button onClick={()=>buy(code)} disabled={!!busy}>{busy===code?"Opening Stripe...":upgrade?"Upgrade":"Change plan"}</button></p>}</article>})}</section>
}