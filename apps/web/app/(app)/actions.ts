"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { encrypt } from "@/lib/crypto";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";
import { wakeWorker } from "@/lib/wake";

export type ActionState = { ok: boolean; error?: string; message?: string } | null;

// Postgres errors the UI can explain. Anything else is logged and reported
// generically — never echo raw SQL errors to the page.
function friendly(err: unknown): string {
  const e = err as { code?: string; message?: string; constraint?: string };
  if (e?.code === "23505" && e.constraint === "posts_user_id_slot_date_key")
    return "You already have a post on that day — one post per day.";
  if (e?.code === "P0002") return "That item no longer exists.";
  if (e?.code === "55000" && e.message) return e.message.charAt(0).toUpperCase() + e.message.slice(1) + ".";
  if (e?.code === "42501") {
    console.error("action refused by database permissions:", e.message);
    return "The database refused that change — it isn't allowed in the current state.";
  }
  if (e?.code === "23514") return "One of the values is out of range.";
  console.error("action failed", err);
  return "Something went wrong. Please try again.";
}

const PostInput = z.object({
  slot_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Pick a date."),
  topic: z.string().trim().min(3, "Give the post a topic.").max(300),
  brief: z.string().trim().max(2000).optional().transform((v) => v || null),
  target_seconds: z
    .union([z.literal(""), z.coerce.number().int().min(5).max(90)])
    .optional()
    .transform((v) => (v === "" || v === undefined ? null : v)),
});

export async function createPost(_: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = PostInput.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const { slot_date, topic, brief, target_seconds } = parsed.data;
  let id: string;
  try {
    id = await asUser(user.id, async (db) => {
      await db.query("select api.ensure_settings()");
      // New posts take the channel's audio style (narrated voice-over or on-screen speech).
      const r = await db.query(
        `insert into posts (user_id, slot_date, topic, brief, target_seconds, audio_source)
         values ($1, $2, $3, $4, $5, (select default_audio_source from app_settings)) returning id`,
        [user.id, slot_date, topic, brief, target_seconds],
      );
      return r.rows[0].id as string;
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  redirect(`/posts/${id}`);
}

export async function updatePost(postId: string, _: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = PostInput.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const { slot_date, topic, brief, target_seconds } = parsed.data;
  try {
    await asUser(user.id, (db) =>
      db.query(
        `update posts set slot_date = $2, topic = $3, brief = $4, target_seconds = $5 where id = $1`,
        [postId, slot_date, topic, brief, target_seconds],
      ),
    );
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Saved." };
}

export async function deletePost(postId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    const r = await asUser(user.id, (db) => db.query("delete from posts where id = $1", [postId]));
    if (r.rowCount === 0) return { ok: false, error: "This post can't be deleted in its current state." };
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  redirect("/calendar");
}

export async function generateScript(postId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.generate_script($1)", [postId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true };
}

export async function approveScript(scriptId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.approve_script($1)", [scriptId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true };
}

export async function requestRender(postId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    // Called once per click; the database refuses a second render of the same script.
    await asUser(user.id, (db) => db.query("select api.request_render($1)", [postId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true };
}

export async function rejectScript(scriptId: string, _: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const note = String(form.get("note") ?? "").trim().slice(0, 1000) || null;
  try {
    await asUser(user.id, (db) => db.query("select api.reject_script($1, $2)", [scriptId, note]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}

// ── settings ────────────────────────────────────────────────────────────────

const SettingsInput = z.object({
  channel_name: z.string().trim().max(120),
  channel_niche: z.string().trim().max(500),
  channel_audience: z.string().trim().max(500),
  channel_voice: z.string().trim().max(500),
  script_language: z.string().trim().min(2).max(40),
  default_reel_seconds: z.coerce.number().int().min(5).max(90),
  script_model: z.string().trim().max(120),
  timezone: z.string().trim().min(3).max(64),
  default_publish_time: z.string().regex(/^\d{2}:\d{2}(:\d{2})?$/),
  youtube_privacy: z.enum(["private", "unlisted", "public"]),
  default_audio_source: z.enum(["kokoro", "ltx_native"]),
  narrator_voice: z.enum(["am_michael", "am_fenrir", "am_onyx", "bm_george", "bm_lewis", "af_heart", "af_bella", "bf_emma"]),
  narrator_speed: z.coerce.number().min(0.7).max(1.5),
  auto_approve: z.string().optional().transform((v) => v === "on"),
});

export async function saveSettings(_: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = SettingsInput.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const v = parsed.data;
  try {
    await asUser(user.id, async (db) => {
      await db.query("select api.ensure_settings()");
      await db.query(
        `update app_settings set channel_name = $1, channel_niche = $2, channel_audience = $3,
                channel_voice = $4, script_language = $5, default_reel_seconds = $6,
                script_model = nullif($7, ''), timezone = $8, default_publish_time = $9::time,
                youtube_privacy = $10, auto_approve = $11, default_audio_source = $12,
                narrator_voice = $13, narrator_speed = $14`,
        [v.channel_name || null, v.channel_niche || null, v.channel_audience || null,
         v.channel_voice || null, v.script_language, v.default_reel_seconds, v.script_model,
         v.timezone, v.default_publish_time, v.youtube_privacy, v.auto_approve,
         v.default_audio_source, v.narrator_voice, v.narrator_speed],
      );
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Settings saved." };
}

// Models we will never offer for script writing: they are not text-in/text-out.
const NOT_FOR_SCRIPTS = /(embed|tts|whisper|transcribe|audio|realtime|dall-e|image|moderation|search|computer-use|codex)/i;

/**
 * Store the OpenAI key — but only after OpenAI accepts it. Listing models is a
 * free call that proves the key works, and its answer becomes the model menu, so
 * the settings page never offers a model this key cannot use.
 */
export async function saveOpenAIKey(_: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const key = String(form.get("openai_key") ?? "").trim();
  if (!/^sk-[\w-]{20,}$/.test(key)) {
    console.warn("openai key check failed: not in sk-… format");
    return { ok: false, error: "That doesn't look like an OpenAI API key (sk-…)." };
  }

  let models: string[];
  try {
    const r = await fetch("https://api.openai.com/v1/models", {
      headers: { Authorization: `Bearer ${key}` },
      signal: AbortSignal.timeout(15_000),
    });
    if (!r.ok) {
      // Status only — never the key — so a failed save can be diagnosed from the server log.
      console.warn(`openai key check failed: HTTP ${r.status}`);
      if (r.status === 401)
        return { ok: false, error: "OpenAI rejected this key. Check it is an OpenAI key (not OpenRouter or another service) and that it hasn't been revoked." };
      if (r.status === 403)
        return { ok: false, error: "This key isn't allowed to list models. In OpenAI → API keys, give it “Models: Read” (and “Model capabilities: Write”), or use a key with All permissions." };
      if (r.status === 429)
        return { ok: false, error: "OpenAI says this key has no quota left — check billing on the key's project." };
      return { ok: false, error: `OpenAI answered ${r.status}; try again in a moment.` };
    }
    const body = (await r.json()) as { data: { id: string }[] };
    models = body.data.map((m) => m.id).filter((id) => !NOT_FOR_SCRIPTS.test(id)).sort();
  } catch (err) {
    console.warn("openai key check failed: network", (err as Error)?.name);
    return { ok: false, error: "Couldn't reach OpenAI to check the key." };
  }
  if (!models.length) {
    console.warn("openai key check failed: no text models listed");
    return { ok: false, error: "This key has no text models available." };
  }

  try {
    await asUser(user.id, async (db) => {
      await db.query("select api.ensure_settings()");
      await db.query(
        // Set from the parameter, not `excluded.ciphertext`: reading EXCLUDED needs SELECT on
        // that column, which the web role deliberately lacks (the vault is write-only).
        `insert into user_keys (user_id, name, ciphertext, updated_at) values ($1, 'openai', $2, now())
         on conflict (user_id, name) do update set ciphertext = $2, updated_at = now()`,
        [user.id, encrypt(key)],
      );
      // Keep the chosen model if it is still available; otherwise leave it for
      // the owner to pick rather than guessing on their behalf.
      await db.query(
        `update app_settings set openai_models = $1,
                script_model = case when script_model = any($1) then script_model else null end`,
        [models],
      );
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: `Key saved. ${models.length} models available — choose one below.` };
}
