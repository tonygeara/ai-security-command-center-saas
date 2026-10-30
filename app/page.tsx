import type {Metadata} from "next";
import {DronePanel} from "./components/DronePanel";
import {FinalCta, JsonLd, SITE_NAME, SITE_URL, SiteFooter, SiteNav, faqJsonLd, icon} from "./components/Site";

export const metadata: Metadata = {
  title: {absolute: "AI Drone Security & Autonomous Drone Patrols | AI Security Command Center"},
  description:
    "Autonomous security drones that patrol your property on a schedule, respond to alarms in one tap and recognize faces and vehicles with AI. Book a free demo.",
  alternates: {canonical: "/"},
};

const capabilities = [
  {
    title: "Autonomous drone patrols",
    text: "Draw a route on a map once. The drone takes off, flies every checkpoint and comes home on its own.",
    icon: icon(<><circle cx="5" cy="18" r="2"/><circle cx="12" cy="6" r="2"/><circle cx="19" cy="15" r="2"/><path d="M6.5 16.5L10.8 7.8M13.6 7.3l4.2 6.2"/></>),
  },
  {
    title: "Patrols on a schedule",
    text: "Night rounds at 2 a.m., weekend sweeps, shift changes — patrols launch automatically on the days and times you set.",
    icon: icon(<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/><path d="M12 14v3l2 1"/></>),
  },
  {
    title: "Instant alarm response",
    text: "When an alarm or camera detects something, a drone flies straight to the spot and shows you live video in seconds.",
    icon: icon(<><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/></>),
  },
  {
    title: "AI face recognition from the air",
    text: "The drone's camera recognizes your enrolled people and flags strangers, people and vehicles automatically.",
    icon: icon(<><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><circle cx="12" cy="10" r="2.5"/><path d="M8 17c.8-2 2.3-3 4-3s3.2 1 4 3"/></>),
  },
  {
    title: "24/7 coverage with drone relay",
    text: "When one drone's battery runs low it returns home and the next drone takes off to continue the patrol.",
    icon: icon(<><path d="M4 12a8 8 0 0 1 14-5.3L20 9"/><path d="M20 4v5h-5"/><path d="M20 12a8 8 0 0 1-14 5.3L4 15"/><path d="M4 20v-5h5"/></>),
  },
  {
    title: "Alerts and control on your phone",
    text: "Get alerts with snapshots, approve a scheduled patrol or send the drone out with one tap from anywhere.",
    icon: icon(<><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></>),
  },
];

const scenarios = [
  ["Farms & rural land", "Patrol fence lines, barns and long driveways that fixed cameras can't cover."],
  ["Construction sites & yards", "Run night patrols over equipment and materials after the crew leaves."],
  ["Estates & large homes", "Sweep the whole perimeter in minutes and see who's on the property."],
  ["Commercial & industrial", "Support your guards with aerial patrols and a fast first look at every alarm."],
];

const steps = [
  ["Book a demo", "Tell us about your property. We'll show you how drone patrols would work for your site."],
  ["Connect your drone", "Install the Command Center on a Windows PC and pair a supported DJI drone with our Drone Link app."],
  ["Plan routes & schedules", "Tap checkpoints on a map, set patrol times, and choose auto-start or approve-first."],
  ["Get protected from above", "Watch live aerial video with AI detections and get alerts the moment something's found."],
];

const faqs: [string, string][] = [
  ["What is an autonomous security drone?", "It's a drone that flies security patrols by itself. You plan the route and schedule once; the drone takes off, flies each checkpoint while AI watches the video, and returns home — with a pilot able to take over at any time."],
  ["Which drones are supported?", "We work with DJI drones through our Drone Link Android app, tested with the DJI Mini 3 Pro and RC-N1 controller. Other DJI models may work but haven't been tested yet."],
  ["Do I need security cameras too?", "No. Drones work on their own. If you have IP cameras, the system can use them too, so a camera alert can send a drone straight to the spot."],
  ["Can drones patrol at night or around the clock?", "Patrols can be scheduled at any time and repeated continuously. With more than one drone, the relay feature swaps drones automatically when batteries run low."],
  ["Is it legal to fly security drones?", "Drone rules depend on your country and site. You must follow your local aviation rules, which may require a licensed pilot and keeping the drone in sight. Ask us and we'll help you plan a compliant setup."],
  ["Is my video sent to the cloud?", "No. Drone and camera video is analysed on a PC at your property. The online portal only manages your account and devices."],
];

const orgJsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {"@type": "Organization", "@id": `${SITE_URL}/#org`, name: SITE_NAME, url: SITE_URL, logo: `${SITE_URL}/icon.svg`,
     contactPoint: {"@type": "ContactPoint", contactType: "sales", url: `${SITE_URL}/contact`}},
    {"@type": "WebSite", "@id": `${SITE_URL}/#website`, url: SITE_URL, name: SITE_NAME, publisher: {"@id": `${SITE_URL}/#org`}},
    {"@type": "SoftwareApplication", name: SITE_NAME, applicationCategory: "SecurityApplication", operatingSystem: "Windows, Android",
     description: "Autonomous drone patrols, scheduled drone security, alarm response and AI face recognition for properties and businesses.",
     publisher: {"@id": `${SITE_URL}/#org`}},
  ],
};

export default function Home() {
  return (
    <main className="home">
      <JsonLd data={orgJsonLd}/>
      <JsonLd data={faqJsonLd(faqs)}/>
      <SiteNav/>

      <section className="hHero">
        <div>
          <p className="eyebrow">AI DRONE SECURITY</p>
          <h1>Autonomous security drones that <em>patrol for you.</em></h1>
          <p className="lead">
            Schedule drone patrols that fly themselves, send a drone to any alarm in seconds, and let AI recognize
            faces and vehicles from the air. One command center for your whole property.
          </p>
          <div className="hActions">
            <a className="btn" href="/contact">Book a free demo</a>
            <a className="ghost" href="/drones">See drone patrols</a>
          </div>
          <ul className="hChecks">
            <li>Autopilot routes</li>
            <li>Scheduled patrols</li>
            <li>AI face recognition</li>
          </ul>
        </div>
        <DronePanel/>
      </section>

      <section className="strip dStrip">
        <span>AUTONOMOUS PATROLS</span><span>SCHEDULED FLIGHTS</span><span>ALARM RESPONSE</span><span>FACE AI</span><span>DRONE RELAY</span>
      </section>

      <section id="features" className="hSection">
        <p className="eyebrow">DRONE SECURITY, DONE FOR YOU</p>
        <h2>A security patrol that flies itself.</h2>
        <div className="hFeatures">
          {capabilities.map(c => (
            <article key={c.title}>
              <div className="hIcon">{c.icon}</div>
              <h3>{c.title}</h3>
              <p>{c.text}</p>
            </article>
          ))}
        </div>
        <div className="hCenter"><a className="ghost" href="/drones">Explore all drone patrol features →</a></div>
      </section>

      <section className="hSection dSplit">
        <div>
          <p className="eyebrow">FACE AI IN THE AIR</p>
          <h2>Know who is on your property — not just that someone is.</h2>
          <p className="dBody">
            Enroll the people who belong: family, staff, contractors. On every patrol, the drone's camera feeds the AI in
            real time. Known people are matched by name. Anyone unknown is flagged and saved with a snapshot so you can act fast.
          </p>
          <ul className="dList">
            <li>Recognizes enrolled faces and flags strangers</li>
            <li>Detects people and vehicles from above</li>
            <li>Every sighting logged with time and location</li>
          </ul>
        </div>
        <div className="dIdCard" aria-hidden="true">
          <div className="dIdRow known"><i/><div><b>Known · Staff</b><small>Checkpoint 1 · Main gate</small></div><em>MATCH</em></div>
          <div className="dIdRow unknown"><i/><div><b>Unknown person</b><small>Checkpoint 2 · North fence</small></div><em>ALERT</em></div>
          <div className="dIdRow"><i/><div><b>Vehicle detected</b><small>Checkpoint 4 · Yard entrance</small></div><em>LOGGED</em></div>
          <p>Alert sent to your phone with snapshot · Recall or continue patrol</p>
        </div>
      </section>

      <section className="hSection">
        <p className="eyebrow">WHO IT'S FOR</p>
        <h2>Built for properties too big for cameras alone.</h2>
        <div className="dScenarios">
          {scenarios.map(([t, d]) => (
            <article key={t}><h3>{t}</h3><p>{d}</p></article>
          ))}
        </div>
      </section>

      <section id="how" className="hSection hHow">
        <p className="eyebrow">HOW IT WORKS</p>
        <h2>From first call to first patrol.</h2>
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

      <section id="cameras" className="hSection">
        <div className="hPrivacy">
          <div className="hIcon big">{icon(<><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></>)}</div>
          <div>
            <p className="eyebrow">WORKS WITH YOUR CAMERAS TOO</p>
            <h2>Cameras watch. Drones respond.</h2>
            <p>
              Already have IP security cameras? Connect them to the same command center for person, vehicle and license
              plate alerts. When a camera spots something, a drone can be on its way to that exact spot in one tap.
              All video is processed on your own property, not in someone else's cloud.
            </p>
          </div>
        </div>
      </section>

      <section id="faq" className="hSection hFaq">
        <p className="eyebrow">QUESTIONS</p>
        <h2>Drone security FAQ</h2>
        <div className="hFaqList">
          {faqs.map(([q, a]) => (
            <details key={q}>
              <summary>{q}</summary>
              <p>{a}</p>
            </details>
          ))}
        </div>
      </section>

      <FinalCta eyebrow="SEE IT FLY" title="Get a free demo of autonomous drone patrols."/>
      <SiteFooter/>
    </main>
  );
}
