import {redirect} from "next/navigation";
import {createClient} from "../../../lib/supabase/server";
import LicenseManager from "./LicenseManager";

export default async function Licenses({searchParams}: {searchParams: Promise<Record<string, string>>}){
 const open = await searchParams;
 // The client list is the Clients page; this page only opens with a licence form to show.
 if(!(open.new || open.edit || open.renew || open.org)) redirect("/admin/clients");
 const supabase=await createClient();
 const [{data:licenses},{data:orgs},{data:limits}]=await Promise.all([
  supabase.from("client_licenses").select("*").order("created_at",{ascending:false}),
  supabase.from("organizations").select("id,name,plan_code,status").order("name"),
  supabase.from("feature_entitlements").select("organization_id,feature_key,enabled,limit_value").in("feature_key",["camera_ai","drone_live"])
 ]);
 return <><div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>{open.renew ? "Renew licence" : open.edit ? "Edit client" : open.org ? "Client details & limits" : "New client licence"}</h1><p className="muted">On-prem: a licence file for the client&apos;s PC. Online: limits, features and contact details.</p></div></div>
 <LicenseManager licenses={licenses??[]} orgs={orgs??[]} limits={limits??[]} open={open}/></>
}
