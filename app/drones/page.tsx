import type {Metadata} from "next";
import {DronePanel} from "../components/DronePanel";
import {FinalCta, JsonLd, SITE_URL, SiteFooter, SiteNav, faqJsonLd, icon} from "../components/Site";

export const metadata: Metadata = {
  title: "Drone Patrol Software: Autopilot Routes & Scheduled Security Patrols",
  description:
    "Plan autopilot drone patrol routes on a map, schedule security patrols by day and time, relay between drones for 24/7 coverage and respond to alarms in one tap.",
  alternates: {canonical: "/drones"},
};

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

const faqs: [string, string][] = [
  ["Which drones are supported?", "The system works with DJI drones through our Drone Link Android app. It is tested with the DJI Mini 3 Pro and RC-N1 controller. Other DJI models may work but have not been tested yet."],
  ["What else do I need?", "A Windows PC running the Command Center app, an Android phone connected to the drone's controller, and Wi-Fi linking the phone and PC."],
  ["Can it really fly on its own?", "Yes. Saved routes and scheduled patrols fly on autopilot after safety checks. A pilot must still be able to take over, and you must follow your local aviation rules, which may require keeping the drone in sight."],
  ["Can I use more than one drone?", "Yes. Multiple drones can be connected, and the relay feature hands a patrol from one drone to the next when batteries run low."],
  ["Is drone footage sent to the cloud?", "No. Like your fixed cameras, the drone's video is analysed on the PC at your property."],
];

const breadcrumbs = {
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  itemListElement: [
    {"@type": "ListItem", position: 1, name: "Home", item: SITE_URL},
    {"@type": "ListItem", position: 2, name: "Drone patrols", item: `${SITE_URL}/drones`},
  ],
};

export default function Drones() {
  return (
    <main className="home">
      <JsonLd data={faqJsonLd(faqs)}/>
      <JsonLd data={breadcrumbs}/>
      <SiteNav current="/drones"/>

      <section className="hHero">
        <div>
          <p className="eyebrow">DRONE PATROL SOFTWARE</p>
          <h1>Drone security patrols, <em>on autopilot.</em></h1>
          <p className="lead">
            Plan a patrol route on a map, put it on a schedule and let the drone fly it — day or night. Add more
            drones for non-stop coverage, and send one to any alarm in a single tap.
          </p>
          <div className="hActions">
            <a className="btn" href="/contact">Book a free demo</a>
            <a className="ghost" href="#capabilities">See what it can do</a>
          </div>
          <ul className="hChecks">
            <li>Scheduled autopilot patrols</li>
            <li>AI face recognition</li>
            <li>Pilot override anytime</li>
          </ul>
        </div>

        <DronePanel/>
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

      <FinalCta eyebrow="TAKE YOUR SECURITY TO THE SKY" title="See a drone patrol plan for your property."/>
      <SiteFooter/>
    </main>
  );
}
