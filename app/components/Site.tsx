import type {ReactNode} from "react";

export const SITE_URL = "https://www.aisecuritycommandcenter.com";
export const SITE_NAME = "AI Security Command Center";

export const icon = (d: ReactNode, size = 26) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);

const LINKS: [string, string][] = [
  ["/drones", "Drone patrols"],
  ["/#cameras", "Cameras"],
  ["/#how", "How it works"],
  ["/#faq", "FAQ"],
  ["/contact", "Contact"],
];

export function SiteNav({current}: {current?: string}) {
  return (
    <header className="hNav">
      <a href="/" className="hBrand" aria-label={`${SITE_NAME} home`}>
        AI SECURITY <span>COMMAND CENTER</span>
      </a>
      <nav aria-label="Main">
        {LINKS.map(([href, label]) => (
          <a key={href} href={href} aria-current={current === href ? "page" : undefined}>{label}</a>
        ))}
      </nav>
      <div className="hNavActions">
        <a href="/login" className="hSignIn">Sign in</a>
        <a className="btn small" href="/contact">Book a demo</a>
        <details className="hMenu">
          <summary aria-label="Open menu"><span/><span/><span/></summary>
          <div>
            {LINKS.map(([href, label]) => <a key={href} href={href}>{label}</a>)}
            <a href="/login">Sign in</a>
          </div>
        </details>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="hFooter">
      <div>
        <b>AI SECURITY COMMAND CENTER</b>
        <p>Autonomous drone patrols and AI security, processed on your own property.</p>
      </div>
      <nav aria-label="Footer">
        <a href="/drones">Drone patrols</a>
        <a href="/#cameras">Cameras</a>
        <a href="/#faq">FAQ</a>
        <a href="/contact">Contact us</a>
        <a href="/login">Sign in</a>
        <a href="/signup">Create account</a>
      </nav>
      <span>© {new Date().getFullYear()} AI Security Command Center</span>
    </footer>
  );
}

export function FinalCta({eyebrow, title}: {eyebrow: string; title: string}) {
  return (
    <section className="final">
      <p className="eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      <a className="btn" href="/contact">Book a free demo</a>
      <a className="ghost" href="/signup">Create an account</a>
      <p className="hFinalLogin">Already a customer? <a href="/login">Sign in</a></p>
    </section>
  );
}

export function JsonLd({data}: {data: object}) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{__html: JSON.stringify(data)}} />;
}

export function faqJsonLd(faqs: [string, string][]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map(([q, a]) => ({"@type": "Question", name: q, acceptedAnswer: {"@type": "Answer", text: a}})),
  };
}
