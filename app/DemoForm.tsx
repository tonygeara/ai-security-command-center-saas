"use client";
// "Request a demo" on the website: sends to the demo-request edge function, which saves it for the admin and
// emails it to the owner.
import {useState} from "react";
import {createClient} from "../lib/supabase/client";

export default function DemoForm(){
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent<HTMLFormElement>){
    e.preventDefault(); setError(""); setState("sending");
    const body = Object.fromEntries(new FormData(e.currentTarget).entries());
    try {
      const {data, error} = await createClient().functions.invoke("demo-request", {body});
      if (error) {
        let msg = "We couldn't send your request. Please try again in a moment.";
        try { const j = await (error as {context?: Response}).context?.json(); if (j?.error) msg = j.error; } catch {}
        throw new Error(msg);
      }
      if (!data?.ok) throw new Error(data?.error || "We couldn't send your request.");
      setState("sent");
    } catch (err) { setError((err as Error).message); setState("idle"); }
  }
  if (state === "sent") return <div className="demoForm demoSent" role="status"><h3>Thank you. Your request is on its way.</h3>
    <p>We&apos;ll contact you shortly to arrange your demo.</p></div>;
  return <form className="demoForm" onSubmit={submit}>
    <div className="demoRow"><label>Full name *<input name="full_name" required minLength={2} maxLength={120} autoComplete="name"/></label>
      <label>Work email *<input name="email" type="email" required maxLength={200} autoComplete="email"/></label></div>
    <div className="demoRow"><label>Company<input name="company" maxLength={160} autoComplete="organization"/></label>
      <label>Phone<input name="phone" type="tel" maxLength={40} autoComplete="tel"/></label></div>
    <div className="demoRow"><label>Country<input name="country" maxLength={80} autoComplete="country-name"/></label>
      <label>Sites / cameras<input name="sites" maxLength={40} placeholder="e.g. 2 sites, 16 cameras"/></label></div>
    <label>What would you like to see?<textarea name="message" rows={4} maxLength={2000}/></label>
    <label className="demoTrap" aria-hidden="true">Website<input name="website" tabIndex={-1} autoComplete="off"/></label>
    {error && <p className="demoError" role="alert">{error}</p>}
    <button className="flightButton" type="submit" disabled={state === "sending"}>{state === "sending" ? "Sending…" : "Request a demo ↗"}</button>
  </form>;
}
