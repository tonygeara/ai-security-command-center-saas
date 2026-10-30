import {createClient} from "../../../lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function Leads(){
  const supabase = await createClient();
  const {data, error} = await supabase.from("contact_requests").select("*").order("created_at", {ascending: false}).limit(200);
  const rows = data ?? [];
  return <>
    <div className="portalTop"><div><p className="eyebrow">SUPER ADMIN</p><h1>Enquiries</h1>
      <p className="muted">Messages sent from the website contact form. Each one is also emailed to you. Reply from your inbox, or tap the email address below.</p></div></div>
    {error && <div className="card"><p className="locked">Could not load enquiries: {error.message}</p></div>}
    <div className="card tableWrap"><table className="adminTable"><thead><tr><th>Received</th><th>From</th><th>Property / interest</th><th>Message</th><th>Email sent</th></tr></thead><tbody>
      {rows.map(r => <tr key={r.id}>
        <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
        <td><b>{r.name}</b>{r.company && <div className="muted">{r.company}</div>}
          <div><a href={`mailto:${r.email}?subject=${encodeURIComponent("Re: your AI Security Command Center enquiry")}`}>{r.email}</a></div>
          {r.phone && <div><a href={`tel:${r.phone}`}>{r.phone}</a></div>}</td>
        <td>{r.property_type || "—"}<div className="muted">{r.interest || ""}</div></td>
        <td style={{whiteSpace: "pre-wrap", maxWidth: 420}}>{r.message}</td>
        <td>{r.email_sent ? <span className="ok">Yes</span> : <span className="locked">No</span>}</td>
      </tr>)}
      {!rows.length && !error && <tr><td colSpan={5} className="muted">No enquiries yet.</td></tr>}
    </tbody></table></div>
  </>;
}
