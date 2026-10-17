"use server";

import { refresh } from "next/cache";

import { asUser } from "@/lib/db";
import { friendly } from "@/lib/errors";
import { requireUser } from "@/lib/session";
import { wakeWorker } from "@/lib/wake";

import type { ActionState } from "../actions";

/** "More ideas": the agent reads one category's sources (or every category's) and
 *  suggests a fresh batch. */
export async function requestIdeas(target: { categoryId: string } | { channelId: string }): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => "categoryId" in target
      ? db.query("select api.request_category_ideas($1)", [target.categoryId])
      : db.query("select api.request_channel_ideas($1)", [target.channelId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true };
}

/**
 * A swipe. Right (accept) schedules the idea as a post at `date` + `time` in the
 * channel's own timezone; left (reject) records the optional reason, which the
 * agent reads before its next batch. `media`: what the reel does with the card's
 * own picture or video — "original" shows it, credited (that choice is the
 * approval); "ai" makes an AI version instead and never shows the original.
 */
export async function decideIdea(ideaId: string, accept: boolean, date: string | null, time: string | null,
                                 reason: string | null, platforms: string[] | null,
                                 media: "none" | "original" | "ai" = "none", formatId: string | null = null,
                                 ): Promise<ActionState & { postId?: string }> {
  const user = await requireUser();
  if (accept && !(date && /^\d{4}-\d{2}-\d{2}$/.test(date) && time && /^\d{2}:\d{2}(:\d{2})?$/.test(time)))
    return { ok: false, error: "Pick a date and time." };
  if (formatId && !/^[0-9a-f-]{36}$/i.test(formatId)) return { ok: false, error: "Pick a format." };
  try {
    const postId = await asUser(user.id, async (db) => {
      const r = await db.query(
        `select (api.decide_idea_v2($1, $2,
                   case when $2 then ($3::date + $4::time) at time zone
                     (select c.timezone from ideas i join channels c on c.id = i.channel_id where i.id = $1)
                   end,
                   $5, $6::text[], false, $7::text, $8::uuid)).post_id`,
        [ideaId, accept, date, time, reason?.slice(0, 200) || null,
         platforms?.filter((p) => p === "youtube" || p === "instagram") ?? null,
         accept && ["original", "ai"].includes(media) ? media : "none", accept ? formatId : null],
      );
      return r.rows[0]?.post_id as string | undefined;
    });
    return { ok: true, postId };
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
}
