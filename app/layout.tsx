import "./globals.css";
import type {Metadata, Viewport} from "next";

const SITE_URL = "https://www.aisecuritycommandcenter.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "AI Drone Security & Autonomous Drone Patrols | AI Security Command Center",
    template: "%s | AI Security Command Center",
  },
  description:
    "Autonomous security drones that patrol your property on a schedule, respond to alarms in one tap and recognize faces and vehicles with AI. Book a free demo.",
  applicationName: "AI Security Command Center",
  keywords: [
    "drone security", "security drone", "autonomous drone patrol", "drone patrol system", "drone surveillance",
    "AI security drone", "scheduled drone patrols", "drone face recognition", "drone security company",
    "perimeter security drone", "construction site drone security", "farm security drone",
  ],
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "AI Security Command Center",
    title: "Autonomous Security Drones That Patrol For You",
    description: "Scheduled autopilot drone patrols, one-tap alarm response and AI face recognition from the air.",
    locale: "en_CA",
  },
  twitter: {
    card: "summary_large_image",
    title: "Autonomous Security Drones That Patrol For You",
    description: "Scheduled autopilot drone patrols, one-tap alarm response and AI face recognition from the air.",
  },
  robots: {index: true, follow: true, googleBot: {index: true, follow: true, "max-image-preview": "large", "max-snippet": -1}},
  ...(process.env.GOOGLE_SITE_VERIFICATION ? {verification: {google: process.env.GOOGLE_SITE_VERIFICATION}} : {}),
};

export const viewport: Viewport = {themeColor: "#050b12", width: "device-width", initialScale: 1};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return <html lang="en"><body>{children}</body></html>;
}
