import {redirect} from "next/navigation";
import {createClient} from "../../../lib/supabase/server";
import SignOut from "../../SignOut";
import LicenseManager from "./LicenseManager";

export default async function Licenses(){
 const supabase=await createClient(); const {data:{user}}=await supabase.auth.getUser(); if(!user)redirect("/login");
 const {data:sa}=await supabase.from("super_admins").select("user_id").eq("user_id",user.id).maybeSingle(); if(!sa)redirect("/unauthorized");
 const [{data:licenses},{data:orgs},{data:limits}]=await Promise.all([
  supabase.from("client_licenses").select("*").order("created_at",{ascending:false}),
  supabase.from("organizations").select("id,name,plan_code,status").order("name"),
  supabase.from("feature_entitlements").select("organization_id,feature_key,enabled,limit_value").in("feature_key",["camera_ai","drone_live"])
 ]);
 return <main className="shell"><div className="brand">AI SECURITY COMMAND CENTER</div>
 <div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Licences & clients</h1><p className="muted">On-prem licence files and online (SaaS) clients in one place · {user.email}</p></div><div className="portalActions"><a className="ghost" href="/admin">Operations Console</a><SignOut/></div></div>
 <LicenseManager licenses={licenses??[]} orgs={orgs??[]} limits={limits??[]}/></main>
}
