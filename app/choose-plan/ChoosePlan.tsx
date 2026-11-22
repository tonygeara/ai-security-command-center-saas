"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";

const WHAT: Record<string, string> = {
  home: "4 cameras with AI, phone access, incident replay",
  pro: "10 cameras, faces and plates, 1 drone flown from the PC",
  business: "30 cameras, 3 drones with AI, follow-the-person, Smart patrol, verified alarms, 1 DJI Dock",
};

export default function ChoosePlan({plans}: {plans: {code: string; name: string; monthly: number}[]}){
  const [busy, setBusy] = useState(""), [message, setMessage] = useState("");
  async function choose(code: string){
    setBusy(code); setMessage("");
    const {data, error} = await createClient().functions.invoke("create-checkout-session", {body: {plan_code: code}});
    if(error || !data?.url){ setMessage(error?.message || data?.error || "Payment page unavailable. Try again or contact your provider."); setBusy(""); return; }
    const url = new URL(data.url);
    if(url.protocol !== "https:" || url.hostname !== "checkout.stripe.com"){ setMessage("Invalid payment page."); setBusy(""); return; }
    location.assign(url.href);
  }
  return <>
    <section className="grid">{plans.map(p => <article key={p.code} className="card">
      <h2>{p.name}</h2><strong>CA${(p.monthly / 100).toFixed(0)}</strong><span className="muted"> / month</span>
      <p className="muted">{WHAT[p.code] || ""}</p>
      <button className="btn" disabled={!!busy} onClick={() => choose(p.code)}>{busy === p.code ? "Opening payment…" : `Choose ${p.name}`}</button>
    </article>)}
      <article className="card"><h2>Enterprise</h2><strong>Quote</strong><p className="muted">Unlimited cameras, drones and docks, drone tracking.</p>
        <a className="ghost" href="mailto:?subject=Enterprise%20plan">Contact your provider</a></article></section>
    <p role="status" className="locked">{message}</p>
  </>;
}
