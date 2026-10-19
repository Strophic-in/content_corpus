import "server-only";

import { asUser } from "./db";

export type PostRow = {
  id: string;
  topic: string;
  audio_source: "ltx_native" | "kokoro" | "none";
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
  research_state: "pending" | "ready" | "none" | null;
  music: { name: string; author: string; page: string; mood: string } | null;
  updated_at: Date;
  // A carousel or picture post: its slides (Instagram), and its template.
  format: "reel" | "longform" | "carousel" | "image";
  slides: { key: string; w: number; h: number }[] | null;
  template_id: string | null;
  look_id: string | null;       // the video look of its generated shots, and why
  look_why: string | null;
  // What it goes out with (worker packaging.py): title, caption, first comment, cover.
  package: {
    title: string; hook_line: string; caption: string; hashtags: string[]; first_comment: string;
    thumbnail_text: string; kicker: string; sources: { site: string; title: string; url: string }[];
    thumbnail_key: string; made_at: string;
  } | null;
  packaging: boolean;           // just finished, its package still being written
  voice_id: string | null;      // its narrator voice and style (Jev's pick, or the owner's)
  voice_style: string | null;
  voice_why: string | null;
  caption_preset: string | null;  // its caption style (Jev's pick)
  go_ahead: boolean;            // on its way to a finished reel without stops
  autopilot: boolean;           // and posted at its time (pipeline_mode auto)
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
  shot_plan: { seconds: number; visual: string; audio: string; narration?: string;
               // Footage shots (absent on older scripts: those are all generated).
               source?: "generate" | "clip" | "image" | "stock" | "chart" | "plain"; asset?: number; start?: number;
               end?: number; keep_audio?: boolean; stock_query?: string;
               // On-screen fields (templates): absent on older scripts.
               role?: string; text?: string; label?: string; layout?: string; transition?: string;
               chart?: { kind?: string; title: string; labels: string[]; values: number[]; unit: string } }[];
  slides: { role: string; heading: string; body: string;
            visual: { source: string; asset: number; prompt: string;
                      chart: { kind: string; title: string; labels: string[]; values: number[] } } }[] | null;
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
  voiced: boolean; rendered: boolean; source: "generate" | "clip" | "image" | "stock" | "chart" | "plain";
};
/** Footage a post may use: the accepted idea's own picture or video. */
export type AssetRow = {
  id: string; n: number; kind: "video" | "image"; origin: string; credit: string;
  rights: "needs_review" | "approved" | "rejected"; state: "uploading" | "pending" | "ready" | "failed";
  w: number | null; h: number | null; seconds: string | null; error: string | null; summary: string | null;
  made_from: string | null; has_file: boolean; file_name: string | null; license: string;
  source_url: string | null; role: string | null; entity: string | null; outlet: string | null;
};
export type ResearchInfo = { articles?: { url: string; site: string; title: string; from_idea: boolean }[];
                              unreadable?: { url: string }[] } | null;
export type StatRow = { platform: string; views: number | null; likes: number | null; comments: number | null;
                        fetched_at: Date };
export type EventRow = { id: string; from_state: string | null; to_state: string; actor: string; reason: string | null; at: Date };

// slot_date comes back as a plain YYYY-MM-DD string (never shifted by a JS Date
// timezone), because a calendar day is not an instant.
const POST_COLS = `id, topic, brief, audio_source, to_char(slot_date, 'YYYY-MM-DD') as slot_date,
                   to_char(publish_at at time zone publish_tz, 'HH24:MI') as publish_time, channel_id, format_id, status,
                   target_seconds, auto_approve, approved_script_id, error, final_key,
                   final_duration_s, updated_at, research_state, music, format, slides, look_id, look_why, package, go_ahead, voice_id, voice_style, voice_why, caption_preset, pipeline_mode = 'auto' as autopilot,
                   (package is null and status = 'ready' and updated_at > now() - interval '10 minutes') as packaging,
                   (select f.template_id from formats f where f.id = posts.format_id) as template_id`;

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
                style_prompt, model, review, rejection_note, approved_at, approved_by, created_at, slides
           from scripts where post_id = $1 order by version desc`,
        [id],
      )
    ).rows as ScriptRow[];
    const shots = (
      await db.query(
        `select id, idx, num_frames, fps, seed::text as seed, state, source,
                -- a clip that keeps its own sound has no line to record
                narration_key is not null or coalesce(narration, '') = '' as voiced, state = 'uploaded' as rendered
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
    const assets = (
      await db.query(
        `select id, n, kind, origin, credit, rights, state, w, h, seconds::text, error, made_from,
                key is not null as has_file, file_name, license, source_url,
                coalesce(analysis->>'summary', analysis->'card'->>'summary') as summary,
                fetch_from->'found'->>'role' as role, fetch_from->'found'->>'entity' as entity,
                fetch_from->'found'->>'outlet' as outlet
           from assets where post_id = $1 order by n`,
        [id],
      )
    ).rows as AssetRow[];
    // The sources read for the script (titles and links; their texts stay on the server).
    const research = (await db.query(
      `select coalesce((select jsonb_agg(a - 'text') from jsonb_array_elements(research->'articles') a), '[]') as articles,
              coalesce(research->'unreadable', '[]') as unreadable
         from posts where id = $1`, [id])).rows[0] as ResearchInfo;
    const stats = (await db.query(
      "select platform, views, likes, comments, fetched_at from post_stats where post_id = $1 order by platform",
      [id])).rows as StatRow[];
    const settings = (await db.query("select timezone, default_reel_seconds from app_settings")).rows[0];
    return { post, scripts, shots, events, settings, assets, stats, research };
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
                default_audio_source, narrator_voice, narrator_speed::float8 as narrator_speed,
                pipeline_mode, auto_spend_cap_paise_day, vision_model, usd_inr_override::float8 as usd_inr_override,
                image_model, image_quality
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

/** A post as the Library grid shows it: what it is, how far it got, where it went. */
export type LibraryPost = {
  id: string; title: string; status: string; format: PostRow["format"]; slot_date: string;
  has_video: boolean; has_slides: boolean; seconds: number | null;
  live: { platform: "youtube" | "instagram"; url: string | null }[]; scheduled: boolean;
};

/** Every post of a channel, newest first. */
export async function libraryPosts(userId: string, channelId: string, limit = 300): Promise<LibraryPost[]> {
  return asUser(userId, async (db) => {
    const r = await db.query(
      `select p.id, p.status, p.format, to_char(p.slot_date, 'YYYY-MM-DD') as slot_date,
              coalesce((select s.title from scripts s where s.id = p.approved_script_id),
                       (select s.title from scripts s where s.post_id = p.id order by s.version desc limit 1),
                       p.topic) as title,
              p.final_key is not null as has_video, coalesce(jsonb_array_length(p.slides), 0) > 0 as has_slides,
              round(p.final_duration_s)::int as seconds,
              coalesce((select jsonb_agg(jsonb_build_object('platform', a.platform, 'url', a.remote_url)
                                         order by a.platform)
                          from publish_attempts a where a.post_id = p.id and a.state = 'live'), '[]') as live,
              exists (select 1 from publish_attempts a where a.post_id = p.id and a.state = 'scheduled') as scheduled
         from posts p where p.channel_id = $1
        order by p.slot_date desc, p.created_at desc limit $2`,
      [channelId, limit],
    );
    return r.rows;
  });
}
