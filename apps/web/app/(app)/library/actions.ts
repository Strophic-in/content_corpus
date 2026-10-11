"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { insertFormat, workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { friendly } from "@/lib/errors";
import { requireUser } from "@/lib/session";

import type { ActionState } from "../actions";

export async function createFormat(_: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const name = String(form.get("name") ?? "").trim().slice(0, 60);
  const template = form.get("template") === "dialogue" ? "dialogue" : "narrated";
  if (!name) return { ok: false, error: "Give the format a name." };
  const { active } = await workspace(user.id);
  let id: string;
  try {
    id = await asUser(user.id, (db) => insertFormat(db, user.id, active.id, name, template));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  redirect(`/library/${id}`);
}

const Source = z.object({ name: z.string().trim().min(1).max(80), url: z.string().trim().url().max(500) });

const FormatInput = z.object({
  name: z.string().trim().min(1, "Give the format a name.").max(60),
  description: z.string().trim().max(1000),
  audio_source: z.enum(["kokoro", "ltx_native"]),
  target_seconds: z.coerce.number().int().min(5).max(300),
  ideas_per_batch: z.coerce.number().int().min(1).max(30),
  visual_style: z.string().trim().max(4000),
  idea_prompt: z.string().trim().min(20, "The idea prompt is empty.").max(20000),
  script_prompt: z.string().trim().min(20, "The script prompt is empty.").max(20000),
  // One source per line: "Name | https://…" (or just the URL).
  sources: z.string().max(10000).transform((text, ctx) => {
    const out: { name: string; url: string }[] = [];
    for (const raw of text.split("\n").map((l) => l.trim()).filter(Boolean)) {
      const [a, b] = raw.includes("|") ? raw.split("|").map((s) => s.trim()) : [raw, raw];
      const r = Source.safeParse({ name: b ? a : a, url: b || a });
      if (!r.success) {
        ctx.addIssue({ code: "custom", message: `Not a valid source line: “${raw.slice(0, 60)}”` });
        return z.NEVER;
      }
      out.push(r.data);
    }
    return out;
  }),
});

export async function updateFormat(formatId: string, _: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = FormatInput.safeParse(Object.fromEntries(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const v = parsed.data;
  let version: number;
  try {
    version = await asUser(user.id, async (db) => {
      const r = await db.query(
        `update formats set name = $2, description = $3, audio_source = $4, target_seconds = $5,
                ideas_per_batch = $6, visual_style = $7, idea_prompt = $8, script_prompt = $9, sources = $10
          where id = $1 returning version`,
        [formatId, v.name, v.description, v.audio_source, v.target_seconds, v.ideas_per_batch,
         v.visual_style, v.idea_prompt, v.script_prompt, JSON.stringify(v.sources)]);
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
  redirect("/library");
}
