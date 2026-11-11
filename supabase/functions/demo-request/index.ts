// The website's "Request a demo" form posts here (no sign-in). It saves the request (Admin → Demo requests)
// and emails it to the owner.
//
// POST JSON {full_name, email, company?, phone?, country?, sites?, message?, website?}
//   website is a hidden field people never fill: anything in it means a bot, and the request is dropped
//   while still answering "ok" so the bot learns nothing.
//
// Secrets (Supabase → Edge Functions → Secrets):
//   RESEND_API_KEY      key from resend.com; without it requests are only saved, not emailed
//   DEMO_REQUEST_EMAIL  where the requests go
//   DEMO_FROM_EMAIL     sender, default "AI Security Command Center <onboarding@resend.dev>" (Resend's test
//                       sender only delivers to the Resend account's own address; verify a domain to change it)
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import {createClient} from "npm:@supabase/supabase-js@2";

const origins = new Set(["https://www.aisecuritycommandcenter.com", "https://aisecuritycommandcenter.com",
  "https://ai-security-command-center-saas.vercel.app", "http://localhost:3000"]);
const text = (v: unknown, max: number) => (typeof v === "string" ? v.replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, " ").trim().slice(0, max) : "");
const oneLine = (v: unknown, max: number) => text(v, max).replace(/\s+/g, " ");
const esc = (s: string) => s.replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]!));

function cors(req: Request) {
  const o = req.headers.get("origin") || "";
  return {"Access-Control-Allow-Origin": origins.has(o) || /^https:\/\/ai-security-command-center-saas-[a-z0-9-]+-tony-geara-8688\.vercel\.app$/.test(o) ? o : "https://www.aisecuritycommandcenter.com",
    "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "content-type, authorization, apikey, x-client-info",
    "Vary": "Origin"};
}

async function email(r: Record<string, string>, id: string) {
  const key = (Deno.env.get("RESEND_API_KEY") || "").trim(), to = (Deno.env.get("DEMO_REQUEST_EMAIL") || "").trim();
  if (!key || !to) {
    console.warn("demo request not emailed: secret missing:", [!key && "RESEND_API_KEY", !to && "DEMO_REQUEST_EMAIL"].filter(Boolean).join(", "));
    return false;
  }
  const rows: [string, string][] = [["Name", r.full_name], ["Email", r.email], ["Company", r.company], ["Phone", r.phone],
    ["Country", r.country], ["Sites / cameras", r.sites]];
  const html = `<h2>New demo request</h2><table cellpadding="6">${rows.filter(([, v]) => v).map(([k, v]) =>
    `<tr><td><b>${k}</b></td><td>${esc(v)}</td></tr>`).join("")}</table>` +
    (r.message ? `<p><b>Message</b></p><p style="white-space:pre-wrap">${esc(r.message)}</p>` : "") +
    `<p style="color:#888">Reply to this email to answer ${esc(r.full_name)}. All requests: Admin → Demo requests. Ref ${id}</p>`;
  const res = await fetch("https://api.resend.com/emails", {method: "POST",
    headers: {"Authorization": `Bearer ${key}`, "Content-Type": "application/json"},
    body: JSON.stringify({from: Deno.env.get("DEMO_FROM_EMAIL") || "AI Security Command Center <onboarding@resend.dev>",
      to: [to], reply_to: r.email, subject: `Demo request: ${r.full_name}${r.company ? " (" + r.company + ")" : ""}`, html})});
  if (!res.ok) console.error("demo request not emailed: Resend said", res.status, (await res.text()).slice(0, 300));
  else console.log("demo request emailed", id);
  return res.ok;
}

Deno.serve(async req => {
  const h = {...cors(req), "Content-Type": "application/json"};
  const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status, headers: h});
  if (req.method === "OPTIONS") return new Response(null, {headers: cors(req)});
  if (req.method !== "POST") return reply({error: "POST only"}, 405);
  let b: Record<string, unknown>;
  try { b = await req.json(); } catch { return reply({error: "Send the form as JSON."}, 400); }
  if (text(b.website, 200)) return reply({ok: true});  // honeypot
  const r = {full_name: oneLine(b.full_name, 120), email: oneLine(b.email, 200).toLowerCase(), company: oneLine(b.company, 160),
    phone: oneLine(b.phone, 40), country: oneLine(b.country, 80), sites: oneLine(b.sites, 40), message: text(b.message, 2000)};
  if (r.full_name.length < 2) return reply({error: "Please enter your name."}, 400);
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(r.email) || r.email.length < 5) return reply({error: "Please enter a valid email address."}, 400);
  const ip = oneLine((req.headers.get("x-forwarded-for") || "").split(",")[0], 64);
  const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {auth: {persistSession: false}});
  const {data: id, error} = await admin.rpc("submit_demo_request", {...r, source_ip: ip});
  if (error) {
    if (error.code === "P0001") return reply({error: error.message}, 429);
    console.error("submit", error.message);
    return reply({error: "Something went wrong. Please try again in a moment."}, 500);
  }
  try { if (await email(r, id as string)) await admin.from("demo_requests").update({emailed: true}).eq("id", id); }
  catch (e) { console.error("email", String(e)); }
  return reply({ok: true});
});
