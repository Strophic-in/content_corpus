"use server";

import { refresh } from "next/cache";

import { asUser } from "@/lib/db";
import { friendly } from "@/lib/errors";
import { requireUser } from "@/lib/session";
import { voices, voiceStyles } from "@/lib/voices";

import type { ActionState } from "../actions";

// Settings → Voices: which narrator voices and voice styles Jev may pick from, or the
// one voice to always use. Ids are checked against the catalog.

async function update(sql: string, params: unknown[]): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, async (db) => {
      await db.query("select api.ensure_settings()");
      await db.query(sql, params);
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}

export async function setVoiceEnabled(id: string, on: boolean): Promise<ActionState> {
  if (!voices().some((v) => v.id === id)) return { ok: false, error: "Unknown voice." };
  return update(`update app_settings set voices_enabled = case when $2
                   then array_append(array_remove(voices_enabled, $1), $1) else array_remove(voices_enabled, $1) end`,
                [id, on]);
}

export async function setVoiceStyleEnabled(id: string, on: boolean): Promise<ActionState> {
  if (!voiceStyles().some((s) => s.style_id === id)) return { ok: false, error: "Unknown style." };
  return update(`update app_settings set voice_styles_enabled = case when $2
                   then array_append(array_remove(voice_styles_enabled, $1), $1)
                   else array_remove(voice_styles_enabled, $1) end`, [id, on]);
}

export async function setVoiceMode(mode: "auto" | "fixed", voice: string | null, style: string | null): Promise<ActionState> {
  if (mode !== "auto" && mode !== "fixed") return { ok: false, error: "Pick a mode." };
  if (voice && !voices().some((v) => v.id === voice)) return { ok: false, error: "Unknown voice." };
  if (style && !voiceStyles().some((s) => s.style_id === style)) return { ok: false, error: "Unknown style." };
  return update("update app_settings set voice_mode = $1, fixed_voice = coalesce($2, fixed_voice), fixed_voice_style = $3",
                [mode, voice, style]);
}
