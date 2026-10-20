import "server-only";

import "./env";

/**
 * A plain-text email. Sent through the owner's own mailbox over SMTP when it is set
 * up (SMTP_USER and SMTP_PASS: hafeez@strophic.in and a Google app password, on
 * smtp.gmail.com unless SMTP_HOST says otherwise), else through Resend (RESEND_API_KEY
 * and RESEND_FROM). Best effort: without either, or if sending fails, nothing is sent
 * and the app carries on (Admin shows the same information).
 */
export async function sendEmail(to: string | string[], subject: string, text: string,
                                replyTo?: string): Promise<boolean> {
  const recipients = (Array.isArray(to) ? to : [to]).filter(Boolean);
  if (!recipients.length) return false;
  if (process.env.SMTP_USER && process.env.SMTP_PASS) return smtp(recipients, subject, text, replyTo);
  return resend(recipients, subject, text, replyTo);
}

async function smtp(to: string[], subject: string, text: string, replyTo?: string): Promise<boolean> {
  try {
    const { createTransport } = await import("nodemailer");
    const port = Number(process.env.SMTP_PORT || 465);
    const transport = createTransport({
      host: process.env.SMTP_HOST || "smtp.gmail.com", port, secure: port === 465,
      auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS },
      connectionTimeout: 10_000, greetingTimeout: 10_000, socketTimeout: 15_000,
    });
    await transport.sendMail({
      from: process.env.SMTP_FROM || `Content Corpus <${process.env.SMTP_USER}>`,
      to, subject, text, ...(replyTo ? { replyTo } : {}),
    });
    return true;
  } catch (err) {
    console.error("email not sent:", (err as Error).message);
    return false;
  }
}

async function resend(to: string[], subject: string, text: string, replyTo?: string): Promise<boolean> {
  const key = process.env.RESEND_API_KEY;
  const from = process.env.RESEND_FROM;
  if (!key || !from) return false;
  try {
    const r = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ from, to, subject, text, ...(replyTo ? { reply_to: replyTo } : {}) }),
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
