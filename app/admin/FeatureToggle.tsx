"use client";
import {useState} from "react";
import {createClient} from "../../lib/supabase/client";
export default function FeatureToggle({orgId,feature,initial}:{orgId:string,feature:string,initial:boolean}){const [on,setOn]=useState(initial);const [busy,setBusy]=useState(false);async function toggle(){setBusy(true);const next=!on;const {error}=await createClient().rpc("set_feature_override",{target_org:orgId,target_feature:feature,target_enabled:next,target_limit:null});if(!error)setOn(next);else alert(error.message);setBusy(false)}return <button disabled={busy} onClick={toggle}>{busy?"Saving...":on?"ON":"OFF"}</button>}
