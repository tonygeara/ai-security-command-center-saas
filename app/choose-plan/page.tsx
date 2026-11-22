import {redirect} from "next/navigation";
import {createClient} from "../../lib/supabase/server";
import SignOut from "../SignOut";
import ChoosePlan from "./ChoosePlan";

// Shown instead of the portal once a client's 14-day trial has ended: nothing else opens (and their PCs stop and refuse
// sign-in) until the company's admin chooses a plan and pays (Stripe). The Stripe webhook then makes the account active.
export default async function ChoosePlanPage({searchParams}: {searchParams: Promise<{checkout?: string}>}){
  const supabase = await createClient();
  const {data: {user}} = await supabase.auth.getUser();
  if(!user) redirect("/login");
  const {checkout} = await searchParams;
  const {data: m} = await supabase.from("organization_members").select("organization_id,role").eq("user_id", user.id).limit(1).maybeSingle();
  if(!m) redirect("/onboarding");
  const {data: ended} = await supabase.rpc("org_trial_expired", {target_org: m.organization_id});
  if(!ended) redirect("/portal");
  const [{data: org}, {data: plans}] = await Promise.all([
    supabase.from("organizations").select("name,trial_ends_at").eq("id", m.organization_id).maybeSingle(),
    supabase.from("billing_plans").select("plan_code,display_name,monthly_cad,sort_order").eq("active", true).order("sort_order")]);
  const admin = ["owner", "admin"].includes(m.role);
  const endedOn = org?.trial_ends_at ? new Date(org.trial_ends_at).toLocaleDateString("en-GB", {dateStyle: "long"}) : "";
  return <main className="shell">
    {checkout === "success" && <meta httpEquiv="refresh" content="5"/>}
    <div className="brand">AI SECURITY COMMAND CENTER</div>
    <div className="portalTop"><div><p className="eyebrow">CHOOSE A PLAN</p><h1>{org?.name || "Your company"}</h1>
      <p className="muted">The free 14-day trial ended{endedOn ? ` on ${endedOn}` : ""}. Cameras&apos; AI, drones and sign-in on your PCs are
        paused until a plan is chosen. Your cameras, settings and recordings are kept.</p></div>
      <div className="portalActions"><SignOut/></div></div>
    {checkout === "success"
      ? <article className="card"><h2>Payment received</h2><p className="muted">Activating your plan: this page moves on to your portal by itself in a few seconds.</p></article>
      : admin ? <ChoosePlan plans={(plans ?? []).map(p => ({code: p.plan_code, name: p.display_name, monthly: p.monthly_cad}))}/>
      : <article className="card"><p>Only your company&apos;s admin can choose the plan. Ask them to sign in here.</p></article>}
    {checkout === "cancelled" && <p className="locked">The payment was cancelled. Choose a plan to continue.</p>}
  </main>;
}
