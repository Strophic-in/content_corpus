"use client";

import { useActionState, useState, useTransition } from "react";

import type { ActionState } from "../actions";
import {
  addSource, categoryJob, createCategory, deleteCategory, removeSource, toggleSource, updateCategory,
  type SourceKind,
} from "./category-actions";

export type SourceRow = {
  id: string; kind: SourceKind; value: string; enabled: boolean; status: "new" | "ok" | "error";
  last_items: number | null; last_error: string | null;
};
export type CategoryData = {
  id: string; name: string; color: string; brief: string; keywords: string; format_ids: string[];
  ideas_per_batch: number; enabled: boolean; sources: SourceRow[]; checking: boolean;
  suggestion: { state: string; result: { communities?: { name: string; exists: boolean; why: string }[];
                                         lemmy?: { name: string; exists: boolean; why: string }[];
                                         hashtags?: { name: string; why: string }[];
                                         sites?: { domain: string; feeds: number; why: string }[] } | null } | null;
};

const KINDS: { kind: SourceKind; label: string; placeholder: string; note?: string }[] = [
  { kind: "reddit", label: "Reddit community", placeholder: "r/worldnews",
    note: "Reddit ends its public feeds on 13 Nov 2026 — add Bluesky, Mastodon or Lemmy too." },
  { kind: "bluesky", label: "Bluesky", placeholder: "whats-hot, trending, or a feed link",
    note: "whats-hot is Bluesky's Discover feed; topic feeds are links like bsky.app/profile/…/feed/…" },
  { kind: "mastodon", label: "Mastodon", placeholder: "mastodon.social or #science",
    note: "A server's trending posts and links, or one hashtag (#science, or #science@fosstodon.org)." },
  { kind: "lemmy", label: "Lemmy community", placeholder: "technology@lemmy.world",
    note: "Reddit-like communities: today's top posts of one (pics@lemmy.world) or a whole server (lemmy.world)." },
  { kind: "hackernews", label: "Hacker News", placeholder: "front page, or search terms" },
  { kind: "youtube", label: "YouTube trending", placeholder: "IN",
    note: "The country's most-popular videos (thumbnails only). Needs a YouTube API key in Settings." },
  { kind: "site", label: "Website", placeholder: "reuters.com or yoursite.com",
    note: "Any site: its RSS feeds when it has them, otherwise the headlines on its homepage." },
  { kind: "rss", label: "RSS feed", placeholder: "https://example.com/feed.xml" },
  { kind: "search", label: "News search", placeholder: "monsoon floods Kerala" },
  { kind: "google_trends", label: "Google Trends", placeholder: "IN" },
  { kind: "wikipedia", label: "Wikipedia most read", placeholder: "en" },
];
const YT_CATEGORIES: [string, string][] = [
  ["", "All videos"], ["25", "News & Politics"], ["28", "Science & Technology"], ["24", "Entertainment"],
  ["23", "Comedy"], ["17", "Sports"], ["20", "Gaming"], ["10", "Music"], ["26", "Howto & Style"], ["27", "Education"],
  ["22", "People & Blogs"], ["1", "Film & Animation"], ["2", "Autos & Vehicles"], ["15", "Pets & Animals"],
  ["19", "Travel & Events"],
];
const SHOW: Record<SourceKind, (v: string) => string> = {
  reddit: (v) => `r/${v}`, site: (v) => v, rss: (v) => v.replace(/^https?:\/\//, ""), search: (v) => `“${v}”`,
  google_trends: (v) => `Google Trends · ${v}`, wikipedia: (v) => `Wikipedia most read · ${v}`,
  bluesky: (v) => v === "whats-hot" ? "Bluesky · What's Hot" : v === "trending" ? "Bluesky · trending topics"
    : `Bluesky feed · ${v.split("/feed/")[1] ?? v}`,
  mastodon: (v) => v.startsWith("#") ? `Mastodon ${v.replace("@", " · ")}` : `Mastodon trending · ${v}`,
  lemmy: (v) => v.includes("@") ? `Lemmy c/${v.replace("@", " · ")}` : `Lemmy top · ${v}`,
  hackernews: (v) => v === "front_page" ? "Hacker News front page" : `Hacker News “${v}”`,
  youtube: (v) => {
    const [region, cat] = v.split(":");
    return `YouTube trending · ${region}${cat ? ` · ${YT_CATEGORIES.find(([id]) => id === cat)?.[1] ?? cat}` : ""}`;
  },
};
const COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#818cf8", "#a855f7", "#ec4899"];
const input = "rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";

function Note({ state }: { state: ActionState }) {
  if (!state) return null;
  return state.error
    ? <p role="alert" className="rounded-md bg-danger-surface px-3 py-2 text-sm text-danger">{state.error}</p>
    : state.message ? <p role="status" className="text-sm text-ok">{state.message}</p> : null;
}

export type FormatOption = { id: string; name: string; kind: string };

function CategoryFields({ c, formats }: { c?: CategoryData; formats: FormatOption[] }) {
  const [color, setColor] = useState(c?.color ?? COLORS[6]);
  // None stored means all of them, so a new category starts with every format ticked.
  const [ticked, setTicked] = useState<string[]>(c?.format_ids.length ? c.format_ids : formats.map((f) => f.id));
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="flex flex-col gap-1 text-sm sm:col-span-2">Name
        <input name="name" required maxLength={60} defaultValue={c?.name} placeholder="Crime & courts" className={input} />
      </label>
      <fieldset className="flex flex-col gap-2 text-sm sm:col-span-2">
        <legend className="mb-1">Formats its ideas may use <span className="text-muted">— the agent picks one per idea; you
          can change it when you swipe</span></legend>
        <div className="flex flex-wrap gap-2">
          {formats.map((f) => (
            <label key={f.id} className={`flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 ${ticked.includes(f.id)
              ? "border-accent text-foreground" : "border-border text-muted"}`}>
              <input type="checkbox" name="format_ids" value={f.id} checked={ticked.includes(f.id)}
                     onChange={() => setTicked((t) => t.includes(f.id) ? t.filter((x) => x !== f.id) : [...t, f.id])}
                     className="size-3.5 accent-accent" />
              {f.name} <span className="text-xs text-muted">{f.kind}</span>
            </label>
          ))}
        </div>
        <span className="text-xs text-muted">
          {ticked.length === formats.length || !ticked.length ? "All formats — and any you make later."
            : `${ticked.length} of ${formats.length} ticked.`}
          {" "}Make more in Formats.</span>
      </fieldset>
      <label className="flex flex-col gap-1 text-sm sm:col-span-2">
        <span>Category prompt <span className="text-muted">— what the agent should look for, take and refuse</span></span>
        <textarea name="brief" rows={6} maxLength={4000} defaultValue={c?.brief}
                  placeholder={"Arrests, verdicts and raids in India with a clear consequence. Prefer stories that come with video.\n"
                    + "Never name victims or minors; nobody is guilty before a verdict. Skip celebrity gossip."}
                  className={input} />
        <span className="text-xs text-muted">Used when finding ideas for this category and when writing each of its scripts.</span>
      </label>
      <label className="flex flex-col gap-1 text-sm">Keywords
        <input name="keywords" maxLength={500} defaultValue={c?.keywords} placeholder="court, arrest, police" className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">Ideas a day
        <input name="ideas_per_batch" type="number" min={1} max={30} defaultValue={c?.ideas_per_batch ?? 2} className={input} />
        <span className="text-xs text-muted">From this category alone, each morning. “More ideas” adds that many again.</span>
      </label>
      <div className="flex flex-col gap-1 text-sm">Colour
        <input type="hidden" name="color" value={color} />
        <div className="flex flex-wrap gap-2">
          {COLORS.map((k) => (
            <button key={k} type="button" aria-label={k} onClick={() => setColor(k)}
                    className={`size-7 rounded-full ${color === k ? "ring-2 ring-foreground ring-offset-2 ring-offset-surface" : ""}`}
                    style={{ background: k }} />
          ))}
        </div>
      </div>
      {c && (
        <label className="flex items-center gap-2 self-end text-sm">
          <input type="checkbox" name="enabled" defaultChecked={c.enabled} className="size-4 accent-accent" />
          Find ideas for this category
        </label>
      )}
    </div>
  );
}

function Sources({ c }: { c: CategoryData }) {
  const [kind, setKind] = useState<SourceKind>("bluesky");
  const [value, setValue] = useState("");
  const [ytCat, setYtCat] = useState("");
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  const meta = KINDS.find((k) => k.kind === kind)!;
  const add = (k: SourceKind, v: string) => start(async () => {
    const r = await addSource(c.id, k, k === "youtube" && ytCat && !v.includes(":") ? `${v.trim()}:${ytCat}` : v);
    setState(r);
    if (r?.ok) setValue("");
  });
  const s = c.suggestion?.result;
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col divide-y divide-border rounded-xl border border-border">
        {c.sources.length === 0 && <li className="p-3 text-sm text-muted">No sources yet — add a community or a site below.</li>}
        {c.sources.map((src) => (
          <li key={src.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 text-sm">
            <span className={`min-w-0 flex-1 truncate ${src.enabled ? "" : "text-muted line-through"}`}>{SHOW[src.kind](src.value)}</span>
            <span className={`text-xs ${src.status === "ok" ? "text-ok" : src.status === "error" ? "text-danger" : "text-muted"}`}
                  title={src.last_error ?? undefined}>
              {src.status === "ok" ? `✓ ${src.last_items ?? 0} items` : src.status === "error" ? "✕ failed" : "checking…"}
            </span>
            <button onClick={() => start(async () => setState(await toggleSource(src.id, !src.enabled)))}
                    className="text-xs text-muted hover:text-foreground">{src.enabled ? "Pause" : "Resume"}</button>
            <button onClick={() => start(async () => setState(await removeSource(src.id)))}
                    className="text-xs text-danger hover:underline">Remove</button>
            {src.status === "error" && src.last_error &&
              <p className="basis-full text-xs text-danger">{src.last_error}</p>}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <select value={kind} onChange={(e) => setKind(e.target.value as SourceKind)} aria-label="Source type" className={input}>
          {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
        </select>
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={meta.placeholder}
               onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(kind, value); } }}
               aria-label="Source" className={`${input} min-w-0 flex-1`} />
        {kind === "youtube" && (
          <select value={ytCat} onChange={(e) => setYtCat(e.target.value)} aria-label="YouTube category" className={input}>
            {YT_CATEGORIES.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        )}
        <button onClick={() => add(kind, value)} disabled={pending}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">Add</button>
      </div>
      {meta.note && <p className="-mt-1 text-xs text-muted">{meta.note}</p>}
      <div className="flex flex-wrap gap-3 text-sm">
        <button disabled={pending || c.checking} onClick={() => start(async () => setState(await categoryJob(c.id, "check")))}
                className="text-accent hover:underline disabled:opacity-50">{c.checking ? "Checking…" : "Check sources now"}</button>
        <button disabled={pending || c.suggestion?.state === "queued" || c.suggestion?.state === "claimed"}
                onClick={() => start(async () => setState(await categoryJob(c.id, "suggest")))}
                className="text-accent hover:underline disabled:opacity-50">
          {c.suggestion?.state === "queued" || c.suggestion?.state === "claimed" ? "Finding sources…" : "Suggest sources"}
        </button>
      </div>
      {s && ((s.communities?.length ?? 0) + (s.lemmy?.length ?? 0) + (s.hashtags?.length ?? 0)
             + (s.sites?.length ?? 0) > 0) && (
        <div className="rounded-xl bg-background p-3 text-sm">
          <p className="font-medium">Suggestions</p>
          <ul className="mt-2 flex flex-col gap-2">
            {s.communities?.map((m) => (
              <li key={m.name} className="flex items-start gap-2">
                <span className="min-w-0 flex-1"><b>r/{m.name}</b>{!m.exists && <span className="text-warn"> · not confirmed</span>}
                  <span className="block text-xs text-muted">{m.why}</span></span>
                <button onClick={() => add("reddit", m.name)} disabled={pending} className="text-xs font-medium text-accent">Add</button>
              </li>
            ))}
            {s.lemmy?.map((m) => (
              <li key={m.name} className="flex items-start gap-2">
                <span className="min-w-0 flex-1"><b>Lemmy c/{m.name}</b>{!m.exists && <span className="text-warn"> · not confirmed</span>}
                  <span className="block text-xs text-muted">{m.why}</span></span>
                <button onClick={() => add("lemmy", m.name)} disabled={pending} className="text-xs font-medium text-accent">Add</button>
              </li>
            ))}
            {s.hashtags?.map((m) => (
              <li key={m.name} className="flex items-start gap-2">
                <span className="min-w-0 flex-1"><b>Mastodon #{m.name}</b>
                  <span className="block text-xs text-muted">{m.why}</span></span>
                <button onClick={() => add("mastodon", `#${m.name}`)} disabled={pending} className="text-xs font-medium text-accent">Add</button>
              </li>
            ))}
            {s.sites?.map((m) => (
              <li key={m.domain} className="flex items-start gap-2">
                <span className="min-w-0 flex-1"><b>{m.domain}</b>
                  <span className={m.feeds ? "text-muted" : "text-warn"}> · {m.feeds ? `${m.feeds} feed${m.feeds === 1 ? "" : "s"}` : "no feed found"}</span>
                  <span className="block text-xs text-muted">{m.why}</span></span>
                <button onClick={() => add("site", m.domain)} disabled={pending} className="text-xs font-medium text-accent">Add</button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <Note state={state} />
    </div>
  );
}

function CategoryCard({ c, formats }: { c: CategoryData; formats: FormatOption[] }) {
  const [state, action, saving] = useActionState<ActionState, FormData>(updateCategory.bind(null, c.id), null);
  const [delState, setDel] = useState<ActionState>(null);
  const [deleting, start] = useTransition();
  const ok = c.sources.filter((s) => s.status === "ok").length;
  return (
    <details className="group rounded-2xl border border-border bg-surface">
      <summary className="flex cursor-pointer list-none items-center gap-3 p-4">
        <span className="size-3 shrink-0 rounded-full" style={{ background: c.color }} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{c.name}</span>
          <span className="block truncate text-xs text-muted">
            {c.sources.length} source{c.sources.length === 1 ? "" : "s"}{c.sources.length ? ` · ${ok} working` : ""}
            {c.enabled ? "" : " · off"}
          </span>
        </span>
        <span className="text-muted transition group-open:rotate-90">›</span>
      </summary>
      <div className="flex flex-col gap-5 border-t border-border p-4">
        <Sources c={c} />
        <form action={action} className="flex flex-col gap-3 border-t border-border pt-4">
          <CategoryFields c={c} formats={formats} />
          <div className="flex flex-wrap items-center gap-3">
            <button disabled={saving} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
              {saving ? "Saving…" : "Save category"}
            </button>
            <button type="button" disabled={deleting}
                    onClick={() => start(async () => setDel(await deleteCategory(c.id)))}
                    className="text-sm text-danger hover:underline">Delete category</button>
          </div>
          <Note state={state} /><Note state={delState} />
        </form>
      </div>
    </details>
  );
}

export function CategoriesSection({ channelId, categories, formats }: {
  channelId: string; categories: CategoryData[]; formats: FormatOption[];
}) {
  const [state, action, adding] = useActionState<ActionState, FormData>(createCategory.bind(null, channelId), null);
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="font-medium">Categories</h2>
        <p className="text-sm text-muted">
          What this channel covers. Each category has its own prompt and sources — communities, social feeds, news
          sites — and its cards carry its tag in Discover.
        </p>
      </div>
      {categories.map((c) => <CategoryCard key={c.id} c={c} formats={formats} />)}
      <details className="rounded-2xl border border-dashed border-border p-4">
        <summary className="cursor-pointer text-sm font-medium">+ New category</summary>
        <form action={action} className="mt-4 flex flex-col gap-3">
          <CategoryFields formats={formats} />
          <button disabled={adding} className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
            {adding ? "Adding…" : "Add category"}
          </button>
          <Note state={state} />
        </form>
      </details>
    </section>
  );
}
