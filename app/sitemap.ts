import type {MetadataRoute} from "next";

const SITE_URL = "https://www.aisecuritycommandcenter.com";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    {url: `${SITE_URL}/`, lastModified: now, changeFrequency: "weekly", priority: 1},
    {url: `${SITE_URL}/drones`, lastModified: now, changeFrequency: "weekly", priority: 0.9},
    {url: `${SITE_URL}/contact`, lastModified: now, changeFrequency: "monthly", priority: 0.8},
    {url: `${SITE_URL}/signup`, lastModified: now, changeFrequency: "yearly", priority: 0.4},
    {url: `${SITE_URL}/login`, lastModified: now, changeFrequency: "yearly", priority: 0.2},
  ];
}
