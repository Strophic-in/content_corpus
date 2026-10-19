"use server";

import { refresh } from "next/cache";

import { asUser } from "@/lib/db";
import { friendly } from "@/lib/errors";
import { requireUser } from "@/lib/session";
import { captionStyles, thumbStyles } from "@/lib/styles";

import type { ActionState } from "../actions";

/** Settings → Styles: a caption or cover style switched on or off (Jev picks among those on). */
export async function setStyleEnabled(kind: "caption" | "thumb", id: string, on: boolean): Promise<ActionState> {
  const list = kind === "caption" ? captionStyles() : thumbStyles();
  if (!list.some((s) => s.id === id)) return { ok: false, error: "Unknown style." };
  const col = kind === "caption" ? "caption_styles_enabled" : "thumb_styles_enabled";
  const user = await requireUser();
  try {
    await asUser(user.id, async (db) => {
      await db.query("select api.ensure_settings()");
      await db.query(`update app_settings set ${col} = case when $2 then array_append(array_remove(${col}, $1), $1)
                                                 else array_remove(${col}, $1) end`, [id, on]);
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}
