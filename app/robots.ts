import type {MetadataRoute} from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{userAgent: "*", allow: "/", disallow: ["/admin", "/portal", "/onboarding", "/unauthorized", "/api/"]}],
    sitemap: "https://www.aisecuritycommandcenter.com/sitemap.xml",
    host: "https://www.aisecuritycommandcenter.com",
  };
}
