"use server";

import { refresh } from "next/cache";
import { z } from "zod";

import { asUser } from "@/lib/db";
import { sendEmail } from "@/lib/email";
import { friendly } from "@/lib/errors";
import { requireOwner } from "@/lib/session";

import type { ActionState } from "../actions";

// Rupees in the form, paise in the database; empty = no limit.
const rupees = z.union([z.literal(""), z.coerce.number().min(0).max(10_000_000)])
  .transform((v) => (v === "" ? null : Math.round(v * 100)));

/** Approve, suspend or re-limit one member (never an owner — the database refuses). */
export async function setMember(userId: string, _: ActionState, form: FormData): Promise<ActionState> {
  const owner = await requireOwner();
  const parsed = z.object({ status: z.enum(["pending", "active", "suspended"]), limit: rupees })
    .safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const { status, limit } = parsed.data;
  try {
    const before = await asUser(owner.id, async (db) => {
      const prev = (await db.query("select status, email from api.admin_members() where user_id = $1",
                                   [userId])).rows[0] as { status: string; email: string } | undefined;
      await db.query("select api.admin_set_member($1, $2, $3)", [userId, status, limit]);
      return prev;
    });
    if (before && before.status !== "active" && status === "active") {
      await sendEmail(before.email, "Your Content Corpus account is ready",
        `You're in. Sign in at ${process.env.BETTER_AUTH_URL ?? ""}/login to start making videos.`);
    }
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Saved." };
}

/** Whether new accounts wait for approval, and the limit a new member starts with. */
export async function setConfig(_: ActionState, form: FormData): Promise<ActionState> {
  const owner = await requireOwner();
  const parsed = z.object({ approval: z.string().optional().transform((v) => v === "on"), limit: rupees })
    .safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  try {
    await asUser(owner.id, (db) => db.query("select api.admin_set_config($1, $2)",
                                            [parsed.data.approval, parsed.data.limit ?? 0]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Saved." };
}

/** A contact-page message marked read, or unread again. */
export async function markMessage(id: string, read: boolean): Promise<ActionState> {
  const owner = await requireOwner();
  if (!z.string().uuid().safeParse(id).success) return { ok: false, error: "Unknown message." };
  try {
    await asUser(owner.id, (db) => db.query("select api.admin_read_contact_message($1, $2)", [id, read]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}
