// Issues a signed on-prem licence (.lic) for "AI Command Centre Lebanon" and records it in
// public.client_licenses. Super admins only. The signing key (Ed25519, PKCS#8 PEM) is the
// LICENSE_SIGNING_KEY secret; every licence is verified against the public key embedded in the
// Windows app before it is returned, so a wrong key can never produce an unusable file.
import {createClient} from "https://esm.sh/@supabase/supabase-js@2";
import {FEATURES, MACHINE_ID, signLicense} from "./license.ts";

const origins = new Set(["https://www.aisecuritycommandcenter.com", "https://aisecuritycommandcenter.com", "https://ai-security-command-center-saas.vercel.app", "http://localhost:3000"]);
const text = (v: unknown, max = 200) => (typeof v === "string" ? v.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, max) : "");

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("Origin") || "";
  const headers = {"Content-Type": "application/json", "Access-Control-Allow-Origin": origins.has(origin) ? origin : "https://www.aisecuritycommandcenter.com",
    "Access-Control-Allow-Headers": "authorization,x-client-info,apikey,content-type", "Access-Control-Allow-Methods": "POST,OPTIONS", "Vary": "Origin"};
  const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status, headers});
  if (origin && !origins.has(origin)) return reply({error: "Origin not allowed"}, 403);
  if (req.method === "OPTIONS") return new Response(null, {status: 204, headers});
  if (req.method !== "POST") return reply({error: "Method not allowed"}, 405);
  try {
    const auth = req.headers.get("Authorization");
    if (!auth) return reply({error: "Sign in required"}, 401);
    const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!, {global: {headers: {Authorization: auth}}});
    const {data: {user}, error: authError} = await sb.auth.getUser();
    if (authError || !user) return reply({error: "Sign in required"}, 401);
    const {data: admin} = await sb.from("super_admins").select("user_id").eq("user_id", user.id).maybeSingle();
    if (!admin) return reply({error: "Super admin required"}, 403);

    const pem = Deno.env.get("LICENSE_SIGNING_KEY");
    if (!pem) return reply({error: "Licence signing is not set up yet: add the LICENSE_SIGNING_KEY secret in Supabase."}, 503);

    const body = await req.json();
    const client = text(body.client_name, 120);
    const machine = text(body.machine_id, 30).toUpperCase();
    const expires = text(body.expires_on, 10);
    const cameras = Math.trunc(Number(body.cameras ?? 1));
    const drones = Math.trunc(Number(body.drones ?? 1));
    const features = Array.isArray(body.features) ? [...new Set(body.features.filter((f: unknown) => typeof f === "string" && FEATURES.includes(f as string)))].sort() : [];
    if (!client) return reply({error: "Client name is required"}, 400);
    if (!MACHINE_ID.test(machine)) return reply({error: "Machine ID must look like XXXX-XXXX-XXXX-XXXX-XXXX (from the client's License page)"}, 400);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(expires) || isNaN(Date.parse(expires))) return reply({error: "Choose an expiry date"}, 400);
    const today = new Date().toISOString().slice(0, 10);
    if (expires <= today) return reply({error: "The expiry date must be in the future"}, 400);
    if (!(cameras >= 1 && cameras <= 500)) return reply({error: "Cameras must be between 1 and 500"}, 400);
    if (!(drones >= 0 && drones <= 50)) return reply({error: "Drones must be between 0 and 50"}, 400);
    if (!features.length) return reply({error: "Choose at least one feature"}, 400);

    const payload = {
      product: "AI Command Centre Lebanon",
      license_id: crypto.randomUUID(),
      customer: client,
      machine_id: machine,
      issued: today,
      expires,
      plan: text(body.plan, 40) || "on-prem",
      features,
      feature_set: 2,  // the newer features are listed: the PC only allows the ones ticked
      limits: {cameras, drones},
    };
    const document = await signLicense(payload, pem);

    const record = {
      edition: "onprem", client_name: client, company: text(body.company), location: text(body.location), address: text(body.address, 300),
      contact_name: text(body.contact_name), phone: text(body.phone, 60), email: text(body.email, 120), notes: text(body.notes, 2000),
      price: body.price === "" || body.price == null ? null : Number(body.price), currency: text(body.currency, 3) || "USD",
      billing_period: ["one-time", "monthly", "yearly"].includes(body.billing_period) ? body.billing_period : null,
      next_payment_date: /^\d{4}-\d{2}-\d{2}$/.test(body.next_payment_date ?? "") ? body.next_payment_date : null,
      payment_status: ["paid", "pending", "overdue"].includes(body.payment_status) ? body.payment_status : null,
      machine_id: machine, plan: payload.plan, cameras, drones, features, issued_on: today, expires_on: expires,
      status: "active", license_id: payload.license_id, license_document: document,
    };
    const recordId = typeof body.record_id === "string" && /^[0-9a-f-]{36}$/i.test(body.record_id) ? body.record_id : null;
    const query = recordId ? sb.from("client_licenses").update(record).eq("id", recordId).select().single()
                           : sb.from("client_licenses").insert(record).select().single();
    const {data: saved, error} = await query;
    if (error) return reply({error: "Licence signed but not saved: " + error.message}, 500);
    return reply({ok: true, record: saved, document});
  } catch (e) {
    return reply({error: e instanceof Error ? e.message : "Could not issue the licence"}, 500);
  }
});
