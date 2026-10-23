"use client";
export default function DownloadLicense({license: l}: {license: Record<string, any>}){
  if(!l?.license_document) return null;
  function save(){
    const name = String(l.client_name || "client").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "client";
    const url = URL.createObjectURL(new Blob([JSON.stringify(l.license_document, null, 2)], {type: "application/json"}));
    const a = Object.assign(document.createElement("a"), {href: url, download: `license-${name}-${String(l.machine_id).slice(0, 9)}.lic`});
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }
  return <button className="ghost" onClick={save}>Download .lic</button>;
}
