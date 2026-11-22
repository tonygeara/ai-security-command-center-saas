import {createClient} from "../../lib/supabase/server";
import TrialCountdown from "./TrialCountdown";

// Every portal page: a company on its free trial sees the time left at the top right (and a reminder on the last day).
export default async function PortalLayout({children}: {children: React.ReactNode}){
  let endsAt: string | null = null;
  try {
    const supabase = await createClient(); const {data: {user}} = await supabase.auth.getUser();
    if(user){
      const {data: m} = await supabase.from("organization_members").select("organization_id").eq("user_id", user.id).limit(1).maybeSingle();
      if(m){
        const {data: o} = await supabase.from("organizations").select("status,trial_ends_at").eq("id", m.organization_id).maybeSingle();
        if(o?.status === "trial" && o.trial_ends_at) endsAt = o.trial_ends_at;
      }
    }
  } catch { /* the page itself handles sign-in */ }
  return <>{children}{endsAt && <TrialCountdown endsAt={endsAt}/>}</>;
}
