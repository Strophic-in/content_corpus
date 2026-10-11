import "server-only";

import { cookies } from "next/headers";
import type { PoolClient } from "pg";
import { cache } from "react";

import { asUser } from "./db";
import { defaultPrompts, type Source, type Template } from "./prompt-defaults";

export type Channel = {
  id: string; name: string; niche: string; audience: string; voice: string; language: string;
  timezone: string; default_publish_time: string; ideas_daily: boolean; ideas_daily_at: string;
  is_default: boolean;
};

export type Format = {
  id: string; channel_id: string; name: string; description: string; is_default: boolean;
  audio_source: "kokoro" | "ltx_native"; target_seconds: number; idea_prompt: string;
  script_prompt: string; visual_style: string; sources: Source[]; ideas_per_batch: number;
  version: number; updated_at: Date;
};

export type Account = {
  id: string; channel_id: string; platform: "youtube" | "instagram"; external_id: string;
  handle: string | null; display_name: string | null; avatar_url: string | null; status: string;
  token_expires_at: Date | null; connected_at: Date;
};

export const CHANNEL_COOKIE = "cc_channel";

export const CHANNEL_COLS = `id, name, niche, audience, voice, language, timezone,
  to_char(default_publish_time, 'HH24:MI') as default_publish_time, ideas_daily,
  to_char(ideas_daily_at, 'HH24:MI') as ideas_daily_at, is_default`;
export const FORMAT_COLS = `id, channel_id, name, description, is_default, audio_source, target_seconds,
  idea_prompt, script_prompt, visual_style, sources, ideas_per_batch, version, updated_at`;
export const ACCOUNT_COLS = `id, channel_id, platform, external_id, handle, display_name, avatar_url, status,
  token_expires_at, connected_at`;

/** A new format from the shipped defaults (inside the caller's transaction).
 *  `ifMissing`: another request may have just created it — then return null. */
export async function insertFormat(db: PoolClient, userId: string, channelId: string, name: string,
                                   template: Template, description = "", ifMissing = false): Promise<string> {
  const d = defaultPrompts(template);
  const r = await db.query(
    `insert into formats (user_id, channel_id, name, description, audio_source, idea_prompt, script_prompt,
                          visual_style, sources)
     values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
     ${ifMissing ? "on conflict (channel_id, name) do nothing" : ""} returning id`,
    [userId, channelId, name, description, d.audio_source, d.idea_prompt, d.script_prompt, d.visual_style,
     JSON.stringify(d.sources)],
  );
  return r.rows[0]?.id as string;
}

// Every account has a channel, and every channel a default format: the first
// visit creates whatever is missing, from the old settings profile and the
// shipped prompts. A first visit renders several requests at once, so every
// step tolerates another request having just done it (unique names + on conflict).
async function ensureBasics(db: PoolClient, userId: string) {
  const s = (await db.query("select * from api.ensure_settings()")).rows[0];
  const n = (await db.query("select count(*)::int as n from channels")).rows[0].n as number;
  if (!n) {
    await db.query(
      `insert into channels (user_id, name, niche, audience, voice, language, timezone)
       values ($1, $2, $3, $4, $5, $6, $7) on conflict (user_id, name) do nothing`,
      [userId, s.channel_name || "My channel", s.channel_niche ?? "", s.channel_audience ?? "",
       s.channel_voice ?? "", s.script_language || "English", s.timezone || "Asia/Kolkata"],
    );
  }
  if (!(await db.query("select 1 from channels where is_default")).rowCount) {
    const first = await db.query("select id from channels order by created_at limit 1");
    if (first.rows[0]) await db.query("select api.set_default_channel($1)", [first.rows[0].id]);
  }
  const bare = await db.query(
    `select c.id from channels c where not exists (select 1 from formats f where f.channel_id = c.id)`,
  );
  for (const row of bare.rows) {
    const fid = await insertFormat(db, userId, row.id, "3D explainer", "narrated",
      "Narrated 3D-animated explainers: one curiosity question answered in under a minute.", true);
    if (fid) await db.query("select api.set_default_format($1)", [fid]);
  }
}

/** The signed-in user's channels, the active one (cookie, else the default) and its formats. */
export const workspace = cache(async (userId: string) => {
  const wanted = (await cookies()).get(CHANNEL_COOKIE)?.value;
  return asUser(userId, async (db) => {
    await ensureBasics(db, userId);
    const channels = (await db.query(`select ${CHANNEL_COLS} from channels order by is_default desc, name`))
      .rows as Channel[];
    const active = channels.find((c) => c.id === wanted) ?? channels.find((c) => c.is_default) ?? channels[0];
    const formats = (await db.query(
      `select ${FORMAT_COLS} from formats where channel_id = $1 order by is_default desc, name`, [active.id],
    )).rows as Format[];
    return { channels, active, formats };
  });
});

export async function channelAccounts(userId: string, channelId: string): Promise<Account[]> {
  return asUser(userId, async (db) =>
    (await db.query(`select ${ACCOUNT_COLS} from channel_accounts where channel_id = $1 order by platform`,
                    [channelId])).rows as Account[]);
}
