import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import {createClient} from "npm:@supabase/supabase-js@2";
const json=(b:unknown,s=200)=>new Response(JSON.stringify(b),{status:s,headers:{"content-type":"application/json","cache-control":"no-store"}});
const sha=async(s:string)=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(s)))).map(b=>b.toString(16).padStart(2,"0")).join("");
const randomToken=()=>{const b=new Uint8Array(48);crypto.getRandomValues(b);return Array.from(b).map(x=>x.toString(16).padStart(2,"0")).join("")};
Deno.serve(async req=>{
 if(req.method!=="POST")return json({error:"method_not_allowed"},405);
 let body:any={};try{body=await req.json()}catch{return json({error:"invalid_json"},400)}
 const code=String(body.code||"").trim().toUpperCase(), name=String(body.device_name||"Windows Edge").trim().slice(0,80);
 if(!/^[A-F0-9]{8}$/.test(code))return json({error:"invalid_pairing_code"},400);
 const admin=createClient(Deno.env.get("SUPABASE_URL")!,Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
 const h=await sha(code);
 const {data:p}=await admin.from("device_pairing_codes").select("id,organization_id,site_id,expires_at,used_at").eq("code_hash",h).maybeSingle();
 if(!p||p.used_at||new Date(p.expires_at).getTime()<Date.now())return json({error:"pairing_code_expired_or_invalid"},401);
 const token=randomToken(), tokenHash=await sha(token);
 const {data:d,error}=await admin.from("edge_devices").insert({organization_id:p.organization_id,site_id:p.site_id,device_name:name,platform:"windows",app_version:String(body.app_version||"V9.1"),status:"online",device_token_hash:tokenHash,enrolled_at:new Date().toISOString(),last_seen_at:new Date().toISOString()}).select("id").single();
 if(error)return json({error:"device_create_failed"},500);
 await admin.from("device_pairing_codes").update({used_at:new Date().toISOString()}).eq("id",p.id).is("used_at",null);
 return json({ok:true,device_id:d.id,device_token:token,control_url:"https://qfnxwuejfotofuxlyqjd.supabase.co/functions/v1/edge-agent-control"});
});
