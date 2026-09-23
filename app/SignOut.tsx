"use client";
import {useState} from "react";
import {createClient} from "../lib/supabase/client";
export default function SignOut(){
 const [busy,setBusy]=useState(false),[error,setError]=useState("");
 async function leave(){setBusy(true);setError("");try{const {error}=await createClient().auth.signOut({scope:"local"});if(error)throw error;location.replace("/login");}catch(e){setError(e instanceof Error?e.message:"Sign out failed");setBusy(false);}}
 return <div><button className="ghost" disabled={busy} onClick={leave}>{busy?"Signing out…":"Sign out"}</button>{error&&<p role="alert">{error}</p>}</div>;
}

