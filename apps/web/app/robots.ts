import type { MetadataRoute } from "next";

// Crawlers (Google's app review among them) may read the public pages and the
// assets they render with; everything else redirects to the sign-in page anyway.
export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", allow: "/", disallow: "/api/" } };
}
