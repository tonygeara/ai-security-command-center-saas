"use client";
import {useMemo, useState} from "react";
import {useRouter} from "next/navigation";

type C = Record<string, any>;
const FILTERS: [string, string][] = [["all", "All"], ["saas", "Online"], ["onprem", "On-prem"], ["expiring", "Expiring ≤30 days"], ["overdue", "Payment overdue"], ["offline", "PC offline"], ["inactive", "Suspended / revoked"]];
const daysLeft = (d?: string | null) => d ? Math.ceil((new Date(d).getTime() - Date.now()) / 86400000) : null;

export default function ClientsTable({rows}: {rows: C[]}){
  const router = useRouter();
  const [q, setQ] = useState(""), [filter, setFilter] = useState("all"), [sort, setSort] = useState<[string, number]>(["name", 1]);
  const today = new Date().toISOString().slice(0, 10);
  const match = (c: C) => {
    const left = daysLeft(c.expires);
    switch(filter){
      case "saas": case "onprem": return c.type === filter;
      case "expiring": return left !== null && left <= 30 && !["revoked", "cancelled"].includes(c.status);
      case "overdue": return c.paymentStatus === "overdue" || (!!c.nextPayment && c.nextPayment < today && c.paymentStatus !== "paid");
      case "offline": return c.devicesTotal > 0 && c.devicesOnline < c.devicesTotal;
      case "inactive": return ["suspended", "revoked", "cancelled"].includes(c.status);
      default: return true;
    }
  };
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return rows.filter(c => match(c) && (!s || [c.name, c.company, c.location, c.contact, c.phone, c.email, c.plan].join(" ").toLowerCase().includes(s)))
      .sort((a, b) => { const [k, dir] = sort; const x = a[k] ?? "", y = b[k] ?? ""; return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * dir; });
  }, [rows, q, filter, sort]);
  const th = (k: string, label: string) => <th onClick={() => setSort(([sk, d]) => [k, sk === k ? -d : 1])} className="sortable">{label}{sort[0] === k ? (sort[1] > 0 ? " ▲" : " ▼") : ""}</th>;
  const exportCsv = () => {
    const cols = ["name", "type", "company", "location", "contact", "phone", "email", "plan", "status", "cameras", "drones", "expires", "price", "paymentStatus", "nextPayment"];
    const csv = [cols.join(","), ...shown.map(c => cols.map(k => `"${String(c[k] ?? "").replace(/"/g, '""')}"`).join(","))].join("\n");
    const a = Object.assign(document.createElement("a"), {href: URL.createObjectURL(new Blob(["﻿" + csv], {type: "text/csv"})), download: "clients.csv"});
    a.click(); URL.revokeObjectURL(a.href);
  };
  return <>
    <div className="clientTools">
      <input className="search" placeholder="Search name, company, city, phone, email…" value={q} onChange={e => setQ(e.target.value)}/>
      <div className="licFilters">{FILTERS.map(([k, t]) => <button key={k} className={filter === k ? "btn small" : "ghost"} onClick={() => setFilter(k)}>{t}</button>)}</div>
      <button className="ghost" onClick={exportCsv}>Export CSV</button>
    </div>
    <div className="card tableWrap"><table className="adminTable clickable"><thead><tr>
      {th("name", "Client")}{th("type", "Type")}{th("plan", "Plan")}<th>Contact</th>{th("cameras", "Limits")}{th("devicesOnline", "PCs")}{th("expires", "Expires")}{th("paymentStatus", "Payment")}
    </tr></thead><tbody>
      {shown.map(c => { const left = daysLeft(c.expires); return <tr key={c.key} onClick={() => router.push("/admin/clients/" + c.key)}>
        <td><b>{c.name}</b><div className="muted">{[c.company, c.location].filter(Boolean).join(" · ")}</div></td>
        <td><span className={"badge " + (c.type === "onprem" ? "badgeOnprem" : "badgeSaas")}>{c.type === "onprem" ? "ON-PREM" : "ONLINE"}</span>
          {["suspended", "revoked", "cancelled"].includes(c.status) && <div className="locked">{c.status}</div>}</td>
        <td>{String(c.plan).toUpperCase()}</td>
        <td>{c.contact}<div className="muted">{c.phone}</div></td>
        <td>{c.cameras ?? "plan"} cam · {c.drones ?? "plan"} drone</td>
        <td>{c.type === "saas" ? <span className={c.devicesTotal && c.devicesOnline < c.devicesTotal ? "locked" : c.devicesOnline ? "ok" : "muted"}>{c.devicesOnline}/{c.devicesTotal}</span> : <span className="muted">offline licence</span>}</td>
        <td className={left !== null && left <= 30 ? "locked" : ""}>{c.expires ?? "—"}{left !== null && <div className="muted">{left <= 0 ? "expired" : `${left} days`}</div>}</td>
        <td>{c.price || "—"}<div className={c.paymentStatus === "overdue" ? "locked" : "muted"}>{c.paymentStatus}</div></td>
      </tr>; })}
      {!shown.length && <tr><td colSpan={8} className="muted">No clients match.</td></tr>}
    </tbody></table></div>
    <p className="muted">{shown.length} of {rows.length} clients</p>
  </>;
}
