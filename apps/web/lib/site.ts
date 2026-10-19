import "server-only";

import "@/lib/env";

// The public pages (homepage, privacy policy, terms) that Google's and Meta's app
// reviews read. Their wording must match what the code does; change both together.

export const POLICIES_UPDATED = "16 October 2026";

// The public contact address: the contact page, the waitlist, the footer.
export const CONTACT_EMAIL = "hafeez@strophic.in";

// Where to write about privacy or data deletion. Both reviews require one; without
// PRIVACY_CONTACT_EMAIL it is the public contact address.
export function contactEmail(): string {
  return process.env.PRIVACY_CONTACT_EMAIL?.trim() || CONTACT_EMAIL;
}

// The public address, e.g. https://content-corpus.strophic.in. Google matches the
// homepage's privacy-policy link against the consent screen's URL, so the public
// pages link to it absolutely.
export function siteUrl(): string {
  return (process.env.BETTER_AUTH_URL ?? "").replace(/\/$/, "");
}

/** Where to send the browser back to: the public address. Behind nginx the app sees
 *  its own (http://0.0.0.0:3000), and a redirect built from req.url sent people there. */
export function origin(req: { url: string }): string {
  return siteUrl() || req.url;
}
