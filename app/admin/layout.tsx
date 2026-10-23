import {redirect} from "next/navigation";
import {createClient} from "../../lib/supabase/server";
import {loadAdminData, needsAttention} from "../../lib/admin";
import AdminNav from "./AdminNav";

export default async function AdminLayout({children}: {children: React.ReactNode}){
  const supabase = await createClient(); const {data: {user}} = await supabase.auth.getUser(); if(!user) redirect("/login");
  const {data: sa} = await supabase.from("super_admins").select("user_id").eq("user_id", user.id).maybeSingle(); if(!sa) redirect("/unauthorized");
  const alerts = needsAttention(await loadAdminData(supabase)).filter(a => a.level !== "low").length;
  return <div className="adminLayout"><AdminNav email={user.email ?? ""} alerts={alerts}/><main className="adminMain">{children}</main></div>;
}
