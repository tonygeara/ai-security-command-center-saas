import type {Metadata} from "next";
import type {ReactNode} from "react";

export const metadata: Metadata = {
  title: "Drone Patrols & Aerial Security | AI Security Command Center",
  description:
    "Autopilot drone patrols on a schedule, instant alarm response and AI face, person and vehicle recognition from the air — all controlled from your AI Security Command Center.",
};

const icon = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);

const capabilities = [
  {
    title: "Autopilot patrol routes",
    text: "Tap stops on a map and save the route. The drone takes off, flies each stop in order at your chosen height, speed and pause time, then returns home, hovers or lands.",
    icon: icon(<><circle cx="5" cy="18" r="2"/><circle cx="12" cy="6" r="2"/><circle cx="19" cy="15" r="2"/><path d="M6.5 16.5L10.8 7.8M13.6 7.3l4.2 6.2"/></>),
  },
  {
    title: "Scheduled patrols",
    text: "Run any saved route automatically on the days and times you pick — every night at 2 a.m., weekends only, whatever fits your site.",
    icon: icon(<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/><path d="M12 14v3l2 1"/></>),
  },
  {
    title: "Non-stop coverage with relay",
    text: "Set a patrol to repeat continuously. When one drone's battery runs low it heads home and the next ready drone takes off to continue the patrol.",
    icon: icon(<><path d="M4 12a8 8 0 0 1 14-5.3L20 9"/><path d="M20 4v5h-5"/><path d="M20 12a8 8 0 0 1-14 5.3L4 15"/><path d="M4 20v-5h5"/></>),
  },
  {
    title: "One-tap alarm response",
    text: "When a camera spots something, send a drone straight to that camera's location. It hovers on scene for a set time and comes home on its own.",
    icon: icon(<><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/></>),
  },
  {
    title: "Face AI from the air",
    text: "The drone's live video runs through the same AI as your fixed cameras: it recognizes enrolled people, flags unknown faces, and detects people and vehicles.",
    icon: icon(<><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><circle cx="12" cy="10" r="2.5"/><path d="M8 17c.8-2 2.3-3 4-3s3.2 1 4 3"/></>),
  },
  {
    title: "Control from your phone",
    text: "Get alerts with snapshots on Telegram, then start a patrol, approve a scheduled flight or send the drone out with a single tap — wherever you are.",
    icon: icon(<><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></>),
  },
];

const scenarios = [
  ["Farms & rural properties", "Cover fence lines, barns and long driveways that fixed cameras can't reach."],
  ["Construction & storage yards", "Run scheduled night patrols over equipment and materials after the crew leaves."],
  ["Estates & large homes", "Check the perimeter in minutes and see who is on the property, from above."],
  ["Commercial & industrial sites", "Back up your guards with aerial patrols and a fast first look at every alarm."],
];

const steps = [
  ["Connect your drone", "Pair a supported DJI drone with the Command Center using our Drone Link app on an Android phone."],
  ["Draw your patrol", "Tap the stops on a map, set height, speed and what happens at the end, and save the route."],
  ["Set the schedule", "Choose days and times. Pick auto-start, or get a Start / Skip message on Telegram first."],
  ["Watch and respond", "See the live aerial feed with AI detections, and get alerts the moment something is found."],
];

const safety = [
  "A pilot can take over at any moment from the controller or dashboard",
  "If the connection drops, the drone stops and hovers within half a second",
  "Built-in limits: 120 m maximum height and 500 m from home",
  "Battery checks before launch and automatic return home",
  "DJI's own return-to-home stays active on signal loss or low battery",
  "A simulator mode lets you practise routes with no real flight",
];

const faqs = [
  ["Which drones are supported?", "The system works with DJI drones through our Drone Link Android app. It is tested with the DJI Mini 3 Pro and RC-N1 controller. Other DJI models may work but have not been tested yet."],
  ["What else do I need?", "A Windows PC running the Command Center app, an Android phone connected to the drone's controller, and Wi-Fi linking the phone and PC."],
  ["Can it really fly on its own?", "Yes. Saved routes and scheduled patrols fly on autopilot after safety checks. A pilot must still be able to take over, and you must follow your local aviation rules, which may require keeping the drone in sight."],
  ["Can I use more than one drone?", "Yes. Multiple drones can be connected, and the relay feature hands a patrol from one drone to the next when batteries run low."],
  ["Is drone footage sent to the cloud?", "No. Like your fixed cameras, the drone's video is analysed on the PC at your property."],
];

export default function Drones() {
  return (
    <main className="home">
      <header className="hNav">
        <a href="/" className="hBrand" aria-label="AI Security Command Center home">
          AI SECURITY <span>COMMAND CENTER</span>
        </a>
        <nav aria-label="Main">
          <a href="/#features">Features</a>
          <a href="/drones" aria-current="page">Drone patrols</a>
          <a href="/#how">How it works</a>
          <a href="/#faq">FAQ</a>
        </nav>
        <div className="hNavActions">
          <a href="/login" className="hSignIn">Sign in</a>
          <a className="btn small" href="/signup">Get started</a>
        </div>
      </header>

      <section className="hHero">
        <div>
          <p className="eyebrow">DRONE PATROLS · AUTOPILOT · FACE AI</p>
          <h1>Your security guard <em>now flies.</em></h1>
          <p className="lead">
            Schedule autopilot drone patrols, send a drone to any alarm in one tap, and let AI recognize faces,
            people and vehicles from the air — all from the same command center as your cameras.
          </p>
          <div className="hActions">
            <a className="btn" href="/signup">Get started</a>
            <a className="ghost" href="#capabilities">See what it can do</a>
          </div>
          <ul className="hChecks">
            <li>Scheduled autopilot patrols</li>
            <li>AI face recognition</li>
            <li>Pilot override anytime</li>
          </ul>
        </div>

        <div className="dPanel" aria-hidden="true">
          <div className="screenTop"><i/> PATROL ACTIVE <span>NIGHT ROUTE · 02:00</span></div>
          <div className="dMap">
            <svg viewBox="0 0 400 260" preserveAspectRatio="none">
              <defs>
                <pattern id="grid" width="26" height="26" patternUnits="userSpaceOnUse">
                  <path d="M26 0H0V26" fill="none" stroke="#14303f" strokeWidth="1"/>
                </pattern>
              </defs>
              <rect width="400" height="260" fill="url(#grid)"/>
              <rect x="150" y="95" width="90" height="60" rx="4" fill="#0f2534" stroke="#244a5e"/>
              <path d="M40 220 L95 60 L300 45 L355 190 L190 230 Z" fill="none" stroke="#37d4ff" strokeWidth="2.5" strokeDasharray="7 6" className="dRoute"/>
              {[[40,220,"H"],[95,60,"1"],[300,45,"2"],[355,190,"3"],[190,230,"4"]].map(([x,y,l]) => (
                <g key={String(l)}>
                  <circle cx={Number(x)} cy={Number(y)} r="11" fill={l==="H"?"#54ef9c":"#0b6fa8"} stroke="#9fe9ff" strokeWidth="1.5"/>
                  <text x={Number(x)} y={Number(y)+4} textAnchor="middle" fontSize="11" fontWeight="700" fill="#061019">{l}</text>
                </g>
              ))}
              <g className="dDrone">
                <circle cx="300" cy="45" r="18" fill="#37d4ff22" stroke="#37d4ff"/>
                <path d="M292 37l16 16M308 37l-16 16" stroke="#eaf6ff" strokeWidth="2.5" strokeLinecap="round"/>
              </g>
            </svg>
            <div className="dHud">
              <span>ALT 30 m</span><span>SPD 6 m/s</span><span>BATT 74%</span>
            </div>
          </div>
          <div className="dFeedRow">
            <div className="dFeed">
              <strong>DRONE CAM · STOP 2</strong>
              <div className="dFace"/>
              <span className="box">UNKNOWN PERSON</span>
            </div>
            <div className="feed events">
              <strong>PATROL LOG</strong>
              <p>Unknown face at stop 2 <small>now</small></p>
              <p>Vehicle at gate <small>3m</small></p>
              <p>Patrol started <small>6m</small></p>
            </div>
          </div>
        </div>
      </section>

      <section className="strip dStrip">
        <span>AUTOPILOT ROUTES</span><span>SCHEDULED PATROLS</span><span>DRONE RELAY</span><span>ALARM RESPONSE</span><span>FACE AI</span>
      </section>

      <section id="capabilities" className="hSection">
        <p className="eyebrow">WHAT YOUR DRONE CAN DO</p>
        <h2>An aerial patrol team that works on its own schedule.</h2>
        <div className="hFeatures">
          {capabilities.map(c => (
            <article key={c.title}>
              <div className="hIcon">{c.icon}</div>
              <h3>{c.title}</h3>
              <p>{c.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="hSection dSplit">
        <div>
          <p className="eyebrow">FACE AI IN THE AIR</p>
          <h2>Know who is on your property, not just that someone is.</h2>
          <p className="dBody">
            Enroll the people who belong — family, staff, contractors. During a patrol or alarm response, the drone's
            camera feeds the AI in real time. Recognized people are labelled by name; anyone unknown is flagged and
            saved with a snapshot, so you can act fast.
          </p>
          <ul className="dList">
            <li>Recognizes enrolled faces and flags strangers</li>
            <li>Detects people and vehicles from above</li>
            <li>Tracking assist keeps the subject in view on your screen</li>
            <li>Every sighting is logged with time and location</li>
          </ul>
        </div>
        <div className="dIdCard" aria-hidden="true">
          <div className="dIdRow known"><i/><div><b>Known · Staff</b><small>Stop 1 · Main gate</small></div><em>MATCH</em></div>
          <div className="dIdRow unknown"><i/><div><b>Unknown person</b><small>Stop 2 · North fence</small></div><em>ALERT</em></div>
          <div className="dIdRow"><i/><div><b>Vehicle detected</b><small>Stop 4 · Yard entrance</small></div><em>LOGGED</em></div>
          <p>Alert sent to your phone with snapshot · Start / Recall buttons</p>
        </div>
      </section>

      <section className="hSection">
        <p className="eyebrow">BUILT FOR LARGER PROPERTIES</p>
        <h2>Where drones make the biggest difference.</h2>
        <div className="dScenarios">
          {scenarios.map(([t, d]) => (
            <article key={t}><h3>{t}</h3><p>{d}</p></article>
          ))}
        </div>
      </section>

      <section className="hSection hHow">
        <p className="eyebrow">HOW IT WORKS</p>
        <h2>From unboxing to your first patrol.</h2>
        <ol className="hSteps dSteps">
          {steps.map(([title, text], i) => (
            <li key={title}>
              <span className="hStepNum">{i + 1}</span>
              <h3>{title}</h3>
              <p>{text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="hSection">
        <div className="hPrivacy">
          <div className="hIcon big">{icon(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/></>)}</div>
          <div>
            <p className="eyebrow">SAFETY BUILT IN</p>
            <h2>Autonomous, but always under your control.</h2>
            <ul className="dSafety">
              {safety.map(s => <li key={s}>{s}</li>)}
            </ul>
          </div>
        </div>
      </section>

      <section className="hSection hFaq">
        <p className="eyebrow">QUESTIONS</p>
        <h2>Drone patrol FAQ</h2>
        <div className="hFaqList">
          {faqs.map(([q, a]) => (
            <details key={q}>
              <summary>{q}</summary>
              <p>{a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="final">
        <p className="eyebrow">TAKE YOUR SECURITY TO THE SKY</p>
        <h2>Start your first drone patrol.</h2>
        <a className="btn" href="/signup">Get started</a>
        <p className="hFinalLogin">Already a customer? <a href="/login">Sign in</a></p>
      </section>

      <footer className="hFooter">
        <div>
          <b>AI SECURITY COMMAND CENTER</b>
          <p>AI-powered security with video processed on your own property.</p>
        </div>
        <nav aria-label="Footer">
          <a href="/#features">Features</a>
          <a href="/drones">Drone patrols</a>
          <a href="/#faq">FAQ</a>
          <a href="/login">Sign in</a>
          <a href="/signup">Create account</a>
        </nav>
        <span>© 2026 AI Security Command Center</span>
      </footer>
    </main>
  );
}
