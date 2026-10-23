// Shared data for the super-admin pages: one "client" list that merges online (SaaS) accounts with
// on-prem licence records, plus the "needs attention" checks shown on the overview.
import type {SupabaseClient} from "@supabase/supabase-js";

// Bump when a new Windows release ships, so PCs on older versions are flagged.
export const LATEST_APP_VERSION = "11.1.0";
const OFFLINE_ALERT_MS = 24 * 3600 * 1000;

export type Row = Record<string, any>;

export async function loadAdminData(supabase: SupabaseClient) {
  const [users, orgs, subs, devices, sources, licenses] = await Promise.all([
    supabase.rpc("super_admin_user_directory"),
    supabase.from("organizations").select("id,name,slug,plan_code,status,created_at").order("name"),
    supabase.from("subscriptions").select("organization_id,plan_code,status,current_period_end,provider_subscription_id,cancel_at_period_end"),
    supabase.from("edge_devices").select("id,organization_id,device_name,status,last_seen_at,app_version,platform,last_ip,created_at"),
    supabase.from("video_sources").select("id,organization_id,edge_device_id,name,source_type,enabled"),
    supabase.from("client_licenses").select("*").order("created_at", {ascending: false}),
  ]);
  return {users: (users.data ?? []) as Row[], orgs: (orgs.data ?? []) as Row[], subs: (subs.data ?? []) as Row[],
    devices: (devices.data ?? []) as Row[], sources: (sources.data ?? []) as Row[], licenses: (licenses.data ?? []) as Row[]};
}

export type AdminData = Awaited<ReturnType<typeof loadAdminData>>;

export const isOnline = (d: Row, now = Date.now()) => d.status === "online" && !!d.last_seen_at && now - new Date(d.last_seen_at).getTime() < 90000;
export const daysLeft = (date?: string | null) => date ? Math.ceil((new Date(date).getTime() - Date.now()) / 86400000) : null;
export function versionBehind(v?: string | null) {
  if (!v) return false;
  const a = String(v).replace(/^v/i, "").split(".").map(Number), b = LATEST_APP_VERSION.split(".").map(Number);
  for (let i = 0; i < 3; i++) { if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) < (b[i] || 0); }
  return false;
}

export type Client = {
  key: string; type: "onprem" | "saas"; name: string; company: string; location: string; contact: string; phone: string; email: string;
  plan: string; status: string; cameras: number | null; drones: number | null; devicesOnline: number; devicesTotal: number;
  expires: string | null; price: string; paymentStatus: string; nextPayment: string | null; orgId: string | null; license: Row | null; org: Row | null;
};

export function buildClients(d: AdminData): Client[] {
  const out: Client[] = [];
  const byOrg = new Map<string, Row>();
  for (const l of d.licenses) if (l.organization_id && !byOrg.has(l.organization_id)) byOrg.set(l.organization_id, l);
  const money = (l?: Row | null) => l?.price != null ? `${l.price} ${l.currency}${l.billing_period ? " / " + l.billing_period : ""}` : "";
  for (const o of d.orgs) {
    const l = byOrg.get(o.id) ?? null, sub = d.subs.find(s => s.organization_id === o.id), ds = d.devices.filter(x => x.organization_id === o.id);
    out.push({key: "org-" + o.id, type: "saas", name: l?.client_name || o.name, company: l?.company || "", location: l?.location || "",
      contact: l?.contact_name || "", phone: l?.phone || "", email: l?.email || "", plan: String(sub?.plan_code ?? o.plan_code ?? ""),
      status: String(sub?.status ?? o.status ?? ""), cameras: l?.cameras ?? null, drones: l?.drones ?? null,
      devicesOnline: ds.filter(x => isOnline(x)).length, devicesTotal: ds.length,
      expires: l?.expires_on ?? (sub?.current_period_end ? String(sub.current_period_end).slice(0, 10) : null),
      price: money(l), paymentStatus: l?.payment_status || "", nextPayment: l?.next_payment_date ?? null, orgId: o.id, license: l, org: o});
  }
  for (const l of d.licenses.filter(x => x.edition === "onprem")) {
    out.push({key: "lic-" + l.id, type: "onprem", name: l.client_name, company: l.company || "", location: l.location || "",
      contact: l.contact_name || "", phone: l.phone || "", email: l.email || "", plan: l.plan || "on-prem", status: l.status,
      cameras: l.cameras, drones: l.drones, devicesOnline: 0, devicesTotal: 0, expires: l.expires_on, price: money(l),
      paymentStatus: l.payment_status || "", nextPayment: l.next_payment_date ?? null, orgId: null, license: l, org: null});
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

export type Alert = {level: "high" | "medium" | "low"; kind: string; title: string; detail: string; href: string};

export function needsAttention(d: AdminData, clients = buildClients(d)): Alert[] {
  const alerts: Alert[] = [], today = new Date().toISOString().slice(0, 10), now = Date.now();
  const clientFor = (orgId?: string | null) => clients.find(c => c.orgId === orgId);
  for (const c of clients) {
    const href = "/admin/clients/" + c.key, left = daysLeft(c.expires);
    if (c.status === "revoked" || c.status === "cancelled") continue;
    if (c.license && left !== null && left <= 30) alerts.push({level: left <= 0 ? "high" : left <= 7 ? "high" : "medium", kind: "expiry",
      title: left <= 0 ? `${c.name}: licence expired` : `${c.name}: licence expires in ${left} day${left === 1 ? "" : "s"}`,
      detail: `${c.type === "onprem" ? "On-prem" : "Online"} · ${c.expires}`, href});
    if (c.paymentStatus === "overdue" || (c.nextPayment && c.nextPayment < today && c.paymentStatus !== "paid"))
      alerts.push({level: "high", kind: "payment", title: `${c.name}: payment overdue`, detail: `${c.price || "amount not set"}${c.nextPayment ? " · due " + c.nextPayment : ""}`, href});
    if (c.type === "saas" && c.plan === "trial" && left !== null && left <= 7 && left >= 0)
      alerts.push({level: "medium", kind: "trial", title: `${c.name}: trial ends in ${left} day${left === 1 ? "" : "s"}`, detail: "Convert to a paid plan or follow up", href});
    if (c.type === "saas" && c.status === "suspended")
      alerts.push({level: "low", kind: "suspended", title: `${c.name}: account suspended`, detail: "Features are off until reactivated", href});
  }
  for (const dv of d.devices) {
    if (dv.status === "disabled") continue;
    const c = clientFor(dv.organization_id), href = c ? "/admin/clients/" + c.key : "/admin/devices";
    const seen = dv.last_seen_at ? new Date(dv.last_seen_at).getTime() : 0;
    if (!isOnline(dv, now) && now - seen > OFFLINE_ALERT_MS)
      alerts.push({level: "medium", kind: "offline", title: `${c?.name ?? "Unknown client"}: PC "${dv.device_name || "unnamed"}" offline`,
        detail: seen ? `Last seen ${new Date(seen).toLocaleString()}` : "Never connected", href});
    if (versionBehind(dv.app_version))
      alerts.push({level: "low", kind: "version", title: `${c?.name ?? "Unknown client"}: PC "${dv.device_name || "unnamed"}" on old version ${dv.app_version}`,
        detail: `Latest is ${LATEST_APP_VERSION}`, href});
  }
  const rank = {high: 0, medium: 1, low: 2};
  return alerts.sort((a, b) => rank[a.level] - rank[b.level]);
}
