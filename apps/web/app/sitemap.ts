import type { MetadataRoute } from "next";

import { siteUrl } from "@/lib/site";

// The public pages search engines may list; the app itself sits behind sign-in.
export default function sitemap(): MetadataRoute.Sitemap {
  const site = siteUrl();
  return [
    { url: `${site}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${site}/contact`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${site}/privacy`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${site}/terms`, changeFrequency: "yearly", priority: 0.3 },
  ];
}
