"use server";

import { asUser } from "@/lib/db";
import { friendly } from "@/lib/errors";
import { requireUser } from "@/lib/session";
import { wakeWorker } from "@/lib/wake";
import type { Video } from "@/lib/youtube";

import type { ActionState } from "../actions";

/** "Make an idea": the ideas lane turns the video into an idea card for the category. */
export async function makeIdea(categoryId: string, v: Video): Promise<ActionState> {
  const user = await requireUser();
  const video = {
    id: v.id, title: v.title.slice(0, 300), channel: v.channel.slice(0, 120), description: v.description.slice(0, 600),
    published: v.published, thumbnail: v.thumbnail, views: v.views, likes: v.likes, comments: v.comments,
  };
  try {
    await asUser(user.id, (db) => db.query("select api.idea_from_video($1, $2::jsonb)",
                                           [categoryId, JSON.stringify(video)]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  return { ok: true, message: "Writing the idea — it'll be on the channel's Discover deck in a minute." };
}
