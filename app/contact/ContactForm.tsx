"use client";
import {useRef, useState} from "react";

const PROPERTY_TYPES = ["Farm or rural property", "Construction site or yard", "Estate or large home", "Commercial or industrial site", "Government or public site", "Other"];
const INTERESTS = ["Drone patrols", "Drones + cameras", "Cameras only", "Not sure yet"];

export default function ContactForm() {
  const startedAt = useRef(Date.now());
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setState("sending"); setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget).entries());
    try {
      const r = await fetch("/api/contact", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...data, started_at: startedAt.current, source_page: window.location.pathname}),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.error || "Something went wrong. Please try again.");
      setState("sent");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
      setState("error");
    }
  }

  if (state === "sent") {
    return (
      <div className="cDone" role="status">
        <div className="cDoneIcon">✓</div>
        <h2>Thanks — we've got your message.</h2>
        <p>We'll reply to you by email as soon as possible.</p>
        <a className="ghost" href="/drones">Explore drone patrols while you wait</a>
      </div>
    );
  }

  return (
    <form className="cForm" onSubmit={submit}>
      <div className="cGrid">
        <label>Full name *<input name="name" autoComplete="name" required maxLength={120}/></label>
        <label>Email *<input name="email" type="email" autoComplete="email" required maxLength={200}/></label>
        <label>Phone<input name="phone" type="tel" autoComplete="tel" maxLength={40}/></label>
        <label>Company<input name="company" autoComplete="organization" maxLength={160}/></label>
        <label>Property type
          <select name="property_type" defaultValue="">
            <option value="" disabled>Choose one</option>
            {PROPERTY_TYPES.map(p => <option key={p}>{p}</option>)}
          </select>
        </label>
        <label>Interested in
          <select name="interest" defaultValue="Drone patrols">
            {INTERESTS.map(p => <option key={p}>{p}</option>)}
          </select>
        </label>
      </div>
      <label>How can we help? *
        <textarea name="message" rows={5} required maxLength={5000} placeholder="Tell us about your property, its size and what you want to protect."/>
      </label>
      <label className="cTrap" aria-hidden="true">Website<input name="website" tabIndex={-1} autoComplete="off"/></label>
      <button className="btn" disabled={state === "sending"}>{state === "sending" ? "Sending…" : "Send message"}</button>
      {state === "error" && <p className="cError" role="alert">{error}</p>}
      <p className="cNote">We only use your details to reply to your enquiry.</p>
    </form>
  );
}
