import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import {createClient} from "npm:@supabase/supabase-js@2";
const j=(b:unknown,s=200)=>new Response(JSON.stringify(b),{status:s,headers:{"content-type":"application/json","cache-control":"no-store"}});
const sha=async(s:string)=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(s)))).map(x=>x.toString(16).padStart(2,"0")).join("");
Deno.serve(async req=>{if(!["GET","POST","DELETE"].includes(req.method))return j({error:"method_not_allowed"},405);
const token=req.headers.get("x-device-token")||"";if(token.length<32)return j({error:"unauthorized"},401);
const admin=createClient(Deno.env.get("SUPABASE_URL")!,Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const {data:d}=await admin.from("edge_devices").select("id,organization_id,site_id,status").eq("device_token_hash",await sha(token)).maybeSingle();
if(!d||d.status==="disabled")return j({error:"unauthorized"},401);
if(req.method==="GET"){const {data,error}=await admin.from("video_sources").select("id,source_type,name,enabled,created_at").eq("organization_id",d.organization_id).order("created_at");return error?j({error:error.message},400):j({ok:true,sources:data||[]});}
const body=await req.json().catch(()=>({}));
if(req.method==="POST"){const type=String(body.source_type||"").toLowerCase();const name=String(body.name||"").trim().slice(0,120);if(!["camera","drone"].includes(type)||!name)return j({error:"invalid_source"},400);
const {data,error}=await admin.from("video_sources").insert({organization_id:d.organization_id,site_id:d.site_id,edge_device_id:d.id,source_type:type,name,enabled:true}).select("id,source_type,name,enabled").single();
return error?j({error:error.message},409):j({ok:true,source:data},201);}
const id=String(body.id||"");if(!id)return j({error:"id_required"},400);const {error}=await admin.from("video_sources").delete().eq("id",id).eq("organization_id",d.organization_id);return error?j({error:error.message},400):j({ok:true});});
