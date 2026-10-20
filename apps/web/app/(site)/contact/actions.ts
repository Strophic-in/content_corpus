"use server";

import { createHash } from "node:crypto";
import { headers } from "next/headers";

import { pool } from "@/lib/db";
import { sendEmail } from "@/lib/email";
import { friendly } from "@/lib/errors";
import { CONTACT_EMAIL } from "@/lib/site";

export type ContactState = { ok: boolean; error?: string; to?: string } | null;

const TOPICS = new Set(["Early access / waitlist", "Pricing", "Partnership", "Support", "Privacy or data deletion",
  "Press", "Something else"]);

/** A visitor's message: kept for the owner (Admin → Messages), and emailed to the
 *  contact address when the server can send mail. */
export async function sendContact(_: ContactState, form: FormData): Promise<ContactState> {
  // A field people never see: only a bot fills it in. It is told it worked.
  if (String(form.get("website") ?? "").trim()) return { ok: true };
  const name = String(form.get("name") ?? "").trim().slice(0, 120);
  const email = String(form.get("email") ?? "").trim().slice(0, 254);
  const topicRaw = String(form.get("topic") ?? "");
  const topic = TOPICS.has(topicRaw) ? topicRaw : "Something else";
  const message = String(form.get("message") ?? "").trim().slice(0, 5000);
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return { ok: false, error: "Give an email address we can reply to." };
  if (message.length < 2) return { ok: false, error: "Write a message." };
  // Rate limits key on a hash of the sender's network address, never the address itself.
  const h = await headers();
  const ip = (h.get("x-forwarded-for")?.split(",")[0] ?? h.get("x-real-ip") ?? "").trim();
  const sender = createHash("sha256").update(`${ip}|${process.env.BETTER_AUTH_SECRET ?? ""}`).digest("hex").slice(0, 32);
  let id: string;
  try {
    id = (await pool.query("select api.contact_message($1, $2, $3, $4, $5) as id", [name, email, topic, message, sender]))
      .rows[0].id as string;
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  const sent = await sendEmail(CONTACT_EMAIL, `Content Corpus · ${topic}${name ? ` — ${name}` : ""}`,
    `${message}\n\n— ${name || "(no name)"} <${email}>\nTopic: ${topic}`, email);
  if (sent) await pool.query("select api.contact_emailed($1)", [id]).catch(() => {});
  return { ok: true, to: email };
}
