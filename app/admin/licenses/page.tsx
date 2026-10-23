import {createClient} from "../../../lib/supabase/server";
import LicenseManager from "./LicenseManager";

export default async function Licenses({searchParams}: {searchParams: Promise<Record<string, string>>}){
 const open = await searchParams;
 const supabase=await createClient();
 const [{data:licenses},{data:orgs},{data:limits}]=await Promise.all([
  supabase.from("client_licenses").select("*").order("created_at",{ascending:false}),
  supabase.from("organizations").select("id,name,plan_code,status").order("name"),
  supabase.from("feature_entitlements").select("organization_id,feature_key,enabled,limit_value").in("feature_key",["camera_ai","drone_live"])
 ]);
 return <><div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Licences</h1><p className="muted">Issue, renew and download on-prem licence files; set limits and contact details for online clients.</p></div></div>
 <LicenseManager licenses={licenses??[]} orgs={orgs??[]} limits={limits??[]} open={open}/></>
}
