"use server";

import { cookies } from "next/headers";
import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { CHANNEL_COOKIE, insertFormat } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";

import { friendly } from "@/lib/errors";

import type { ActionState } from "./actions";

/** Which channel the app shows: a cookie, checked against the user's channels. */
export async function switchChannel(channelId: string): Promise<void> {
  const user = await requireUser();
  const ok = await asUser(user.id, async (db) =>
    (await db.query("select 1 from channels where id = $1", [channelId])).rowCount === 1);
  if (!ok) return;
  (await cookies()).set(CHANNEL_COOKIE, channelId, { httpOnly: true, sameSite: "lax", secure: true, path: "/",
                                                     maxAge: 60 * 60 * 24 * 365 });
}

const ChannelInput = z.object({
  name: z.string().trim().min(1, "Give the channel a name.").max(80),
  niche: z.string().trim().max(500),
  audience: z.string().trim().max(500),
  voice: z.string().trim().max(500),
  language: z.string().trim().min(2).max(40),
  timezone: z.string().trim().min(3).max(64),
  default_publish_time: z.string().regex(/^\d{2}:\d{2}(:\d{2})?$/, "Pick a time."),
  ideas_daily_at: z.string().regex(/^\d{2}:\d{2}(:\d{2})?$/, "Pick a time."),
  ideas_daily: z.string().optional().transform((v) => v === "on"),
});

export async function createChannel(_: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = ChannelInput.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const v = parsed.data;
  let id: string;
  try {
    id = await asUser(user.id, async (db) => {
      const r = await db.query(
        `insert into channels (user_id, name, niche, audience, voice, language, timezone, default_publish_time,
                               ideas_daily, ideas_daily_at)
         values ($1, $2, $3, $4, $5, $6, $7, $8::time, $9, $10::time) returning id`,
        [user.id, v.name, v.niche, v.audience, v.voice, v.language, v.timezone, v.default_publish_time,
         v.ideas_daily, v.ideas_daily_at],
      );
      const fid = await insertFormat(db, user.id, r.rows[0].id, "3D explainer", "narrated",
        "Narrated 3D-animated explainers: one curiosity question answered in under a minute.");
      await db.query("select api.set_default_format($1)", [fid]);
      return r.rows[0].id as string;
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await switchChannel(id);
  redirect(`/channels/${id}`);
}

export async function updateChannel(channelId: string, _: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = ChannelInput.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const v = parsed.data;
  try {
    await asUser(user.id, (db) => db.query(
      `update channels set name = $2, niche = $3, audience = $4, voice = $5, language = $6, timezone = $7,
              default_publish_time = $8::time, ideas_daily = $9, ideas_daily_at = $10::time, updated_at = now()
        where id = $1`,
      [channelId, v.name, v.niche, v.audience, v.voice, v.language, v.timezone, v.default_publish_time,
       v.ideas_daily, v.ideas_daily_at]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Saved." };
}

export async function makeDefaultChannel(channelId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.set_default_channel($1)", [channelId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}

export async function deleteChannel(channelId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    const left = await asUser(user.id, async (db) => {
      const n = (await db.query("select count(*)::int as n from channels")).rows[0].n as number;
      if (n < 2) return false;
      await db.query("delete from channels where id = $1 and not is_default", [channelId]);
      return true;
    });
    if (!left) return { ok: false, error: "Keep at least one channel." };
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  redirect("/channels");
}

export async function disconnectAccount(accountId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("delete from channel_accounts where id = $1", [accountId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}
