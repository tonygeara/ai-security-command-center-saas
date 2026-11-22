import {redirect} from "next/navigation";
import {createClient} from "../../lib/supabase/server";

// "Your dashboard": where a signed-in role link goes (the Windows app's admin link opens it too).
// Super admins → the admin portal; everyone else → their customer portal; not signed in → sign in first.
export default async function Go(){
  const supabase = await createClient();
  const {data: {user}} = await supabase.auth.getUser();
  if(!user) redirect("/login");
  const {data: admin} = await supabase.from("super_admins").select("user_id").eq("user_id", user.id).maybeSingle();
  redirect(admin ? "/admin" : "/portal");
}
