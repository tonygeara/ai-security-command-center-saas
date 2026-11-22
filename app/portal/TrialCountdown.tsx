"use client";
import {useEffect, useState} from "react";
import {uiConfirm} from "../../lib/dialog";

const DAY = 86400000;
const pad = (n: number) => String(n).padStart(2, "0");

// Free trial: time left at the top right, and one day before the end a reminder (once a day) to choose a plan.
export default function TrialCountdown({endsAt}: {endsAt: string}){
  const end = Date.parse(endsAt);
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => { setNow(Date.now()); const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => {
    function remind(){
      const ms = end - Date.now(); if(ms <= 0 || ms > DAY) return;
      const key = "trialReminder:" + end, today = new Date().toDateString();
      try { if(localStorage.getItem(key) === today) return; localStorage.setItem(key, today); } catch { /* private window */ }
      const h = Math.max(1, Math.round(ms / 3600000));
      uiConfirm(`Your free trial ends in about ${h} hour${h > 1 ? "s" : ""} (${new Date(end).toLocaleString()}).\n\n`
        + "When it ends, your PCs switch off their features until a plan is chosen. Choose one now and nothing changes for you.",
        {title: "Free trial ends tomorrow", ok: "Choose a plan", cancel: "Later", danger: false})
        .then(go => { if(go) window.location.href = "/choose-plan"; });
    }
    const first = setTimeout(remind, 1200), again = setInterval(remind, 10 * 60 * 1000);
    return () => { clearTimeout(first); clearInterval(again); };
  }, [end]);
  if(now === null || isNaN(end)) return null;
  const ms = end - now;
  let text = "ENDED · CHOOSE A PLAN", cls = "trialPill over";
  if(ms > 0){
    const s = Math.floor(ms / 1000), d = Math.floor(s / 86400);
    text = `${d ? d + "d " : ""}${pad(Math.floor(s % 86400 / 3600))}:${pad(Math.floor(s % 3600 / 60))}:${pad(s % 60)} left`;
    cls = ms < DAY ? "trialPill soon" : "trialPill";
  }
  return <a className={cls} href="/choose-plan" title="Free trial: choose a plan before it ends">Free trial · <b>{text}</b></a>;
}
