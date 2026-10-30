import {NextResponse} from "next/server";
import {createClient} from "@supabase/supabase-js";

// Website contact form: saves every enquiry to Supabase (contact_requests) and emails it via Resend.
// Vercel environment variables:
//   RESEND_API_KEY      required for email (https://resend.com → API Keys)
//   CONTACT_TO_EMAIL    where enquiries are sent (defaults to the owner's inbox below)
//   CONTACT_FROM_EMAIL  verified sender, e.g. "AI Security <hello@aisecuritycommandcenter.com>".
//                       Until a domain is verified in Resend, the default onboarding sender is used,
//                       which can only deliver to the email address the Resend account was created with.
export const runtime = "nodejs";

const TO = process.env.CONTACT_TO_EMAIL || "tony_geara@hotmail.com";
const FROM = process.env.CONTACT_FROM_EMAIL || "AI Security Website <onboarding@resend.dev>";

const LIMITS: Record<string, number> = {name: 120, email: 200, phone: 40, company: 160, property_type: 80, interest: 80, message: 5000, source_page: 200};

function clean(v: unknown, max: number) {
  return typeof v === "string" ? v.trim().slice(0, max) : "";
}

function esc(s: string) {
  return s.replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]!));
}

export async function POST(req: Request) {
  let body: Record<string, unknown>;
  try { body = await req.json(); } catch { return NextResponse.json({ok: false, error: "Invalid request."}, {status: 400}); }

  // Spam traps: a hidden field real people leave empty, and forms submitted impossibly fast.
  if (clean(body.website, 200)) return NextResponse.json({ok: true});
  const elapsed = Date.now() - Number(body.started_at || 0);
  if (Number.isFinite(elapsed) && elapsed > 0 && elapsed < 2500) return NextResponse.json({ok: true});

  const f = Object.fromEntries(Object.entries(LIMITS).map(([k, max]) => [k, clean(body[k], max)]));
  if (!f.name || !f.message) return NextResponse.json({ok: false, error: "Please add your name and a message."}, {status: 400});
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email)) return NextResponse.json({ok: false, error: "Please enter a valid email address."}, {status: 400});

  let emailSent = false;
  const key = process.env.RESEND_API_KEY;
  if (key) {
    const rows = [["Name", f.name], ["Email", f.email], ["Phone", f.phone], ["Company", f.company],
      ["Property type", f.property_type], ["Interested in", f.interest], ["Page", f.source_page]].filter(([, v]) => v);
    const html = `<h2>New enquiry from your website</h2><table cellpadding="6">${rows.map(([k, v]) => `<tr><td><b>${k}</b></td><td>${esc(v)}</td></tr>`).join("")}</table>`
      + `<p><b>Message</b></p><p style="white-space:pre-wrap">${esc(f.message)}</p><p style="color:#888">Reply to this email to answer ${esc(f.name)} directly.</p>`;
    const text = rows.map(([k, v]) => `${k}: ${v}`).join("\n") + `\n\nMessage:\n${f.message}`;
    try {
      const r = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: {Authorization: `Bearer ${key}`, "Content-Type": "application/json"},
        body: JSON.stringify({from: FROM, to: [TO], reply_to: f.email, subject: `New website enquiry: ${f.name}${f.company ? ` (${f.company})` : ""}`, html, text}),
      });
      emailSent = r.ok;
      if (!r.ok) console.error("Resend error", r.status, await r.text());
    } catch (e) {
      console.error("Resend request failed", e);
    }
  } else {
    console.error("RESEND_API_KEY is not set: contact request saved but not emailed.");
  }

  let saved = false;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL, anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (url && anon) {
    const {error} = await createClient(url, anon, {auth: {persistSession: false}})
      .from("contact_requests").insert({...Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v || null])), email_sent: emailSent});
    saved = !error;
    if (error) console.error("contact_requests insert failed", error.message);
  }

  if (!emailSent && !saved) {
    return NextResponse.json({ok: false, error: "Sorry, your message couldn't be sent. Please try again in a few minutes."}, {status: 502});
  }
  return NextResponse.json({ok: true});
}
