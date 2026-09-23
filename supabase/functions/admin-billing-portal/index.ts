import {createClient} from "https://esm.sh/@supabase/supabase-js@2";
const origins=new Set(["https://www.aisecuritycommandcenter.com","https://aisecuritycommandcenter.com","https://ai-security-command-center-saas.vercel.app"]);
Deno.serve(async(req:Request)=>{
 const origin=req.headers.get("Origin")||"";
 const headers={"Content-Type":"application/json","Access-Control-Allow-Origin":origins.has(origin)?origin:"https://www.aisecuritycommandcenter.com","Access-Control-Allow-Headers":"authorization,x-client-info,apikey,content-type","Access-Control-Allow-Methods":"POST,OPTIONS","Vary":"Origin"};
 const reply=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers});
 if(origin&&!origins.has(origin))return reply({error:"Origin not allowed"},403);
 if(req.method==="OPTIONS")return new Response(null,{status:204,headers});
 if(req.method!=="POST")return reply({error:"Method not allowed"},405);
 try{
  const auth=req.headers.get("Authorization");if(!auth)return reply({error:"Sign in required"},401);
  const sb=createClient(Deno.env.get("SUPABASE_URL")!,Deno.env.get("SUPABASE_ANON_KEY")!,{global:{headers:{Authorization:auth}}});
  const {data:{user},error:authError}=await sb.auth.getUser();if(authError||!user)return reply({error:"Sign in required"},401);
  const {data:admin}=await sb.from("super_admins").select("user_id").eq("user_id",user.id).maybeSingle();if(!admin)return reply({error:"Super admin required"},403);
  const {organization_id,destination}=await req.json();if(typeof organization_id!=="string"||!/^[0-9a-f-]{36}$/i.test(organization_id))return reply({error:"Invalid organization"},400);
  const {data:sub,error}=await sb.from("subscriptions").select("provider_customer_id,provider_subscription_id").eq("organization_id",organization_id).maybeSingle();
  if(error||!sub?.provider_customer_id||!sub?.provider_subscription_id)return reply({error:"No paid Stripe subscription for this customer"},400);
  const secret=Deno.env.get("STRIPE_SECRET_KEY");if(!secret)return reply({error:"Billing is not configured"},503);
  if(destination==="admin")return reply({url:"https://dashboard.stripe.com/"+(/^(sk|rk)_test_/.test(secret)?"test/":"")+"subscriptions/"+encodeURIComponent(sub.provider_subscription_id)});
  const response=await fetch("https://api.stripe.com/v1/billing_portal/sessions",{method:"POST",headers:{Authorization:"Bearer "+secret,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({customer:sub.provider_customer_id,return_url:"https://www.aisecuritycommandcenter.com/portal?organization="+organization_id})});
  const result=await response.json();if(!response.ok||!result.url)return reply({error:"Stripe could not open billing. Check the Stripe portal configuration."},502);
  return reply({url:result.url});
 }catch{return reply({error:"Unable to open billing"},500);}
});
