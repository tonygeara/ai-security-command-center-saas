import {ImageResponse} from "next/og";

export const alt = "AI Security Command Center: autonomous security drones that patrol for you";
export const size = {width: 1200, height: 630};
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div style={{width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center", padding: 80,
        background: "linear-gradient(135deg,#050b12 0%,#07253a 60%,#0a3d5c 100%)", color: "#eaf6ff", fontFamily: "sans-serif"}}>
        <div style={{fontSize: 26, letterSpacing: 6, color: "#52d9ff", fontWeight: 700}}>AI SECURITY COMMAND CENTER</div>
        <div style={{fontSize: 76, fontWeight: 800, lineHeight: 1.05, marginTop: 28, maxWidth: 950}}>Autonomous security drones that patrol for you.</div>
        <div style={{fontSize: 32, color: "#a8bcc9", marginTop: 30}}>Scheduled patrols · Alarm response · AI face recognition</div>
      </div>
    ),
    size,
  );
}
