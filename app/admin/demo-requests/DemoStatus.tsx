"use client";
import {useState} from "react";
import {createClient} from "../../../lib/supabase/client";

export default function DemoStatus({id, status}: {id: string; status: string}){
  const [value, setValue] = useState(status); const [err, setErr] = useState("");
  async function change(next: string){
    const before = value; setValue(next); setErr("");
    const {error} = await createClient().from("demo_requests").update({status: next}).eq("id", id);
    if (error) { setValue(before); setErr(error.message); }
  }
  return <><select value={value} onChange={e => change(e.target.value)} aria-label="Status">
    <option value="new">New</option><option value="contacted">Contacted</option><option value="closed">Closed</option></select>
    {err && <div className="locked">{err}</div>}</>;
}
