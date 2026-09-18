"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
export default function PairDevice({orgId,siteId}:{orgId:string,siteId?:string}){
 const [code,setCode]=useState("");const [busy,setBusy]=useState(false);
 async function make(){setBusy(true);const {data,error}=await createClient().rpc("create_device_pairing_code",{target_org:orgId,target_site:siteId||null});if(error)alert(error.message);else setCode(data||"");setBusy(false)}
 return <div><button onClick={make} disabled={busy}>{busy?"Generating...":"Pair a Windows device"}</button>{code&&<div style={{marginTop:12}}><div className="muted">Enter this one-time code in V9.1. Expires in 15 minutes.</div><div style={{fontSize:30,fontWeight:800,letterSpacing:6,marginTop:8}}>{code}</div></div>}</div>
}