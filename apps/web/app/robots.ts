import type { MetadataRoute } from "next";
import { connection } from "next/server";

import { siteUrl } from "@/lib/site";

// Crawlers (Google's app review among them) may read the public pages and the
// assets they render with; everything else redirects to the sign-in page anyway.
export default async function robots(): Promise<MetadataRoute.Robots> {
  await connection();          // the address is the server's, not the build's
  return { rules: { userAgent: "*", allow: "/", disallow: "/api/" }, sitemap: `${siteUrl()}/sitemap.xml` };
}
