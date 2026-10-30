import type {Metadata} from "next";
import ContactForm from "./ContactForm";
import {JsonLd, SITE_URL, SiteFooter, SiteNav, icon} from "../components/Site";

export const metadata: Metadata = {
  title: "Contact Us & Book a Drone Security Demo",
  description:
    "Book a free demo of autonomous drone security patrols, or ask us anything about AI drone patrols, scheduling and face recognition for your property.",
  alternates: {canonical: "/contact"},
};

const breadcrumbs = {
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  itemListElement: [
    {"@type": "ListItem", position: 1, name: "Home", item: SITE_URL},
    {"@type": "ListItem", position: 2, name: "Contact", item: `${SITE_URL}/contact`},
  ],
};

const perks = [
  ["A walkthrough built around your property", icon(<><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/></>, 22)],
  ["See autopilot routes, schedules and face AI live", icon(<><circle cx="5" cy="18" r="2"/><circle cx="12" cy="6" r="2"/><circle cx="19" cy="15" r="2"/><path d="M6.5 16.5L10.8 7.8M13.6 7.3l4.2 6.2"/></>, 22)],
  ["Advice on drones, equipment and local rules", icon(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/></>, 22)],
  ["No obligation — just answers", icon(<><path d="M20 6L9 17l-5-5"/></>, 22)],
];

export default function Contact() {
  return (
    <main className="home">
      <JsonLd data={breadcrumbs}/>
      <SiteNav current="/contact"/>
      <section className="hSection cWrap">
        <div>
          <p className="eyebrow">CONTACT US</p>
          <h1 className="cTitle">Book a free drone security demo.</h1>
          <p className="lead">
            Tell us about your property and what you want to protect. We'll reply to you by email as soon as possible.
          </p>
          <ul className="cPerks">
            {perks.map(([t, i]) => <li key={String(t)}><span className="hIcon">{i}</span>{t}</li>)}
          </ul>
        </div>
        <div className="cCard">
          <ContactForm/>
        </div>
      </section>
      <SiteFooter/>
    </main>
  );
}
