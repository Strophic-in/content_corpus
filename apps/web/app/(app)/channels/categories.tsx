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
  id: string; name: string; color: string; brief: string; keywords: string; format_id: string | null;
  ideas_per_batch: number; enabled: boolean; sources: SourceRow[]; checking: boolean;
  suggestion: { state: string; result: { communities?: { name: string; exists: boolean; why: string }[];
                                         sites?: { domain: string; feeds: number; why: string }[] } | null } | null;
};

const KINDS: { kind: SourceKind; label: string; placeholder: string }[] = [
  { kind: "reddit", label: "Reddit community", placeholder: "r/worldnews" },
  { kind: "site", label: "News site", placeholder: "reuters.com" },
  { kind: "rss", label: "RSS feed", placeholder: "https://example.com/feed.xml" },
  { kind: "search", label: "News search", placeholder: "monsoon floods Kerala" },
  { kind: "google_trends", label: "Google Trends", placeholder: "IN" },
  { kind: "wikipedia", label: "Wikipedia most read", placeholder: "en" },
];
const SHOW: Record<SourceKind, (v: string) => string> = {
  reddit: (v) => `r/${v}`, site: (v) => v, rss: (v) => v.replace(/^https?:\/\//, ""), search: (v) => `“${v}”`,
  google_trends: (v) => `Google Trends · ${v}`, wikipedia: (v) => `Wikipedia most read · ${v}`,
};
const COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#818cf8", "#a855f7", "#ec4899"];
const input = "rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";

function Note({ state }: { state: ActionState }) {
  if (!state) return null;
  return state.error
    ? <p role="alert" className="rounded-md bg-danger-surface px-3 py-2 text-sm text-danger">{state.error}</p>
    : state.message ? <p role="status" className="text-sm text-ok">{state.message}</p> : null;
}

function CategoryFields({ c, formats }: { c?: CategoryData; formats: { id: string; name: string }[] }) {
  const [color, setColor] = useState(c?.color ?? COLORS[6]);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="flex flex-col gap-1 text-sm">Name
        <input name="name" required maxLength={60} defaultValue={c?.name} placeholder="Crime & courts" className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">Format (how its videos are made)
        <select name="format_id" defaultValue={c?.format_id ?? ""} className={input}>
          <option value="">The channel&apos;s default</option>
          {formats.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm sm:col-span-2">Brief — what to take and what to refuse
        <textarea name="brief" rows={3} maxLength={2000} defaultValue={c?.brief}
                  placeholder="Arrests, verdicts and raids with a clear consequence. Never name victims or minors; nobody is guilty before a verdict."
                  className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">Keywords
        <input name="keywords" maxLength={500} defaultValue={c?.keywords} placeholder="court, arrest, police" className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">Ideas per batch
        <input name="ideas_per_batch" type="number" min={1} max={30} defaultValue={c?.ideas_per_batch ?? 6} className={input} />
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
  const [kind, setKind] = useState<SourceKind>("reddit");
  const [value, setValue] = useState("");
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  const meta = KINDS.find((k) => k.kind === kind)!;
  const add = (k: SourceKind, v: string) => start(async () => {
    const r = await addSource(c.id, k, v);
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
        <button onClick={() => add(kind, value)} disabled={pending}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">Add</button>
      </div>
      <div className="flex flex-wrap gap-3 text-sm">
        <button disabled={pending || c.checking} onClick={() => start(async () => setState(await categoryJob(c.id, "check")))}
                className="text-accent hover:underline disabled:opacity-50">{c.checking ? "Checking…" : "Check sources now"}</button>
        <button disabled={pending || c.suggestion?.state === "queued" || c.suggestion?.state === "claimed"}
                onClick={() => start(async () => setState(await categoryJob(c.id, "suggest")))}
                className="text-accent hover:underline disabled:opacity-50">
          {c.suggestion?.state === "queued" || c.suggestion?.state === "claimed" ? "Finding communities…" : "Suggest communities and sites"}
        </button>
      </div>
      {s && ((s.communities?.length ?? 0) + (s.sites?.length ?? 0) > 0) && (
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

function CategoryCard({ c, formats }: { c: CategoryData; formats: { id: string; name: string }[] }) {
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
  channelId: string; categories: CategoryData[]; formats: { id: string; name: string }[];
}) {
  const [state, action, adding] = useActionState<ActionState, FormData>(createCategory.bind(null, channelId), null);
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="font-medium">Categories</h2>
        <p className="text-sm text-muted">
          What this channel covers. Each category has its own sources — Reddit communities, news sites, feeds — and
          its cards carry its tag in Discover.
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
