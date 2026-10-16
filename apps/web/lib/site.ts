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
