"use client";
import Link from "next/link";
import {usePathname} from "next/navigation";
import SignOut from "../SignOut";

const ITEMS: [string, string, string][] = [["/admin", "◉", "Overview"], ["/admin/clients", "▤", "Clients"],
  ["/admin/devices", "▣", "Devices"], ["/admin/users", "☺", "Users"], ["/admin/demo-requests", "✉", "Demo requests"]];

export default function AdminNav({email, alerts}: {email: string; alerts: number}){
  const path = usePathname();
  const active = (href: string) => href === "/admin" ? path === "/admin" : path.startsWith(href) || (href === "/admin/clients" && path.startsWith("/admin/licenses"));
  return <nav className="adminNav">
    <div className="brand adminBrand">AI SECURITY<span>ADMIN</span></div>
    {ITEMS.map(([href, icon, label]) => <Link key={href} href={href} className={active(href) ? "active" : ""}>
      <i>{icon}</i>{label}{href === "/admin" && alerts > 0 && <b className="navCount">{alerts}</b>}</Link>)}
    <div className="adminNavFoot"><a href="https://downloads.aisecuritycommandcenter.com/" target="_blank">Downloads ↗</a>
      <span className="muted" title={email}>{email}</span><Link className="roleLink" href="/admin" title="The admin portal">Super admin</Link><SignOut/></div>
  </nav>;
}
