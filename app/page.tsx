import type {ReactNode} from "react";

const icon = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);

const features = [
  {
    title: "Person & vehicle alerts",
    text: "Your cameras spot people and vehicles in real time, so you get a useful alert instead of a notification for every shadow or swaying tree.",
    icon: icon(<><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></>),
  },
  {
    title: "Know who's at the door",
    text: "Add the people who belong — family, staff, regular visitors — and get flagged when someone you don't know shows up.",
    icon: icon(<><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></>),
  },
  {
    title: "License plate reading",
    text: "Read plates as vehicles arrive and recognize the ones you've saved, from your own car to delivery vans.",
    icon: icon(<><rect x="2" y="7" width="20" height="10" rx="2"/><path d="M6 12h2M11 12h2M16 12h2"/></>),
  },
  {
    title: "Live drone view",
    text: "Stream a drone's camera into the same screen as your fixed cameras for a bird's-eye look at larger properties.",
    icon: icon(<><circle cx="5" cy="5" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M7 7l3 3M17 7l-3 3M7 17l3-3M17 17l-3-3"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/></>),
  },
  {
    title: "Video stays on your property",
    text: "The AI runs on a Windows PC at your location. Your camera footage is analysed there, not uploaded to someone else's servers.",
    icon: icon(<><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M9 21v-6h6v6"/></>),
  },
  {
    title: "Manage it from anywhere",
    text: "Sign in to your online portal to check your system's status, add devices and manage your account from any browser.",
    icon: icon(<><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></>),
  },
];

const steps = [
  ["Create your account", "Sign up online in a minute. No hardware to buy from us."],
  ["Install on a Windows PC", "Download the Command Center app onto a PC at your property and connect your IP cameras."],
  ["Pair and you're protected", "Link the PC to your account with a pairing code. Alerts and controls are ready right away."],
];

const faqs = [
  ["What do I need to get started?", "A Windows PC that can stay on at your property, and one or more IP security cameras on the same network. The app sets up everything else for you."],
  ["Will my existing cameras work?", "Most IP cameras that provide a standard video stream (RTSP) will work. If you're unsure about a specific model, create an account and we'll help you check."],
  ["Is my video sent to the cloud?", "No. Video is processed on the PC at your location by default. The online portal is used to manage your account and devices."],
  ["How much does it cost?", "Plans depend on how many cameras and which features you need. After you create an account you'll see the options available in your portal, and you can change plans at any time."],
  ["Do you support larger sites?", "Yes. For businesses, multi-site operations and government, we can set up custom limits, deployment and features. Create an account to start the conversation."],
];

export default function Home() {
  return (
    <main className="home">
      <header className="hNav">
        <a href="/" className="hBrand" aria-label="AI Security Command Center home">
          AI SECURITY <span>COMMAND CENTER</span>
        </a>
        <nav aria-label="Main">
          <a href="#features">Features</a>
          <a href="/drones">Drone patrols</a>
          <a href="#how">How it works</a>
          <a href="#faq">FAQ</a>
        </nav>
        <div className="hNavActions">
          <a href="/login" className="hSignIn">Sign in</a>
          <a className="btn small" href="/signup">Get started</a>
        </div>
      </header>

      <section className="hHero">
        <div>
          <p className="eyebrow">AI SECURITY FOR HOMES &amp; BUSINESSES</p>
          <h1>Smarter alerts from the cameras <em>you already have.</em></h1>
          <p className="lead">
            Turn your security cameras into a system that recognizes people, vehicles and license plates —
            with video kept on your own property.
          </p>
          <div className="hActions">
            <a className="btn" href="/signup">Get started</a>
            <a className="ghost" href="#how">See how it works</a>
          </div>
          <ul className="hChecks">
            <li>Works with most IP cameras</li>
            <li>Video stays on-site</li>
            <li>Set up in minutes</li>
          </ul>
        </div>
        <div className="heroPanel" aria-hidden="true">
          <div className="screenTop"><i/> SYSTEM ONLINE <span>LIVE AI</span></div>
          <div className="feedGrid">
            <div className="feed"><strong>FRONT DOOR</strong><span className="box">PERSON DETECTED</span></div>
            <div className="feed car"><strong>DRIVEWAY</strong><span className="box">VEHICLE · PLATE READ</span></div>
            <div className="feed drone"><strong>DRONE</strong><span className="box">LIVE FEED</span></div>
            <div className="feed events">
              <strong>RECENT EVENTS</strong>
              <p>Person at front door <small>now</small></p>
              <p>Known vehicle arrived <small>2m</small></p>
              <p>Camera back online <small>5m</small></p>
            </div>
          </div>
        </div>
      </section>

      <section id="features" className="hSection">
        <p className="eyebrow">WHAT YOU GET</p>
        <h2>Everything you need to see what's happening — and nothing you don't.</h2>
        <div className="hFeatures">
          {features.map(f => (
            <article key={f.title}>
              <div className="hIcon">{f.icon}</div>
              <h3>{f.title}</h3>
              <p>{f.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="hSection">
        <a href="/drones" className="dTeaser">
          <div>
            <p className="eyebrow">NEW · DRONE PATROLS</p>
            <h2>Add eyes in the sky.</h2>
            <p>Schedule autopilot drone patrols, send a drone to any alarm in one tap, and recognize faces from the air.</p>
          </div>
          <span className="btn">Explore drone patrols →</span>
        </a>
      </section>

      <section id="how" className="hSection hHow">
        <p className="eyebrow">HOW IT WORKS</p>
        <h2>Up and running in three steps.</h2>
        <ol className="hSteps">
          {steps.map(([title, text], i) => (
            <li key={title}>
              <span className="hStepNum">{i + 1}</span>
              <h3>{title}</h3>
              <p>{text}</p>
            </li>
          ))}
        </ol>
        <div className="hCenter"><a className="btn" href="/signup">Create your account</a></div>
      </section>

      <section className="hSection">
        <div className="hPrivacy">
          <div className="hIcon big">{icon(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/></>)}</div>
          <div>
            <p className="eyebrow">PRIVACY FIRST</p>
            <h2>Your footage, your property.</h2>
            <p>
              Most cloud cameras send every second of video to a remote server. Command Center does the AI work on a
              PC at your location, so your recordings stay with you. The online portal only handles your account,
              devices and settings.
            </p>
          </div>
        </div>
      </section>

      <section id="faq" className="hSection hFaq">
        <p className="eyebrow">QUESTIONS</p>
        <h2>Frequently asked questions</h2>
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
        <p className="eyebrow">READY WHEN YOU ARE</p>
        <h2>Make your cameras work smarter.</h2>
        <a className="btn" href="/signup">Get started</a>
        <p className="hFinalLogin">Already a customer? <a href="/login">Sign in</a></p>
      </section>

      <footer className="hFooter">
        <div>
          <b>AI SECURITY COMMAND CENTER</b>
          <p>AI-powered security with video processed on your own property.</p>
        </div>
        <nav aria-label="Footer">
          <a href="#features">Features</a>
          <a href="/drones">Drone patrols</a>
          <a href="#how">How it works</a>
          <a href="#faq">FAQ</a>
          <a href="/login">Sign in</a>
          <a href="/signup">Create account</a>
        </nav>
        <span>© 2026 AI Security Command Center</span>
      </footer>
    </main>
  );
}
