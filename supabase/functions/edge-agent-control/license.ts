// Licence signing shared by issue-onprem-license and edge-agent-control (keep both copies identical;
// no imports, so it can be tested locally with Node and checked by the Windows app's Python verifier).
// Must match PUBLIC_KEY_B64 in edge/app/licensing.py.
const APP_PUBLIC_KEY_B64 = "FdDMvjooLB3N8bOWc6mjnX1AjPcZHcQ8B5da/E01Lb4=";
export const FEATURES = ["camera_ai", "face_ai", "lpr", "drone_live", "drone_ai", "drone_tracking", "drone_control",
  "handoff", "smart_patrol", "verified_alarms", "incident_replay", "phone_access"];
export const MACHINE_ID = /^[0-9A-F]{4}(-[0-9A-F]{4}){4}$/;

// Same bytes as Python json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).
export function canonical(v: unknown): string {
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  if (v && typeof v === "object") {
    return "{" + Object.keys(v as Record<string, unknown>).sort().map((k) => JSON.stringify(k) + ":" + canonical((v as Record<string, unknown>)[k])).join(",") + "}";
  }
  return JSON.stringify(v);
}

const b64 = (bytes: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(bytes)));
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

export async function signLicense(payload: Record<string, unknown>, pem: string) {
  const der = unb64(pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, ""));
  const key = await crypto.subtle.importKey("pkcs8", der, {name: "Ed25519"}, false, ["sign"]);
  const data = new TextEncoder().encode(canonical(payload));
  const signature = b64(await crypto.subtle.sign({name: "Ed25519"}, key, data));
  const pub = await crypto.subtle.importKey("raw", unb64(APP_PUBLIC_KEY_B64), {name: "Ed25519"}, false, ["verify"]);
  if (!(await crypto.subtle.verify({name: "Ed25519"}, pub, unb64(signature), data))) {
    throw new Error("Signing key does not match the key built into the Windows app");
  }
  return {license: payload, signature};
}

