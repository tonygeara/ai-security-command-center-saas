import type {Metadata} from "next";
export const metadata: Metadata = {title: "Customer Sign In", description: "Sign in to your AI Security Command Center portal to manage drones, cameras and devices.", alternates: {canonical: "/login"}};
export default function Layout({children}: {children: React.ReactNode}) { return children; }
