import Link from "next/link";
import { Suspense } from "react";

import { workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";
import {
  CATEGORIES, REGIONS, search, SUBCATEGORIES, subcategory, trending, WORLDWIDE, youtubeKey, YouTubeError, type Video,
} from "@/lib/youtube";

import { VideoGridSkeleton } from "../skeletons";
import { ExploreFilters } from "./filters";
import { MakeIdea } from "./make-idea";

export const metadata = { title: "Explore YouTube · Content Corpus" };

const SORTS = { views: "Most viewed", momentum: "Fastest rising", newest: "Newest", reach: "Most countries" } as const;
type Sort = keyof typeof SORTS;

const compact = (n: number) => new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n);
const age = (h: number) => (h < 48 ? `${h} h ago` : h < 24 * 60 ? `${Math.round(h / 24)} d ago` : `${Math.round(h / 720)} mo ago`);
const length = (s: number) => (s ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "");

// What's doing well on YouTube right now — a country's trending chart, or a topic's
// most-viewed videos lately — with how fast each is rising (views an hour since it
// went up). "Make an idea" turns one into an idea card for a channel; the reel is
// made our way, never from their video.
export default async function ExplorePage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const user = await requireUser();
  const sp = await searchParams;
  const one = (k: string) => (Array.isArray(sp[k]) ? sp[k]![0] : sp[k]) ?? "";
  const tab = one("tab") === "search" ? "search" : "trending";
  const region = REGIONS.some(([c]) => c === one("region")) ? one("region") : "IN";
  const category = CATEGORIES.some(([c]) => c === one("cat")) ? one("cat") : "";
  // A sub-category is a search inside its category (charts have none).
  const sub = tab === "trending" ? subcategory(category, one("sub")) : null;
  const world = region === WORLDWIDE;
  const q = one("q").trim().slice(0, 100);
  const days = [1, 7, 30].includes(Number(one("days"))) ? Number(one("days")) : 7;
  const shorts = one("shorts") === "1";
  const asked = one("sort") as Sort;
  // "Most countries" only means something for the Worldwide chart.
  const reachable = world && tab === "trending" && !sub;
  const sort: Sort = asked in SORTS && (asked !== "reach" || reachable) ? asked
    : tab === "search" || sub ? "views" : reachable ? "reach" : "momentum";

  const { active } = await workspace(user.id);
  const destinations = await asUser(user.id, async (db) => (await db.query(
    `select k.id, c.name as channel, k.name as category, c.id = $1 as active
       from categories k join channels c on c.id = k.channel_id
      order by (c.id = $1) desc, c.name, k.created_at`, [active.id])).rows as
    { id: string; channel: string; category: string; active: boolean }[]);
  const to = destinations.find((d) => d.id === one("to")) ?? destinations[0];

  const query: Query = { tab, region, category, sub: sub ?? null, q, days, shorts, sort };

  const keep: Record<string, string> = { tab, region, cat: category, sub: sub?.id ?? "", q, days: String(days), shorts: shorts ? "1" : "", sort,
                 to: to?.id ?? "" };
  const subs = tab === "trending" ? SUBCATEGORIES[category] ?? [] : [];
  const href = (over: Partial<typeof keep>) =>
    `/explore?${new URLSearchParams(Object.entries({ ...keep, ...over }).filter(([, v]) => v) as [string, string][])}`;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Explore YouTube</h1>
          <p className="text-sm text-muted">What&apos;s doing well right now — and how fast it&apos;s rising.</p>
        </div>
        <nav className="flex rounded-full border border-border p-1 text-sm">
          {(["trending", "search"] as const).map((t) => (
            <Link key={t} href={href({ tab: t, sort: t === "search" ? "views" : "momentum" })}
                  className={`rounded-full px-3 py-1 ${tab === t ? "bg-accent text-accent-foreground" : "text-muted"}`}>
              {t === "trending" ? "Trending" : "Search"}
            </Link>
          ))}
        </nav>
      </div>

      <ExploreFilters key={`${tab}:${region}:${category}:${sub?.id ?? ""}`} tab={tab} region={region}
                      category={category} sub={sub?.id ?? ""} q={q} days={days} shorts={shorts} sort={sort} sorts={SORTS}
                      destinations={destinations} to={to?.id ?? ""} />
      {subs.length > 0 && (
        <nav aria-label="Sub-categories" className="-mt-2 flex gap-1.5 overflow-x-auto pb-1 text-sm">
          <Link href={href({ sub: "", sort: "" })}
                className={`shrink-0 rounded-full border px-3 py-1 ${!sub ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"}`}>
            All {CATEGORIES.find(([c]) => c === category)?.[1]}
          </Link>
          {subs.map((x) => (
            <Link key={x.id} href={href({ sub: x.id, sort: "" })}
                  className={`shrink-0 rounded-full border px-3 py-1 ${sub?.id === x.id ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"}`}>
              {x.name}
            </Link>
          ))}
        </nav>
      )}
      <p className="-mt-2 text-xs text-muted">
        {tab === "search" || sub
          ? `A ${sub ? "sub-category" : "search"} uses 101 of your 10,000 daily YouTube units`
          : world ? "Worldwide reads 12 countries' charts: 12 of your 10,000 daily YouTube units"
          : "A chart uses 1 of your 10,000 daily YouTube units"};
        results are kept for 15 minutes.
        {sub && " A sub-category is a search for its topic inside the category, most viewed lately first."}
      </p>

      {/* The filters show at once; the videos stream in when YouTube answers. */}
      <Suspense key={JSON.stringify(query)} fallback={<VideoGridSkeleton />}>
        <Results userId={user.id} query={query} categoryId={to?.id ?? null} />
      </Suspense>
    </div>
  );
}

type Query = { tab: "trending" | "search"; region: string; category: string;
               sub: { id: string; q: string } | null; q: string; days: number; shorts: boolean; sort: Sort };

async function Results({ userId, query, categoryId }: { userId: string; query: Query; categoryId: string | null }) {
  const { tab, region, category, sub, q, days, shorts, sort } = query;
  const key = await youtubeKey(userId);
  let videos: Video[] = [];
  let error: string | null = null;
  if (key && (tab === "trending" || q)) {
    try {
      const order = sort === "newest" ? "date" : "viewCount";
      videos = sub ? await search(key, sub.q, days, region, shorts, order, category)
        : tab === "trending" ? await trending(key, region, category)
        : await search(key, q, days, region, shorts, order, category);
    } catch (e) {
      error = e instanceof YouTubeError ? e.message : "YouTube couldn't be reached — try again in a moment.";
    }
  }
  if (shorts) videos = videos.filter((v) => v.short);
  videos = [...videos].sort((a, b) => sort === "views" ? b.views - a.views
    : sort === "newest" ? a.ageHours - b.ageHours
    : sort === "reach" ? (b.countries?.length ?? 0) - (a.countries?.length ?? 0) || b.viewsPerHour - a.viewsPerHour
    : b.viewsPerHour - a.viewsPerHour);

  return !key ? (
    <p className="rounded-xl border border-border bg-surface p-5 text-sm">
      Add your YouTube Data API key in <Link href="/settings" className="text-accent underline">Settings</Link> to
      explore.
    </p>
  ) : error ? (
    <p role="alert" className="rounded-xl border border-danger bg-danger-surface p-4 text-sm text-danger">{error}</p>
  ) : tab === "search" && !q ? (
    <p className="text-sm text-muted">Search a topic to see what&apos;s been doing well on it lately.</p>
  ) : videos.length === 0 ? (
    <p className="text-sm text-muted">Nothing here{shorts ? " among Shorts" : ""}. Try another country, category or time window.</p>
  ) : (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {videos.map((v, i) => (
        <li key={v.id} className="flex flex-col overflow-hidden rounded-2xl border border-border bg-surface">
          <a href={`https://www.youtube.com/watch?v=${v.id}`} target="_blank" rel="noreferrer"
             className="relative block aspect-video bg-black">
            {v.thumbnail && (
              // eslint-disable-next-line @next/next/no-img-element -- YouTube's own thumbnail
              <img src={v.thumbnail} alt="" loading="lazy" className="size-full object-cover" />
            )}
            <span className="absolute top-2 left-2 rounded-md bg-black/70 px-1.5 py-0.5 text-xs font-medium text-white">#{i + 1}</span>
            {v.short && <span className="absolute top-2 right-2 rounded-md bg-red-600 px-1.5 py-0.5 text-xs font-semibold text-white">Short</span>}
            {v.seconds > 0 && (
              <span className="absolute right-2 bottom-2 rounded-md bg-black/70 px-1.5 py-0.5 text-xs text-white">{length(v.seconds)}</span>
            )}
          </a>
          <div className="flex flex-1 flex-col gap-2 p-3 text-sm">
            <a href={`https://www.youtube.com/watch?v=${v.id}`} target="_blank" rel="noreferrer"
               className="line-clamp-2 font-medium hover:underline">{v.title}</a>
            <p className="truncate text-xs text-muted">{v.channel} · {age(v.ageHours)}</p>
            {v.countries && v.countries.length > 0 && (
              <p className="text-xs" title={v.countries.join(", ")}>
                <span className="font-medium text-ok">🔥 Trending in {v.countries.length} {v.countries.length === 1 ? "country" : "countries"}</span>
                <span className="text-muted"> · {v.countries.slice(0, 5).join(" ")}{v.countries.length > 5 ? ` +${v.countries.length - 5}` : ""}</span>
              </p>
            )}
            <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
              <span><b>{compact(v.views)}</b> views</span>
              <span className="text-accent"><b>{compact(v.viewsPerHour)}</b>/hour</span>
              <span className="text-muted">{compact(v.likes)} likes · {compact(v.comments)} comments</span>
            </p>
            <div className="mt-auto pt-1"><MakeIdea categoryId={categoryId} video={v} /></div>
          </div>
        </li>
      ))}
    </ul>
  );
}
