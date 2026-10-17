"use server";

import { cookies } from "next/headers";
import { refresh, revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { CHANNEL_COOKIE, starterFormats } from "@/lib/channels";
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

/** From the Discover home: make the channel the active one and show its idea cards. */
export async function openChannel(channelId: string): Promise<void> {
  await switchChannel(channelId);
  redirect(`/discover/${channelId}`);
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
      await starterFormats(db, user.id, r.rows[0].id);
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

/**
 * Delete a channel with everything in it: its posts (a post without a channel is
 * invisible and could never be posted), ideas, categories, formats and connected
 * accounts. Videos already on YouTube or Instagram stay there; the cost history
 * stays; the stored files are swept by the ideas lane. Deleting the default
 * channel makes the oldest other one the default. The last channel can't go.
 */
export async function deleteChannel(channelId: string, back = "/channels"): Promise<ActionState> {
  const user = await requireUser();
  try {
    const outcome = await asUser(user.id, async (db) => {
      const rows = (await db.query("select id, is_default from channels order by created_at")).rows as
        { id: string; is_default: boolean }[];
      const me = rows.find((r) => r.id === channelId);
      if (!me) return "gone";
      if (rows.length < 2) return "last";
      if (me.is_default) {
        await db.query("select api.set_default_channel($1)", [rows.find((r) => r.id !== channelId)!.id]);
      }
      await db.query("delete from posts where channel_id = $1", [channelId]);
      await db.query("delete from channels where id = $1", [channelId]);
      return "deleted";
    });
    if (outcome === "last") return { ok: false, error: "Keep at least one channel." };
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  const jar = await cookies();
  if (jar.get(CHANNEL_COOKIE)?.value === channelId) jar.delete(CHANNEL_COOKIE);
  revalidatePath("/", "layout");            // the header's channel picker lists it too
  redirect(back);
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
