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
  countries?: string[];          // Worldwide: the charts it is trending on
};

const API = "https://www.googleapis.com/youtube/v3";
const CACHE_MS = 15 * 60_000;
const cache = new Map<string, { at: number; videos: Video[] }>();

/** "WW": Worldwide — the charts of WORLD merged (YouTube has no global chart). */
export const WORLDWIDE = "WW";
export const REGIONS: [string, string][] = [
  [WORLDWIDE, "🌍 Worldwide"],
  ["IN", "India"], ["US", "United States"], ["GB", "United Kingdom"], ["CA", "Canada"], ["AU", "Australia"],
  ["NZ", "New Zealand"], ["IE", "Ireland"], ["AE", "UAE"], ["SA", "Saudi Arabia"], ["SG", "Singapore"],
  ["MY", "Malaysia"], ["PH", "Philippines"], ["ID", "Indonesia"], ["PK", "Pakistan"], ["BD", "Bangladesh"],
  ["LK", "Sri Lanka"], ["NP", "Nepal"], ["NG", "Nigeria"], ["KE", "Kenya"], ["ZA", "South Africa"],
  ["EG", "Egypt"], ["DE", "Germany"], ["FR", "France"], ["ES", "Spain"], ["IT", "Italy"], ["NL", "Netherlands"],
  ["SE", "Sweden"], ["PL", "Poland"], ["TR", "Türkiye"], ["RU", "Russia"], ["BR", "Brazil"], ["MX", "Mexico"],
  ["AR", "Argentina"], ["CO", "Colombia"], ["JP", "Japan"], ["KR", "South Korea"], ["TW", "Taiwan"],
  ["HK", "Hong Kong"], ["TH", "Thailand"], ["VN", "Vietnam"],
];
// The big, widely watched charts Worldwide merges: 1 unit each.
const WORLD = ["US", "IN", "GB", "CA", "AU", "PH", "NG", "ZA", "SG", "AE", "IE", "NZ"];

export const CATEGORIES: [string, string][] = [
  ["", "All"], ["25", "News & Politics"], ["28", "Science & Tech"], ["24", "Entertainment"], ["23", "Comedy"],
  ["17", "Sports"], ["20", "Gaming"], ["10", "Music"], ["26", "Howto & Style"], ["27", "Education"],
  ["22", "People & Blogs"], ["1", "Film & Animation"], ["2", "Autos"], ["15", "Pets & Animals"],
  ["19", "Travel"], ["29", "Nonprofits & Activism"],
];

/** Sub-categories: YouTube's charts have none, so each is a search inside its
 *  category for its own words (`|` is YouTube's OR), most viewed lately first. */
export const SUBCATEGORIES: Record<string, { id: string; name: string; q: string }[]> = {
  "28": [
    { id: "ai", name: "AI", q: "AI|artificial intelligence|ChatGPT|OpenAI|Gemini" },
    { id: "space", name: "Space", q: "space|NASA|ISRO|SpaceX|rocket|astronomy" },
    { id: "phones", name: "Smartphones", q: "smartphone|iPhone|Samsung Galaxy|Pixel|OnePlus" },
    { id: "gadgets", name: "Gadgets & reviews", q: "gadget|unboxing|tech review" },
    { id: "pc", name: "Computers & PC", q: "PC build|laptop|GPU|Nvidia|processor" },
    { id: "ev", name: "Electric vehicles", q: "electric vehicle|EV|Tesla|battery" },
    { id: "physics", name: "Physics", q: "physics|quantum|black hole|relativity" },
    { id: "bio", name: "Biology & health", q: "biology|medicine|human body|brain|DNA" },
    { id: "climate", name: "Climate & environment", q: "climate|environment|renewable energy" },
    { id: "robots", name: "Robotics", q: "robot|robotics|humanoid" },
    { id: "cyber", name: "Cybersecurity", q: "cybersecurity|hacking|scam|data breach" },
    { id: "code", name: "Coding", q: "programming|coding|developer|software" },
    { id: "inventions", name: "Inventions", q: "invention|engineering|how it is made" },
  ],
  "25": [
    { id: "world", name: "World news", q: "world news|international" },
    { id: "india", name: "India", q: "India news|Indian politics" },
    { id: "us", name: "US politics", q: "US politics|White House|Congress" },
    { id: "elections", name: "Elections", q: "election|polls|vote" },
    { id: "war", name: "War & conflict", q: "war|conflict|military|ceasefire" },
    { id: "economy", name: "Economy & markets", q: "economy|stock market|inflation|budget" },
    { id: "disasters", name: "Weather & disasters", q: "flood|earthquake|cyclone|storm|wildfire" },
    { id: "crime", name: "Crime & courts", q: "crime|court|verdict|arrest" },
    { id: "explained", name: "Explained", q: "explained|analysis" },
  ],
  "24": [
    { id: "movies", name: "Movies & trailers", q: "trailer|movie|box office" },
    { id: "series", name: "TV & web series", q: "web series|Netflix|Prime Video|season" },
    { id: "bollywood", name: "Bollywood", q: "Bollywood" },
    { id: "south", name: "South Indian cinema", q: "Tollywood|Kollywood|Telugu movie|Tamil movie" },
    { id: "hollywood", name: "Hollywood", q: "Hollywood|Marvel|DC" },
    { id: "celebs", name: "Celebrities", q: "celebrity|interview|red carpet" },
    { id: "reality", name: "Reality shows", q: "reality show|Bigg Boss|talent show" },
    { id: "kdrama", name: "K-drama & K-pop", q: "K-drama|K-pop|BTS|BLACKPINK" },
    { id: "anime", name: "Anime", q: "anime" },
  ],
  "23": [
    { id: "standup", name: "Stand-up", q: "stand up comedy" },
    { id: "sketch", name: "Sketches", q: "comedy sketch|funny skit" },
    { id: "pranks", name: "Pranks", q: "prank" },
    { id: "memes", name: "Memes", q: "memes|meme review" },
    { id: "roast", name: "Roasts", q: "roast" },
  ],
  "17": [
    { id: "cricket", name: "Cricket", q: "cricket|IPL|T20|test match" },
    { id: "football", name: "Football", q: "football|soccer|Premier League|Champions League" },
    { id: "basketball", name: "Basketball", q: "NBA|basketball" },
    { id: "f1", name: "Formula 1", q: "F1|Formula 1|Grand Prix" },
    { id: "tennis", name: "Tennis", q: "tennis|Wimbledon|US Open" },
    { id: "combat", name: "Combat sports", q: "UFC|boxing|WWE|MMA" },
    { id: "olympics", name: "Olympics & athletics", q: "Olympics|athletics|javelin|sprint" },
    { id: "kabaddi", name: "Kabaddi", q: "kabaddi|Pro Kabaddi" },
  ],
  "20": [
    { id: "minecraft", name: "Minecraft", q: "Minecraft" },
    { id: "gta", name: "GTA", q: "GTA|GTA 6" },
    { id: "battle", name: "Battle royale", q: "BGMI|PUBG|Free Fire|Fortnite|Warzone" },
    { id: "esports", name: "Esports", q: "esports|tournament|Valorant" },
    { id: "trailers", name: "Game trailers", q: "game trailer|gameplay reveal" },
    { id: "mobile", name: "Mobile games", q: "mobile game" },
  ],
  "10": [
    { id: "bollywood", name: "Bollywood songs", q: "Bollywood song|Hindi song" },
    { id: "punjabi", name: "Punjabi", q: "Punjabi song" },
    { id: "hiphop", name: "Hip-hop & rap", q: "rap|hip hop" },
    { id: "pop", name: "Pop", q: "pop song|official music video" },
    { id: "kpop", name: "K-pop", q: "K-pop" },
    { id: "lofi", name: "Lo-fi & chill", q: "lofi|chill" },
    { id: "covers", name: "Covers", q: "cover song|acoustic cover" },
  ],
  "26": [
    { id: "cooking", name: "Cooking", q: "recipe|cooking" },
    { id: "fashion", name: "Fashion", q: "fashion|outfit|haul" },
    { id: "beauty", name: "Beauty & makeup", q: "makeup|skincare|beauty" },
    { id: "fitness", name: "Fitness", q: "workout|fitness|gym" },
    { id: "diy", name: "DIY & crafts", q: "DIY|craft|hack" },
    { id: "home", name: "Home", q: "home decor|room makeover|cleaning" },
  ],
  "27": [
    { id: "history", name: "History", q: "history|ancient|empire" },
    { id: "money", name: "Money & finance", q: "personal finance|investing|money" },
    { id: "psychology", name: "Psychology", q: "psychology|mind|habits" },
    { id: "geography", name: "Geography", q: "geography|map|countries" },
    { id: "maths", name: "Maths", q: "maths|math" },
    { id: "exams", name: "Exams & study", q: "UPSC|JEE|NEET|study tips" },
    { id: "languages", name: "Languages", q: "learn English|language learning" },
    { id: "explainers", name: "Explainers", q: "explained|how does|why does" },
  ],
  "22": [
    { id: "vlogs", name: "Vlogs", q: "vlog" },
    { id: "dayinlife", name: "Day in the life", q: "day in the life" },
    { id: "podcasts", name: "Podcasts", q: "podcast" },
    { id: "motivation", name: "Motivation", q: "motivation|success story" },
    { id: "relationships", name: "Relationships", q: "relationship|dating|marriage" },
  ],
  "1": [
    { id: "animation", name: "Animation", q: "animation|animated short" },
    { id: "shortfilm", name: "Short films", q: "short film" },
    { id: "vfx", name: "VFX & behind the scenes", q: "VFX|behind the scenes" },
  ],
  "2": [
    { id: "cars", name: "Cars", q: "car review|new car" },
    { id: "bikes", name: "Bikes", q: "bike review|motorcycle" },
    { id: "ev", name: "Electric", q: "electric car|EV" },
    { id: "super", name: "Supercars", q: "supercar|hypercar|Lamborghini|Ferrari" },
  ],
  "15": [
    { id: "dogs", name: "Dogs", q: "dog|puppy" },
    { id: "cats", name: "Cats", q: "cat|kitten" },
    { id: "wildlife", name: "Wildlife", q: "wildlife|wild animals|safari" },
    { id: "ocean", name: "Ocean life", q: "ocean|shark|whale" },
    { id: "funny", name: "Funny animals", q: "funny animals" },
  ],
  "19": [
    { id: "vlogs", name: "Travel vlogs", q: "travel vlog" },
    { id: "food", name: "Street food", q: "street food" },
    { id: "places", name: "Hidden places", q: "hidden places|abandoned|unexplored" },
    { id: "budget", name: "Budget travel", q: "budget travel|cheap travel" },
  ],
};

export function subcategory(category: string, id: string) {
  return SUBCATEGORIES[category]?.find((s) => s.id === id) ?? null;
}

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

/** A country's most-popular chart (optionally one category): 1 quota unit. Worldwide:
 *  the WORLD charts merged (12 units), each video marked with the charts it is on. */
export async function trending(key: string, region: string, category: string): Promise<Video[]> {
  if (region === WORLDWIDE) {
    return cached(`tw:${key.slice(-6)}:${category}`, async () => {
      const charts = await Promise.allSettled(WORLD.map((r) => trending(key, r, category)));
      const ok = charts.flatMap((c, i) => (c.status === "fulfilled" ? [[WORLD[i], c.value] as const] : []));
      if (!ok.length) throw (charts[0] as PromiseRejectedResult).reason;
      const byId = new Map<string, Video>();
      for (const [country, videos] of ok) {
        for (const v of videos) {
          const seen = byId.get(v.id);
          if (seen) seen.countries = [...(seen.countries ?? []), country];
          else byId.set(v.id, { ...v, countries: [country] });
        }
      }
      return [...byId.values()];
    });
  }
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
                             order: "viewCount" | "date" | "relevance", category = ""): Promise<Video[]> {
  return cached(`s:${key.slice(-6)}:${q}:${days}:${region}:${shortsOnly}:${order}:${category}`, async () => {
    const after = new Date(Date.now() - days * 86_400_000).toISOString();
    const found = await call(key, "search", {
      part: "id", type: "video", q, order, publishedAfter: after, maxResults: "50",
      ...(region && region !== WORLDWIDE ? { regionCode: region } : {}),
      ...(category ? { videoCategoryId: category } : {}),
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
