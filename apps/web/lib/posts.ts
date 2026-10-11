import "server-only";

import { asUser } from "./db";

export type PostRow = {
  id: string;
  topic: string;
  audio_source: "ltx_native" | "kokoro";
  brief: string | null;
  slot_date: string; // YYYY-MM-DD
  publish_time: string | null; // HH:MM in the post's timezone
  channel_id: string | null;
  format_id: string | null;
  status: string;
  target_seconds: number | null;
  auto_approve: boolean;
  approved_script_id: string | null;
  error: { stage?: string; message?: string } | null;
  final_key: string | null;
  final_duration_s: string | null;
  updated_at: Date;
};

export type ScriptRow = {
  id: string;
  version: number;
  state: string;
  title: string | null;
  hook: string | null;
  description: string | null;
  hashtags: string[];
  intended_dialogue: string;
  shot_plan: { seconds: number; visual: string; audio: string; narration?: string }[];
  style_prompt: string | null;
  model: string | null;
  review: { score: number; risks: string[]; notes: string } | null;
  rejection_note: string | null;
  approved_at: Date | null;
  approved_by: string | null;
  created_at: Date;
};

export type ShotRow = {
  id: string; idx: number; num_frames: number; fps: number; seed: string; state: string;
  voiced: boolean; rendered: boolean;
};
export type EventRow = { id: string; from_state: string | null; to_state: string; actor: string; reason: string | null; at: Date };

// slot_date comes back as a plain YYYY-MM-DD string (never shifted by a JS Date
// timezone), because a calendar day is not an instant.
const POST_COLS = `id, topic, brief, audio_source, to_char(slot_date, 'YYYY-MM-DD') as slot_date,
                   to_char(publish_at at time zone publish_tz, 'HH24:MI') as publish_time, channel_id, format_id, status,
                   target_seconds, auto_approve, approved_script_id, error, final_key,
                   final_duration_s, updated_at`;

export async function postsBetween(userId: string, channelId: string, from: string, to: string): Promise<PostRow[]> {
  return asUser(userId, async (db) => {
    const r = await db.query(
      `select ${POST_COLS} from posts where channel_id = $3 and slot_date between $1 and $2
        order by slot_date, publish_at nulls last, created_at`,
      [from, to, channelId],
    );
    return r.rows;
  });
}

export async function postDetail(userId: string, id: string) {
  return asUser(userId, async (db) => {
    const post = (await db.query(`select ${POST_COLS} from posts where id = $1`, [id])).rows[0] as
      | PostRow
      | undefined;
    if (!post) return null;
    const scripts = (
      await db.query(
        `select id, version, state, title, hook, description, hashtags, intended_dialogue, shot_plan,
                style_prompt, model, review, rejection_note, approved_at, approved_by, created_at
           from scripts where post_id = $1 order by version desc`,
        [id],
      )
    ).rows as ScriptRow[];
    const shots = (
      await db.query(
        `select id, idx, num_frames, fps, seed::text as seed, state,
                narration_key is not null as voiced, state = 'uploaded' as rendered
           from shots where post_id = $1 and script_id = $2 order by idx`,
        [id, post.approved_script_id],
      )
    ).rows as ShotRow[];
    const events = (
      await db.query(
        `select id::text as id, from_state, to_state, actor, reason, at
           from post_events where post_id = $1 order by at desc, id desc limit 30`,
        [id],
      )
    ).rows as EventRow[];
    const settings = (await db.query("select timezone, default_reel_seconds from app_settings")).rows[0];
    return { post, scripts, shots, events, settings };
  });
}

export async function userSettings(userId: string) {
  return asUser(userId, async (db) => {
    await db.query("select api.ensure_settings()");
    const s = (
      await db.query(
        `select timezone, auto_approve, default_publish_time::text as default_publish_time,
                youtube_privacy, channel_name, channel_niche, channel_audience, channel_voice,
                script_language, default_reel_seconds, script_model, openai_models,
                default_audio_source, narrator_voice, narrator_speed::float8 as narrator_speed
           from app_settings`,
      )
    ).rows[0];
    const keys = (await db.query("select name, updated_at from user_keys order by name")).rows as {
      name: string;
      updated_at: Date;
    }[];
    return { settings: s, keys };
  });
}
