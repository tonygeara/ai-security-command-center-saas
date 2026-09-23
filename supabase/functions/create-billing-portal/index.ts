import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import {createClient} from "npm:@supabase/supabase-js@2";
Deno.serve(async req=>{
const origin=req.headers.get("Origin")||"";const allowed=new Set(["https://www.aisecuritycommandcenter.com","https://aisecuritycommandcenter.com","https://ai-security-command-center-saas.vercel.app"]);
const cors={"Vary":"Origin","Access-Control-Allow-Origin":allowed.has(origin)?origin:"https://www.aisecuritycommandcenter.com","Access-Control-Allow-Headers":"authorization, x-client-info, apikey, content-type","Access-Control-Allow-Methods":"POST, OPTIONS"};
const j=(b:unknown,s=200)=>new Response(JSON.stringify(b),{status:s,headers:{...cors,"content-type":"application/json"}});
if(origin&&!allowed.has(origin))return j({error:"origin_not_allowed"},403);
if(req.method==="OPTIONS")return new Response("ok",{headers:cors});if(req.method!=="POST")return j({error:"method_not_allowed"},405);
const auth=req.headers.get("authorization")||"";const sb=createClient(Deno.env.get("SUPABASE_URL")!,Deno.env.get("SUPABASE_ANON_KEY")!,{global:{headers:{Authorization:auth}}});
const {data:{user}}=await sb.auth.getUser();if(!user)return j({error:"unauthorized"},401);
const {data:m}=await sb.from("organization_members").select("organization_id,role").eq("user_id",user.id).limit(1).maybeSingle();if(!m||!["owner","admin"].includes(m.role))return j({error:"not_authorized"},403);
const {data:s}=await sb.from("subscriptions").select("provider_customer_id").eq("organization_id",m.organization_id).maybeSingle();if(!s?.provider_customer_id)return j({error:"no_stripe_customer"},400);
const key=Deno.env.get("STRIPE_SECRET_KEY");if(!key)return j({error:"stripe_not_configured"},503);
const body=new URLSearchParams({customer:s.provider_customer_id,return_url:"https://www.aisecuritycommandcenter.com/portal"});
const r=await fetch("https://api.stripe.com/v1/billing_portal/sessions",{method:"POST",headers:{Authorization:`Bearer ${key}`,"Content-Type":"application/x-www-form-urlencoded"},body});const d=await r.json();if(!r.ok)return j({error:d?.error?.message||"portal_error"},400);return j({url:d.url});});