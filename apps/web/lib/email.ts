import "server-only";

import "./env";

/**
 * A plain-text email through Resend (RESEND_API_KEY, and RESEND_FROM — an address
 * on a domain verified in Resend, like "Content Corpus <noreply@strophic.in>").
 * Best effort: without the keys, or if Resend is down, nothing is sent and the
 * app carries on (the admin page shows the same information).
 */
export async function sendEmail(to: string | string[], subject: string, text: string): Promise<boolean> {
  const key = process.env.RESEND_API_KEY;
  const from = process.env.RESEND_FROM;
  const recipients = (Array.isArray(to) ? to : [to]).filter(Boolean);
  if (!key || !from || !recipients.length) return false;
  try {
    const r = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ from, to: recipients, subject, text }),
      signal: AbortSignal.timeout(5000),
    });
    return r.ok;
  } catch {
    return false;
  }
}

/** The owners' addresses: the first sign-in emails allowed. */
export function ownerEmails(): string[] {
  return (process.env.AUTH_ALLOWED_EMAILS ?? "").split(",").map((e) => e.trim()).filter(Boolean);
}
