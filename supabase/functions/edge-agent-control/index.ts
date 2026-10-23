import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import {createClient} from "npm:@supabase/supabase-js@2";
import {signLicense} from "./license.ts";
const LEASE_DAYS=7;
const json=(b:unknown,s=200)=>new Response(JSON.stringify(b),{status:s,headers:{"content-type":"application/json","cache-control":"no-store"}});
const hex=async(s:string)=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(s)))).map(b=>b.toString(16).padStart(2,"0")).join("");
Deno.serve(async req=>{if(req.method!=="POST")return json({error:"method_not_allowed"},405);const token=req.headers.get("x-device-token")||"";if(token.length<32)return json({error:"unauthorized"},401);
const admin=createClient(Deno.env.get("SUPABASE_URL")!,Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!),hash=await hex(token);
const {data:d,error}=await admin.from("edge_devices").select("id,organization_id,device_name,status").eq("device_token_hash",hash).maybeSingle();if(error||!d||d.status==="disabled")return json({error:"unauthorized"},401);
const ip=(req.headers.get("x-forwarded-for")||"").split(",")[0].trim()||null;await admin.from("edge_devices").update({status:"online",last_seen_at:new Date().toISOString(),last_ip:ip,updated_at:new Date().toISOString()}).eq("id",d.id);
const {data:o}=await admin.from("organizations").select("plan_code,status").eq("id",d.organization_id).single();const {data:pf}=await admin.from("plan_features").select("feature_key,enabled,limit_value").eq("plan_code",o?.plan_code||"");const {data:ov}=await admin.from("feature_entitlements").select("feature_key,enabled,limit_value").eq("organization_id",d.organization_id);
const features:Record<string,{enabled:boolean,limit_value:number|null}>={};for(const x of pf||[])features[x.feature_key]={enabled:x.enabled,limit_value:x.limit_value};for(const x of ov||[])features[x.feature_key]={enabled:x.enabled,limit_value:x.limit_value};
const {data:sources}=await admin.from("video_sources").select("source_type").eq("organization_id",d.organization_id);const usage={cameras:(sources||[]).filter(x=>x.source_type==="camera").length,drones:(sources||[]).filter(x=>x.source_type==="drone").length};
const active=["active","trial"].includes(o?.status||"");if(!active)for(const k of Object.keys(features))features[k].enabled=false;
const body:Record<string,unknown>={device_id:d.id,organization_status:o?.status||"unknown",plan_code:o?.plan_code||"unknown",features,usage,limits:{cameras:features.camera_ai?.limit_value??null,drones:features.drone_live?.limit_value??null},server_time:new Date().toISOString()};
// Signed lease: lets the PC keep this plan offline for a few days. Only our key can make one and it is
// bound to this device (hash of its token), so the customer can't edit or copy it.
const pem=Deno.env.get("LICENSE_SIGNING_KEY");if(pem){try{const now=new Date();body.lease=await signLicense({product:"AI Security Command Center",kind:"saas-lease",device:hash,device_id:d.id,organization_status:body.organization_status,plan_code:body.plan_code,features,usage,limits:body.limits,issued_at:now.toISOString(),expires_at:new Date(now.getTime()+LEASE_DAYS*86400000).toISOString()},pem);}catch(e){console.error("lease signing failed",e);}}
return json(body);});
