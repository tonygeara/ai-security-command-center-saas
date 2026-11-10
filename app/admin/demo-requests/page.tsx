import {createClient} from "../../../lib/supabase/server";
import DemoStatus from "./DemoStatus";

type Req = {id: string; created_at: string; full_name: string; email: string; company: string | null; phone: string | null;
  country: string | null; sites: string | null; message: string | null; status: string; emailed: boolean};

export default async function DemoRequests(){
  const supabase = await createClient();
  const {data, error} = await supabase.from("demo_requests").select("id,created_at,full_name,email,company,phone,country,sites,message,status,emailed")
    .order("created_at", {ascending: false}).limit(500);
  const rows = (data ?? []) as Req[];
  const fresh = rows.filter(r => r.status === "new").length;
  return <>
    <div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Demo requests</h1>
      <p className="muted">Sent from the website&apos;s &quot;Request a demo&quot; form. {fresh} new. Each one is also emailed to you when email is set up.</p></div></div>
    {error && <p className="locked">{error.message}</p>}
    <div className="card tableWrap"><table className="adminTable"><thead><tr><th>Received</th><th>From</th><th>Company</th><th>Message</th><th>Status</th></tr></thead><tbody>
      {rows.map(r => <tr key={r.id}>
        <td className="muted">{new Date(r.created_at).toLocaleString()}{!r.emailed && <div title="The email notification was not sent">not emailed</div>}</td>
        <td><b>{r.full_name}</b><div><a href={"mailto:" + r.email}>{r.email}</a></div>{r.phone && <div className="muted">{r.phone}</div>}</td>
        <td>{r.company || "—"}<div className="muted">{[r.country, r.sites].filter(Boolean).join(" · ")}</div></td>
        <td style={{whiteSpace: "pre-wrap", maxWidth: 360}}>{r.message || <span className="muted">—</span>}</td>
        <td><DemoStatus id={r.id} status={r.status}/></td></tr>)}
      {!rows.length && <tr><td colSpan={5} className="muted">No demo requests yet.</td></tr>}
    </tbody></table></div>
  </>;
}
