"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { encrypt } from "@/lib/crypto";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";
import { friendly } from "@/lib/errors";
import { textModels } from "@/lib/models";
import { wakeWorker } from "@/lib/wake";

export type ActionState = { ok: boolean; error?: string; message?: string } | null;

const PostInput = z.object({
  slot_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Pick a date."),
  publish_time: z.string().regex(/^\d{2}:\d{2}(:\d{2})?$/, "Pick a time."),
  format_id: z.string().uuid("Pick a format."),
  topic: z.string().trim().min(3, "Give the post a topic.").max(300),
  brief: z.string().trim().max(2000).optional().transform((v) => v || null),
  target_seconds: z
    .union([z.literal(""), z.coerce.number().int().min(5).max(300)])
    .optional()
    .transform((v) => (v === "" || v === undefined ? null : v)),
});

export async function createPost(_: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = PostInput.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const { slot_date, publish_time, format_id, topic, brief, target_seconds } = parsed.data;
  let id: string;
  try {
    id = await asUser(user.id, async (db) => {
      await db.query("select api.ensure_settings()");
      // The post belongs to the format's channel, at that channel's local time, and
      // takes the format's audio style (narrated voice-over or on-screen speech).
      const r = await db.query(
        `insert into posts (user_id, channel_id, format_id, slot_date, publish_tz, publish_at, topic, brief,
                            target_seconds, audio_source)
         select $1, c.id, f.id, $3::date, c.timezone, ($3::date + $4::time) at time zone c.timezone, $5, $6, $7,
                f.audio_source
           from formats f join channels c on c.id = f.channel_id where f.id = $2
         returning id`,
        [user.id, format_id, slot_date, publish_time, topic, brief, target_seconds],
      );
      if (!r.rows[0]) throw Object.assign(new Error("format not found"), { code: "P0002" });
      // Its assets are collected now (logos, the reports, photos, videos), before any script.
      await db.query("select api.collect_assets($1)", [r.rows[0].id]);
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
  const { slot_date, publish_time, format_id, topic, brief, target_seconds } = parsed.data;
  try {
    await asUser(user.id, (db) =>
      db.query(
        `update posts p set slot_date = $2::date, publish_at = ($2::date + $3::time) at time zone p.publish_tz,
                topic = $4, brief = $5, target_seconds = $6, format_id = f.id, audio_source = f.audio_source
           from formats f where p.id = $1 and f.id = $7`,
        [postId, slot_date, publish_time, topic, brief, target_seconds, format_id],
      ),
    );
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Saved." };
}

/** A post to another day (the calendar's drag and drop): its time of day is kept, and
 *  a scheduled post's publishing moves with it. */
export async function movePost(postId: string, date: string): Promise<ActionState> {
  const user = await requireUser();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return { ok: false, error: "Pick a day." };
  try {
    await asUser(user.id, (db) => db.query("select api.move_post($1, $2::date)", [postId, date]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}

export async function deletePost(postId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    const r = await asUser(user.id, (db) => db.query("delete from posts where id = $1", [postId]));
    if (r.rowCount === 0) return { ok: false, error: "A post being rendered, scheduled or posted can't be deleted." };
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

/** Autopilot for one post: written, approved, rendered and posted at its time, no stops. */
export async function setAutopilot(postId: string, on: boolean): Promise<ActionState> {
  const user = await requireUser();
  let what = "";
  try {
    what = await asUser(user.id, async (db) =>
      (await db.query("select api.autopilot($1, $2) as r", [postId, on])).rows[0]?.r as string);
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  if (on) await wakeWorker();
  refresh();
  return { ok: true, message: on ? `Autopilot on — ${what}.` : "Autopilot off — it waits for you." };
}

/** Write a finished reel's title, caption, first comment and cover again. */
export async function requestPackage(postId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.request_package($1)", [postId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true, message: "Writing it again — it'll be here in a minute." };
}

/** Allow or withdraw one piece of a post's footage. Withdrawn footage is never shown:
 *  rendering refuses a script that uses it (write a new one). */
export async function setAssetRights(assetId: string, allowed: boolean): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("update assets set rights = $2 where id = $1",
                                           [assetId, allowed ? "approved" : "rejected"]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}

const PublishInput = z.object({
  platforms: z.array(z.enum(["youtube", "instagram"])).min(1, "Choose where to post it."),
  // Wall-clock time in the post's timezone (a datetime-local value); none = now.
  at: z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/, "Pick a date and time.").nullable(),
  youtube_privacy: z.enum(["private", "unlisted", "public"]).nullable(),
});

/** Post a finished reel now, or schedule it, to the chosen platforms. */
export async function requestPublish(postId: string, input: z.input<typeof PublishInput>): Promise<ActionState> {
  const user = await requireUser();
  const parsed = PublishInput.safeParse(input);
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const { platforms, at, youtube_privacy } = parsed.data;
  try {
    await asUser(user.id, (db) => db.query(
      `select api.request_publish($1, $2::text[],
                                  (select $3::timestamp at time zone publish_tz from posts where id = $1), $4)`,
      [postId, platforms, at, youtube_privacy]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true };
}

/** A scheduled post goes out now, on one platform or on every one it is scheduled for. */
export async function publishNow(postId: string, platform?: "youtube" | "instagram"): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.publish_now($1, $2)", [postId, platform ?? null]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true, message: "Posting now." };
}

export async function cancelPublish(postId: string, platform: "youtube" | "instagram"): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.cancel_publish($1, $2)", [postId, platform]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
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

// Account-wide settings. A channel's profile, timezone and posting time are on
// its channel; a kind of video's length, audio style and prompts on its format.
const SettingsInput = z.object({
  script_model: z.string().trim().max(120),
  youtube_privacy: z.enum(["private", "unlisted", "public"]),
  narrator_voice: z.enum(["am_michael", "am_fenrir", "am_onyx", "bm_george", "bm_lewis", "af_heart", "af_bella", "bf_emma"]),
  narrator_speed: z.coerce.number().min(0.7).max(1.5),
  auto_approve: z.string().optional().transform((v) => v === "on"),
  pipeline_mode: z.enum(["manual", "auto"]),
  // Rupees a day automatic renders may spend; empty = no limit.
  auto_spend_cap: z.union([z.literal(""), z.coerce.number().min(0).max(100000)]).optional()
    .transform((v) => (v === "" || v === undefined ? null : Math.round(v * 100))),
  vision_model: z.string().trim().max(120),
  image_model: z.string().trim().max(120).optional(),
  image_quality: z.enum(["low", "medium", "high"]).optional(),
  max_gpu_shots: z.coerce.number().int().min(0).max(12),
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
        `update app_settings set script_model = nullif($1, ''), youtube_privacy = $2, auto_approve = $3,
                narrator_voice = $4, narrator_speed = $5, pipeline_mode = $6, auto_spend_cap_paise_day = $7,
                vision_model = nullif($8, ''), image_model = coalesce(nullif($9, ''), image_model),
                image_quality = coalesce($10, image_quality), max_gpu_shots = $11`,
        [v.script_model, v.youtube_privacy, v.auto_approve, v.narrator_voice, v.narrator_speed,
         v.pipeline_mode, v.auto_spend_cap, v.vision_model, v.image_model ?? "", v.image_quality ?? null,
         v.max_gpu_shots],
      );
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Settings saved." };
}

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
    models = body.data.map((m) => m.id).sort();             // all of them; each menu filters (lib/models.ts)
  } catch (err) {
    console.warn("openai key check failed: network", (err as Error)?.name);
    return { ok: false, error: "Couldn't reach OpenAI to check the key." };
  }
  if (!textModels(models).length) {
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


// ── costs and optional keys ──────────────────────────────────────────────────

const Price = z.union([z.literal(""), z.coerce.number().min(0).max(1000)]).transform((v) => (v === "" ? null : v));

/** The owner's price for each model (USD per 1M tokens; per image), and the rate override. */
export async function savePrices(_: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const models = form.getAll("model").map(String);
  const rows: { model: string; input: number | null; cached: number | null; output: number | null; image: number | null }[] = [];
  for (const [i, model] of models.entries()) {
    const parsed = z.object({ input: Price, cached: Price, output: Price, image: Price }).safeParse({
      input: form.getAll("input")[i], cached: form.getAll("cached")[i], output: form.getAll("output")[i],
      image: form.getAll("image")[i],
    });
    if (!parsed.success) return { ok: false, error: `${model}: prices must be numbers.` };
    rows.push({ model: model.slice(0, 100), ...parsed.data, image: parsed.data.image });
  }
  const fx = z.union([z.literal(""), z.coerce.number().min(1).max(1000)]).safeParse(form.get("usd_inr") ?? "");
  if (!fx.success) return { ok: false, error: "The exchange rate must be rupees per dollar, like 84.5." };
  try {
    await asUser(user.id, async (db) => {
      for (const r of rows) {
        if (r.input == null && r.output == null && r.cached == null && r.image == null) {
          await db.query("delete from prices where model = $1", [r.model]);
        } else {
          await db.query(
            `insert into prices (user_id, model, input_per_m, cached_input_per_m, output_per_m, per_image, updated_at)
             values ($1, $2, $3, $4, $5, $6, now())
             on conflict (user_id, model) do update set input_per_m = $3, cached_input_per_m = $4,
                    output_per_m = $5, per_image = $6, updated_at = now()`,
            [user.id, r.model, r.input, r.cached, r.output, r.image]);
        }
      }
      await db.query("update app_settings set usd_inr_override = $1", [fx.data === "" ? null : fx.data]);
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Saved. New charges use these prices; past ones keep theirs." };
}

/** Reddit's API keys (only after Reddit approves the app). Write-only, like the OpenAI key. */
export async function saveRedditKeys(_: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const id = String(form.get("client_id") ?? "").trim();
  const secret = String(form.get("client_secret") ?? "").trim();
  if (form.get("remove") === "1") {
    await asUser(user.id, (db) => db.query(
      "delete from user_keys where name in ('reddit_client_id', 'reddit_client_secret')"));
    refresh();
    return { ok: true, message: "Removed — Reddit is read through its public feeds again." };
  }
  if (!/^[\w-]{10,40}$/.test(id) || !/^[\w-]{20,60}$/.test(secret))
    return { ok: false, error: "Paste the app's client id and secret from reddit.com/prefs/apps." };
  try {
    await asUser(user.id, async (db) => {
      for (const [name, value] of [["reddit_client_id", id], ["reddit_client_secret", secret]]) {
        await db.query(
          `insert into user_keys (user_id, name, ciphertext, updated_at) values ($1, $2, $3, now())
           on conflict (user_id, name) do update set ciphertext = $3, updated_at = now()`,
          [user.id, name, encrypt(value)]);
      }
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Saved. The ideas worker uses Reddit's API from its next batch." };
}

// Keys for other services, write-only like the OpenAI key: a YouTube Data API key
// (a Google Cloud API key) for trending-chart sources, a Pexels key for stock video.
const SERVICE_KEYS = {
  youtube: { name: "youtube_api_key", shape: /^AIza[0-9A-Za-z_-]{35}$/,
             wrong: "That isn't a Google API key (they start with AIza and are 39 characters).",
             saved: "Saved. YouTube trending sources work from the next batch.",
             removed: "Removed — YouTube trending sources will pause." },
  freesound: { name: "freesound_api_key", shape: /^[A-Za-z0-9]{20,64}$/,
               wrong: "That doesn't look like a Freesound API key (letters and digits, from freesound.org/apiv2/apply).",
               saved: "Saved. New scripts pick a mood, and the reel gets a CC0 track.",
               removed: "Removed — no background music." },
  jev: { name: "jev_api_key", shape: /^[A-Za-z0-9._-]{20,200}$/,
         wrong: "That doesn't look like a TypeSafe API key (from console.typesafe.ai).",
         saved: "Saved and checked with Jev.",
         removed: "Removed — decisions go back to the OpenAI model." },
  pexels: { name: "pexels_api_key", shape: /^[A-Za-z0-9]{30,100}$/,
            wrong: "That doesn't look like a Pexels API key (letters and digits, from pexels.com/api).",
            saved: "Saved. New scripts may use stock video.",
            removed: "Removed — new scripts won't use stock video." },
} as const;
export type ServiceKey = keyof typeof SERVICE_KEYS;

export async function saveServiceKey(service: ServiceKey, _: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const k = SERVICE_KEYS[service];
  if (form.get("remove") === "1") {
    await asUser(user.id, (db) => db.query("delete from user_keys where name = $1", [k.name]));
    refresh();
    return { ok: true, message: k.removed };
  }
  const key = String(form.get("key") ?? "").trim();
  if (!k.shape.test(key)) return { ok: false, error: k.wrong };
  if (service === "jev") {
    // One tiny decision (a fraction of a paisa) proves the key works before it is stored.
    try {
      const r = await fetch("https://api.typesafe.ai/v1/systemone", {
        method: "POST", signal: AbortSignal.timeout(15_000),
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model: "jev-latest", state: "The sky is blue.",
                               questions: { ok: { type: "noul", instructions: "Is this sentence about the sky?" } } }),
      });
      if (r.status === 401 || r.status === 403) return { ok: false, error: "TypeSafe rejected this key." };
      if (!r.ok) console.warn(`jev key check: HTTP ${r.status}`);
    } catch (err) {
      console.warn("jev key check failed: network", (err as Error)?.name);
    }
  }
  try {
    await asUser(user.id, (db) => db.query(
      `insert into user_keys (user_id, name, ciphertext, updated_at) values ($1, $2, $3, now())
       on conflict (user_id, name) do update set ciphertext = $3, updated_at = now()`,
      [user.id, k.name, encrypt(key)]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: k.saved };
}

/** Re-read which models the stored key can use (the ideas worker does it: the web
 *  can't read the key back). Daily it happens by itself. */
export async function refreshModels(): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.refresh_openai_models()"));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  return { ok: true, message: "Asking OpenAI for the list…" };
}

// ── the owner's own footage ──────────────────────────────────────────────────

const VIDEO_EXT = ["mp4", "mov", "m4v", "webm"];
const IMAGE_EXT = ["jpg", "jpeg", "png", "webp"];

/** Make room for one upload (an asset row and its storage); the browser then PUTs
 *  the file to /api/upload/<assetId>. */
export async function startUpload(postId: string, name: string, bytes: number,
                                  type: string): Promise<ActionState & { assetId?: string }> {
  const user = await requireUser();
  const ext = (name.split(".").pop() ?? "").toLowerCase();
  const kind = type.startsWith("video/") || VIDEO_EXT.includes(ext) ? "video"
    : type.startsWith("image/") || IMAGE_EXT.includes(ext) ? "image" : null;
  if (!kind || ![...VIDEO_EXT, ...IMAGE_EXT].includes(ext))
    return { ok: false, error: `${name}: use MP4, MOV or WebM video, or JPEG, PNG or WebP pictures.` };
  if (!Number.isInteger(bytes) || bytes <= 0) return { ok: false, error: `${name} is empty.` };
  try {
    const assetId = await asUser(user.id, async (db) =>
      (await db.query("select (api.start_upload($1, $2, $3, $4, $5)).id", [postId, kind, bytes, ext, name.slice(0, 200)]))
        .rows[0].id as string);
    return { ok: true, assetId };
  } catch (err) {
    return { ok: false, error: `${name}: ${friendly(err)}` };
  }
}

/** A link the owner pastes — a picture, a video page or an article — as one of the post's assets. */
export async function addAssetLink(postId: string, url: string, kind: "auto" | "image" | "video"): Promise<ActionState> {
  const user = await requireUser();
  if (!/^https?:\/\/\S+\.\S+$/i.test(url.trim())) return { ok: false, error: "Paste a full link, starting with https://" };
  try {
    await asUser(user.id, (db) => db.query("select api.add_asset_link($1, $2, $3)", [postId, url.trim(), kind]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true };
}

/** Collect (again) the post's logos, report cards, photos and videos. */
export async function collectAssets(postId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.collect_assets($1)", [postId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true };
}

export async function deleteUpload(assetId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.delete_upload($1)", [assetId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}
