"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
export default function UpgradePlans({currentPlan}:{currentPlan:string}){
 const [busy,setBusy]=useState(false);const [message,setMessage]=useState("");
 async function billing(){setBusy(true);setMessage("");try{const {data,error}=await createClient().functions.invoke("create-billing-portal");if(error){setMessage(error.message);return}if(data?.url)location.href=data.url;else setMessage(data?.error||"Unable to open billing. Please try again.")}catch{setMessage("Unable to open billing. Please try again.")}finally{setBusy(false)}}
 return <article className="card"><h3>Account & billing</h3><p className="muted">Current account configuration: {currentPlan.toUpperCase()}. Your enabled features and device limits are managed for your organization.</p><button className="ghost" onClick={billing} disabled={busy}>{busy?"Opening billing…":"Manage billing / Cancel subscription"}</button><p role="status" className="muted">{message}</p></article>
}
