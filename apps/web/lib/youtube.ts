import "server-only";

import { decrypt } from "./crypto";
import { asUser } from "./db";

/**
 * YouTube's public data for the Explore page, read with the owner's own YouTube
 * Data API key (Settings). Quota: a chart or a statistics read costs 1 unit, a
 * search 100, of 10,000 a day — so results are kept for CACHE_MS per query.
 * The key goes in a header, never a URL (URLs end up in logs).
 */
export type Video = {
  id: string; title: string; channel: string; channelId: string; description: string; published: string;
  thumbnail: string | null; views: number; likes: number; comments: number; seconds: number;
  viewsPerHour: number; ageHours: number; short: boolean;
};

const API = "https://www.googleapis.com/youtube/v3";
const CACHE_MS = 15 * 60_000;
const cache = new Map<string, { at: number; videos: Video[] }>();

export const REGIONS: [string, string][] = [
  ["IN", "India"], ["US", "United States"], ["GB", "United Kingdom"], ["CA", "Canada"], ["AU", "Australia"],
  ["AE", "UAE"], ["SG", "Singapore"], ["DE", "Germany"], ["FR", "France"], ["BR", "Brazil"], ["JP", "Japan"],
];
export const CATEGORIES: [string, string][] = [
  ["", "All"], ["25", "News & Politics"], ["28", "Science & Tech"], ["24", "Entertainment"], ["23", "Comedy"],
  ["17", "Sports"], ["20", "Gaming"], ["10", "Music"], ["26", "Howto & Style"], ["27", "Education"],
  ["22", "People & Blogs"], ["1", "Film & Animation"], ["2", "Autos"], ["15", "Pets & Animals"],
  ["19", "Travel"],
];

export class YouTubeError extends Error {}

export async function youtubeKey(userId: string): Promise<string | null> {
  const ct = await asUser(userId, async (db) =>
    (await db.query("select api.youtube_key_ciphertext() as k")).rows[0]?.k as string | null);
  return ct ? decrypt(ct) : null;
}

async function call(key: string, path: string, params: Record<string, string>) {
  const r = await fetch(`${API}/${path}?${new URLSearchParams(params)}`, {
    headers: { "X-Goog-Api-Key": key }, signal: AbortSignal.timeout(15_000), cache: "no-store",
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const reason = body?.error?.errors?.[0]?.reason as string | undefined;
    throw new YouTubeError(reason === "quotaExceeded" ? "Today's YouTube quota is used up — it resets at midnight Pacific time."
      : reason === "videoChartNotFound" ? "YouTube has no chart for that country and category."
      : body?.error?.message ?? `YouTube answered ${r.status}`);
  }
  return body;
}

function seconds(iso: string | undefined): number {
  const m = /^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/.exec(iso ?? "");
  return m ? ((+(m[1] ?? 0) * 24 + +(m[2] ?? 0)) * 60 + +(m[3] ?? 0)) * 60 + +(m[4] ?? 0) : 0;
}

type Item = {
  id: string;
  snippet?: { title?: string; channelTitle?: string; channelId?: string; description?: string; publishedAt?: string;
              thumbnails?: Record<string, { url: string }> };
  statistics?: { viewCount?: string; likeCount?: string; commentCount?: string };
  contentDetails?: { duration?: string };
};

/** The API doesn't say which videos are Shorts: a minute or less is, and up to three
 *  minutes when it calls itself one (#shorts) — a 1:31 trailer or a 2:50 song isn't. */
function isShort(secs: number, title = "", description = ""): boolean {
  if (secs <= 0) return false;
  return secs <= 60 || (secs <= 180 && /#shorts?\b/i.test(`${title} ${description}`));
}

function toVideo(v: Item, now: number): Video {
  const sn = v.snippet ?? {};
  const st = v.statistics ?? {};
  const t = sn.thumbnails ?? {};
  const views = Number(st.viewCount ?? 0);
  const hours = Math.max(1, (now - Date.parse(sn.publishedAt ?? "")) / 3_600_000 || 1);
  const secs = seconds(v.contentDetails?.duration);
  return {
    id: v.id, title: sn.title ?? "", channel: sn.channelTitle ?? "", channelId: sn.channelId ?? "",
    description: (sn.description ?? "").slice(0, 600), published: sn.publishedAt ?? "",
    thumbnail: (t.maxres ?? t.standard ?? t.high ?? t.medium ?? t.default)?.url ?? null,
    views, likes: Number(st.likeCount ?? 0), comments: Number(st.commentCount ?? 0), seconds: secs,
    viewsPerHour: Math.round(views / hours), ageHours: Math.round(hours), short: isShort(secs, sn.title, sn.description),
  };
}

async function cached(key: string, load: () => Promise<Video[]>): Promise<Video[]> {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < CACHE_MS) return hit.videos;
  const videos = await load();
  cache.set(key, { at: Date.now(), videos });
  if (cache.size > 200) cache.delete(cache.keys().next().value!);
  return videos;
}

/** A country's most-popular chart (optionally one category): 1 quota unit. */
export async function trending(key: string, region: string, category: string): Promise<Video[]> {
  return cached(`t:${key.slice(-6)}:${region}:${category}`, async () => {
    const body = await call(key, "videos", {
      part: "snippet,statistics,contentDetails", chart: "mostPopular", regionCode: region, maxResults: "50",
      ...(category ? { videoCategoryId: category } : {}),
    });
    const now = Date.now();
    return (body.items ?? []).map((v: Item) => toVideo(v, now));
  });
}

/** Videos about `q` from the last `days`, most viewed first: 101 quota units. */
export async function search(key: string, q: string, days: number, region: string, shortsOnly: boolean,
                             order: "viewCount" | "date" | "relevance"): Promise<Video[]> {
  return cached(`s:${key.slice(-6)}:${q}:${days}:${region}:${shortsOnly}:${order}`, async () => {
    const after = new Date(Date.now() - days * 86_400_000).toISOString();
    const found = await call(key, "search", {
      part: "id", type: "video", q, order, publishedAfter: after, regionCode: region, maxResults: "50",
      ...(shortsOnly ? { videoDuration: "short" } : {}),
    });
    const ids = (found.items ?? []).map((i: { id?: { videoId?: string } }) => i.id?.videoId).filter(Boolean);
    if (!ids.length) return [];
    const body = await call(key, "videos", { part: "snippet,statistics,contentDetails", id: ids.join(",") });
    const now = Date.now();
    const byId = new Map<string, Video>((body.items ?? []).map((v: Item) => [v.id, toVideo(v, now)]));
    return ids.map((id: string) => byId.get(id)).filter(Boolean) as Video[];
  });
}
