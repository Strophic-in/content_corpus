import "server-only";

import "@/lib/env";

// The public pages (homepage, privacy policy, terms) that Google's and Meta's app
// reviews read. Their wording must match what the code does; change both together.

export const POLICIES_UPDATED = "16 October 2026";

// Where to write about privacy or data deletion. Both reviews require one; without
// PRIVACY_CONTACT_EMAIL it is the owner's sign-in address.
export function contactEmail(): string | undefined {
  return process.env.PRIVACY_CONTACT_EMAIL?.trim()
    || process.env.AUTH_ALLOWED_EMAILS?.split(",")[0]?.trim()
    || undefined;
}

// The public address, e.g. https://content-corpus.strophic.in. Google matches the
// homepage's privacy-policy link against the consent screen's URL, so the public
// pages link to it absolutely.
export function siteUrl(): string {
  return (process.env.BETTER_AUTH_URL ?? "").replace(/\/$/, "");
}
