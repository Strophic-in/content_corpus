import type { MetadataRoute } from "next";
import { connection } from "next/server";

import { siteUrl } from "@/lib/site";

// The public pages search engines may list; the app itself sits behind sign-in.
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  await connection();          // the address is the server's, not the build's
  const site = siteUrl();
  return [
    { url: `${site}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${site}/contact`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${site}/privacy`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${site}/terms`, changeFrequency: "yearly", priority: 0.3 },
  ];
}
