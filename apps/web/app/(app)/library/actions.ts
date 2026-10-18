"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { insertFormat, workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { friendly } from "@/lib/errors";
import { requireUser } from "@/lib/session";
import { template, templates } from "@/lib/templates";

import type { ActionState } from "../actions";

export async function createFormat(_: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const name = String(form.get("name") ?? "").trim().slice(0, 60);
  const t = String(form.get("template") ?? "");
  if (!templates().some((x) => x.template_id === t)) return { ok: false, error: "Pick a template." };
  if (!name) return { ok: false, error: "Give the format a name." };
  const { active } = await workspace(user.id);
  let id: string;
  try {
    id = await asUser(user.id, (db) => insertFormat(db, user.id, active.id, name, t, template(t).format));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  redirect(`/library/${id}`);
}

const FormatInput = z.object({
  name: z.string().trim().min(1, "Give the format a name.").max(60),
  description: z.string().trim().max(1000),
  audio_source: z.enum(["kokoro", "ltx_native", "none"]),
  target_seconds: z.coerce.number().int().min(5).max(300),
  visual_style: z.string().trim().max(4000),
  idea_prompt: z.string().trim().min(20, "The idea prompt is empty.").max(20000),
  script_prompt: z.string().trim().min(20, "The script prompt is empty.").max(20000),
});

const HEX = /^#[0-9a-fA-F]{6}$/;

/** The look the owner set, checked against what the template allows (the worker
 *  checks again: templates.clean_params). Empty fields mean "the template's". */
function readParams(form: FormData, templateId: string): Record<string, unknown> | string {
  const t = template(templateId);
  const get = (k: string) => String(form.get(`p_${k}`) ?? "").trim();
  const out: Record<string, unknown> = {};
  const pick = (k: string, ok: (v: string) => boolean, as: (v: string) => unknown = (v) => v) => {
    const v = get(k);
    if (!v) return null;
    if (!ok(v)) return `${k.replace("_", " ")} “${v}” isn't allowed for ${t.display_name}.`;
    out[k] = as(v);
    return null;
  };
  const errors = [
    pick("captions", (v) => ["karaoke", "beats", "kinetic", "speech", "none"].includes(v)),
    pick("transition", (v) => (t.render.transitions ?? ["cut"]).includes(v)),
    pick("layout", (v) => (t.render.layouts ?? ["full"]).includes(v as "full" | "split")),
    pick("font", (v) => ["Montserrat", "Noto Serif"].includes(v)),
    pick("caption_position", (v) => ["top", "middle", "bottom"].includes(v)),
    pick("music_source_mode", (v) => ["licensed_asset", "platform_native", "none"].includes(v)),
    pick("brand_text", (v) => v.length <= 40),
    pick("ai_images", (v) => ["cover", "all", "none"].includes(v)),
    ...["primary_color", "accent_color", "background_color", "panel_color"].map((k) => pick(k, (v) => HEX.test(v))),
    pick("safe_margin_px", (v) => /^\d+$/.test(v) && +v >= 30 && +v <= 160, Number),
    pick("slide_aspect", (v) => !!t.render.slides && ["4:5", "1:1"].includes(v)),
    pick("slide_count", (v) => !!t.render.slides && /^\d+$/.test(v) && +v >= t.render.slides.count[0]
      && +v <= t.render.slides.count[1], Number),
  ].filter(Boolean);
  return errors.length ? (errors[0] as string) : out;
}

export async function updateFormat(formatId: string, templateId: string, _: ActionState,
                                   form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = FormatInput.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const v = parsed.data;
  const t = template(templateId);
  if (t.content_type === "video" && !(t.render.audios ?? []).includes(v.audio_source))
    return { ok: false, error: `${t.display_name} doesn't take that kind of audio.` };
  const params = readParams(form, templateId);
  if (typeof params === "string") return { ok: false, error: params };
  let version: number;
  try {
    version = await asUser(user.id, async (db) => {
      const r = await db.query(
        `update formats set name = $2, description = $3, audio_source = $4, target_seconds = $5,
                visual_style = $6, idea_prompt = $7, script_prompt = $8, params = $9::jsonb
          where id = $1 returning version`,
        [formatId, v.name, v.description, v.audio_source, v.target_seconds,
         v.visual_style, v.idea_prompt, v.script_prompt, JSON.stringify(params)]);
      return r.rows[0]?.version as number;
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: `Saved · version ${version}. New scripts and ideas use it from now on.` };
}

export async function restoreVersion(formatId: string, version: number): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.restore_format_version($1, $2)", [formatId, version]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: `Version ${version} restored.` };
}

export async function makeDefaultFormat(formatId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("select api.set_default_format($1)", [formatId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}

export async function deleteFormat(formatId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    const r = await asUser(user.id, (db) =>
      db.query("delete from formats where id = $1 and not is_default", [formatId]));
    if (!r.rowCount) return { ok: false, error: "The default format can't be deleted — make another one the default first." };
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  redirect("/library?view=formats");
}
