"use server";

import { refresh } from "next/cache";
import { z } from "zod";

import { asUser } from "@/lib/db";
import { friendly } from "@/lib/errors";
import { requireUser } from "@/lib/session";
import { wakeWorker } from "@/lib/wake";

import type { ActionState } from "../actions";

const CategoryInput = z.object({
  name: z.string().trim().min(1, "Give the category a name.").max(60),
  color: z.string().regex(/^#[0-9a-fA-F]{6}$/, "Pick a colour."),
  brief: z.string().trim().max(4000, "Keep the category prompt under 4,000 characters."),
  keywords: z.string().trim().max(500),
  format_ids: z.array(z.string().uuid()).max(40),
  ideas_per_batch: z.coerce.number().int().min(1, "At least 1 idea.").max(30, "At most 30 ideas."),
  enabled: z.string().optional().transform((v) => v === "on"),
});

// The ticked formats come as repeated "format_ids" fields.
const fields = (form: FormData) => ({ ...Object.fromEntries(form), format_ids: form.getAll("format_ids").map(String) });

// Every format ticked is stored as none ('{}'), which means "all of the channel's
// formats" — so a format made later is open to the category too.
const ALL_OR = (channel: string, ids: string) =>
  `case when exists (select 1 from formats f where f.channel_id = ${channel} and f.id <> all(${ids}::uuid[]))
        then ${ids}::uuid[] else '{}'::uuid[] end`;

export async function createCategory(channelId: string, _: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = CategoryInput.safeParse(fields(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const v = parsed.data;
  try {
    await asUser(user.id, (db) => db.query(
      `insert into categories (user_id, channel_id, name, color, brief, keywords, format_ids, ideas_per_batch, enabled)
       values ($1, $2, $3, $4, $5, $6, ${ALL_OR("$2", "$7")}, $8, true)`,
      [user.id, channelId, v.name, v.color, v.brief, v.keywords, v.format_ids, v.ideas_per_batch]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: `“${v.name}” added — now give it some sources.` };
}

export async function updateCategory(categoryId: string, _: ActionState, form: FormData): Promise<ActionState> {
  const user = await requireUser();
  const parsed = CategoryInput.safeParse(fields(form));
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0].message };
  const v = parsed.data;
  try {
    await asUser(user.id, (db) => db.query(
      `update categories set name = $2, color = $3, brief = $4, keywords = $5,
                             format_ids = ${ALL_OR("categories.channel_id", "$6")},
                             ideas_per_batch = $7, enabled = $8
        where id = $1`,
      [categoryId, v.name, v.color, v.brief, v.keywords, v.format_ids, v.ideas_per_batch, v.enabled]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true, message: "Saved." };
}

export async function deleteCategory(categoryId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    const left = await asUser(user.id, async (db) => {
      const n = (await db.query(
        `select count(*)::int as n from categories
          where channel_id = (select channel_id from categories where id = $1)`, [categoryId])).rows[0].n as number;
      if (n <= 1) return false;
      await db.query("delete from categories where id = $1", [categoryId]);
      return true;
    });
    if (!left) return { ok: false, error: "A channel needs at least one category." };
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}

export type SourceKind = "reddit" | "site" | "rss" | "search" | "google_trends" | "wikipedia"
  | "bluesky" | "mastodon" | "lemmy" | "hackernews" | "youtube";

const HOST = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/;
const bareHost = (v: string) => v.replace(/^https?:\/\//i, "").replace(/\/.*$/, "").toLowerCase();

/** What the owner typed → the stored value, or an error to show. */
function normalize(kind: SourceKind, raw: string): { value?: string; error?: string } {
  const v = raw.trim();
  if (!v) return { error: "Type something first." };
  switch (kind) {
    case "bluesky": {
      if (/^(what'?s[- ]?hot|discover)$/i.test(v)) return { value: "whats-hot" };
      if (/^trending( topics)?$/i.test(v)) return { value: "trending" };
      const at = v.match(/^at:\/\/([^/]+)\/app\.bsky\.feed\.generator\/([A-Za-z0-9_-]+)$/);
      if (at) return { value: `https://bsky.app/profile/${at[1]}/feed/${at[2]}` };
      const m = v.match(/^https?:\/\/(www\.)?bsky\.app\/profile\/([A-Za-z0-9.:_-]+)\/feed\/([A-Za-z0-9_-]+)\/?$/);
      return m ? { value: `https://bsky.app/profile/${m[2]}/feed/${m[3]}` }
        : { error: "Type whats-hot, trending, or paste a feed link (bsky.app/profile/…/feed/…)." };
    }
    case "mastodon": {
      const tagUrl = v.match(/^https?:\/\/([^/]+)\/tags\/([A-Za-z0-9_]+)/i);
      if (tagUrl) return { value: `#${tagUrl[2]}@${tagUrl[1].toLowerCase()}` };
      const tag = v.match(/^#([A-Za-z0-9_]{1,100})(?:@(.+))?$/);
      if (tag) {
        const host = bareHost(tag[2] ?? "mastodon.social");
        return HOST.test(host) ? { value: `#${tag[1]}@${host}` } : { error: "That isn't a Mastodon server (like mastodon.social)." };
      }
      const host = bareHost(v);
      return HOST.test(host) ? { value: host } : { error: "Type a server (mastodon.social) or a hashtag (#science)." };
    }
    case "lemmy": {
      const url = v.match(/^https?:\/\/([^/]+)\/c\/([A-Za-z0-9_]{1,50})(?:@([^/]+))?/i);
      if (url) return { value: `${url[2]}@${(url[3] ?? url[1]).toLowerCase()}` };
      const comm = v.replace(/^!/, "").match(/^(?:c\/)?([A-Za-z0-9_]{1,50})@(.+)$/i);
      if (comm) {
        const host = bareHost(comm[2]);
        return HOST.test(host) ? { value: `${comm[1]}@${host}` } : { error: "That isn't a Lemmy server (like lemmy.world)." };
      }
      const host = bareHost(v);
      return HOST.test(host) ? { value: host }
        : { error: "Type a server (lemmy.world) or a community on one (technology@lemmy.world)." };
    }
    case "hackernews":
      if (/^(front[ _-]?page|top|frontpage)$/i.test(v)) return { value: "front_page" };
      return v.length <= 200 ? { value: v } : { error: "Keep search terms under 200 characters." };
    case "youtube": {
      const m = v.toUpperCase().match(/^([A-Z]{2})(?::(\d{1,3}))?$/);
      return m ? { value: m[2] ? `${m[1]}:${m[2]}` : m[1] } : { error: "Use a two-letter country code, like IN or US." };
    }
    case "reddit": {
      const name = v.replace(/^https?:\/\/(www\.|old\.)?reddit\.com/i, "").replace(/^\/?r\//i, "").replace(/\/.*$/, "");
      return /^[A-Za-z0-9_]{2,21}$/.test(name) ? { value: name } : { error: "That isn't a community name (like r/worldnews)." };
    }
    case "site": {
      const host = v.replace(/^https?:\/\//i, "").replace(/\/.*$/, "").replace(/^www\./i, "").toLowerCase();
      if (/(^|\.)reddit\.com$/.test(host)) return { error: "Add Reddit communities as communities, not as a site." };
      return /^[a-z0-9.-]+\.[a-z]{2,}$/.test(host) ? { value: host } : { error: "That isn't a website domain (like reuters.com)." };
    }
    case "rss": {
      try {
        const u = new URL(v);
        if (!/^https?:$/.test(u.protocol)) return { error: "Feeds must be http(s) links." };
        if (/(^|\.)reddit\.com$/i.test(u.hostname)) return { error: "Add Reddit communities as communities, not as a feed." };
        return { value: u.toString() };
      } catch {
        return { error: "That isn't a link." };
      }
    }
    case "search":
      return v.length <= 200 ? { value: v } : { error: "Keep search terms under 200 characters." };
    case "google_trends":
      return /^[A-Za-z]{2}$/.test(v) ? { value: v.toUpperCase() } : { error: "Use a two-letter country code, like IN or US." };
    case "wikipedia":
      return /^[a-z]{2,3}$/i.test(v) ? { value: v.toLowerCase() } : { error: "Use a language code, like en or hi." };
  }
}

export async function addSource(categoryId: string, kind: SourceKind, raw: string): Promise<ActionState> {
  const user = await requireUser();
  const n = normalize(kind, raw);
  if (n.error) return { ok: false, error: n.error };
  try {
    await asUser(user.id, async (db) => {
      await db.query(`insert into category_sources (user_id, category_id, kind, value) values ($1, $2, $3, $4)
                      on conflict (category_id, kind, value) do update set enabled = true`,
                     [user.id, categoryId, kind, n.value]);
      await db.query("select api.check_category_sources($1)", [categoryId]);   // verified by the ideas worker
    });
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true };
}

export async function removeSource(sourceId: string): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("delete from category_sources where id = $1", [sourceId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}

export async function toggleSource(sourceId: string, enabled: boolean): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query("update category_sources set enabled = $2 where id = $1",
                                           [sourceId, enabled]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  refresh();
  return { ok: true };
}

/** Check every unchecked or failing source now, or ask the agent what to add. */
export async function categoryJob(categoryId: string, job: "check" | "suggest"): Promise<ActionState> {
  const user = await requireUser();
  try {
    await asUser(user.id, (db) => db.query(
      job === "check" ? "select api.check_category_sources($1)" : "select api.suggest_category_sources($1)",
      [categoryId]));
  } catch (err) {
    return { ok: false, error: friendly(err) };
  }
  await wakeWorker();
  refresh();
  return { ok: true };
}
