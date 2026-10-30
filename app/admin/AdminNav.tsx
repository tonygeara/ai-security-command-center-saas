"use client";
import Link from "next/link";
import {usePathname} from "next/navigation";
import SignOut from "../SignOut";

const ITEMS: [string, string, string][] = [["/admin", "◉", "Overview"], ["/admin/clients", "▤", "Clients"], ["/admin/licenses", "⚿", "Licences"],
  ["/admin/devices", "▣", "Devices"], ["/admin/users", "☺", "Users"], ["/admin/leads", "✉", "Enquiries"]];

export default function AdminNav({email, alerts}: {email: string; alerts: number}){
  const path = usePathname();
  const active = (href: string) => href === "/admin" ? path === "/admin" : path.startsWith(href);
  return <nav className="adminNav">
    <div className="brand adminBrand">AI SECURITY<span>ADMIN</span></div>
    {ITEMS.map(([href, icon, label]) => <Link key={href} href={href} className={active(href) ? "active" : ""}>
      <i>{icon}</i>{label}{href === "/admin" && alerts > 0 && <b className="navCount">{alerts}</b>}</Link>)}
    <div className="adminNavFoot"><a href="https://downloads.aisecuritycommandcenter.com/" target="_blank">Downloads ↗</a>
      <span className="muted" title={email}>{email}</span><SignOut/></div>
  </nav>;
}
