import "server-only";

import { cookies } from "next/headers";
import type { PoolClient } from "pg";
import { cache } from "react";

import { asUser } from "./db";
import { defaultPrompts, type Source } from "./prompt-defaults";
import { templateDefaults, type ContentType } from "./templates";

export type Channel = {
  id: string; name: string; niche: string; audience: string; voice: string; language: string;
  timezone: string; default_publish_time: string; ideas_daily: boolean; ideas_daily_at: string;
  daily_auto_post: boolean; daily_pick_at: string; daily_auto_count: number;
  // When daily ideas are paused: "forever" (until resumed), or when they start again; null = not paused.
  ideas_paused: string | null;
  video_look: string;     // "auto", "format" or a look id (lib/looks.ts)
  is_default: boolean;
};

export type Format = {
  id: string; channel_id: string; name: string; description: string; is_default: boolean;
  audio_source: "kokoro" | "ltx_native" | "none"; target_seconds: number; idea_prompt: string;
  script_prompt: string; visual_style: string; sources: Source[]; ideas_per_batch: number;
  version: number; updated_at: Date; template_id: string; content_type: ContentType;
  params: Record<string, unknown>;
};

export type Account = {
  id: string; channel_id: string; platform: "youtube" | "instagram"; external_id: string;
  handle: string | null; display_name: string | null; avatar_url: string | null; status: string;
  token_expires_at: Date | null; connected_at: Date;
};

export const CHANNEL_COOKIE = "cc_channel";

export const CHANNEL_COLS = `id, name, niche, audience, voice, language, timezone,
  to_char(default_publish_time, 'HH24:MI') as default_publish_time, ideas_daily,
  to_char(ideas_daily_at, 'HH24:MI') as ideas_daily_at, is_default, video_look,
  daily_auto_post, to_char(daily_pick_at, 'HH24:MI') as daily_pick_at, daily_auto_count,
  case when ideas_paused_until = 'infinity' then 'forever'
       when ideas_paused_until > now() then to_char(ideas_paused_until at time zone timezone, 'Dy DD Mon, HH24:MI')
  end as ideas_paused`;
export const FORMAT_COLS = `id, channel_id, name, description, is_default, audio_source, target_seconds,
  idea_prompt, script_prompt, visual_style, sources, ideas_per_batch, version, updated_at, template_id,
  content_type, params`;
export const ACCOUNT_COLS = `id, channel_id, platform, external_id, handle, display_name, avatar_url, status,
  token_expires_at, connected_at`;

// The names formats were made from before templates.
const LEGACY: Record<string, string> = {
  narrated: "cinematic_3d_explainer", dialogue: "character_dialogue", news: "mini_news_explainer",
};

/** A new format of a template, from its shipped prompts (inside the caller's
 *  transaction). `ifMissing`: another request may have just created it — then null. */
export async function insertFormat(db: PoolClient, userId: string, channelId: string, name: string,
                                   templateId: string, description = "", ifMissing = false): Promise<string> {
  const id = LEGACY[templateId] ?? templateId;
  const d = templateDefaults(id);
  const r = await db.query(
    `insert into formats (user_id, channel_id, name, description, audio_source, idea_prompt, script_prompt,
                          visual_style, sources, template_id, target_seconds)
     values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
     ${ifMissing ? "on conflict (channel_id, name) do nothing" : ""} returning id`,
    [userId, channelId, name, description, d.audio_source, d.idea_prompt, d.script_prompt, d.visual_style,
     JSON.stringify(defaultPrompts("narrated").sources), id, d.target_seconds],
  );
  return r.rows[0]?.id as string;
}

/** What every new channel starts with: a narrated explainer (its default), a
 *  carousel and a picture card. */
export async function starterFormats(db: PoolClient, userId: string, channelId: string): Promise<void> {
  const fid = await insertFormat(db, userId, channelId, "3D explainer", "cinematic_3d_explainer",
    "Narrated 3D-animated explainers: one curiosity question answered in under a minute.", true);
  if (fid) await db.query("select api.set_default_format($1)", [fid]);
  await insertFormat(db, userId, channelId, "Carousel", "educational_carousel",
    "Swipeable slides: a cover hook, one idea per slide, a summary.", true);
  await insertFormat(db, userId, channelId, "Picture card", "picture_above_text_below",
    "One picture on top, a bold headline and a few lines below.", true);
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
  for (const row of bare.rows) await starterFormats(db, userId, row.id);
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
