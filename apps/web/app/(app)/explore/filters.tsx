"use client";

import { useRef, useState } from "react";

import { CATEGORIES, REGIONS, SUBCATEGORIES, WORLDWIDE } from "@/lib/youtube-lists";

// The Explore filters. Picking a category shows its sub-categories at once, and on
// the Trending tab a new country, category or sub-category loads straight away — no
// "Show" press needed (the sub-categories were missed behind it).

const input = "rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";

export function ExploreFilters({ tab, region, category, sub, q, days, shorts, sort, sorts, destinations, to }: {
  tab: "trending" | "search"; region: string; category: string; sub: string; q: string; days: number; shorts: boolean;
  sort: string; sorts: Record<string, string>;
  destinations: { id: string; channel: string; category: string }[]; to: string;
}) {
  const form = useRef<HTMLFormElement>(null);
  const [reg, setReg] = useState(region);
  const [cat, setCat] = useState(category);
  const [subId, setSubId] = useState(sub);
  const subs = tab === "trending" ? SUBCATEGORIES[cat] ?? [] : [];
  const reachable = reg === WORLDWIDE && tab === "trending" && !subId;
  // After React has drawn the new choice (so the form sends it).
  const go = () => { if (tab === "trending") setTimeout(() => form.current?.requestSubmit(), 0); };

  return (
    <form ref={form} action="/explore" className="flex flex-wrap items-end gap-2 rounded-2xl border border-border bg-surface p-3">
      <input type="hidden" name="tab" value={tab} />
      {tab === "search" && (
        <input name="q" defaultValue={q} placeholder="A topic, like “monsoon floods”" required
               className={`${input} min-w-0 flex-1 basis-56`} />
      )}
      <select name="region" value={reg} onChange={(e) => { setReg(e.target.value); go(); }} aria-label="Country" className={input}>
        {REGIONS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
      </select>
      <select name="cat" value={cat} onChange={(e) => { setCat(e.target.value); setSubId(""); go(); }}
              aria-label="Category" className={input}>
        {CATEGORIES.map(([c, n]) => <option key={c} value={c}>{c ? n : tab === "search" ? "Any category" : n}</option>)}
      </select>
      {subs.length > 0 && (
        <select name="sub" value={subId} onChange={(e) => { setSubId(e.target.value); go(); }}
                aria-label="Sub-category" className={`${input} ${subId ? "border-accent" : ""}`}>
          <option value="">All {CATEGORIES.find(([c]) => c === cat)?.[1]}</option>
          {subs.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
      )}
      {(tab === "search" || subId) && (
        <select name="days" defaultValue={String(days)} aria-label="Uploaded within" className={input}>
          <option value="1">Last 24 hours</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option>
        </select>
      )}
      <select name="sort" defaultValue={sort} key={reachable ? "r" : "n"} aria-label="Sort" className={input}>
        {Object.entries(sorts).filter(([k]) => k !== "reach" || reachable)
          .map(([k, n]) => <option key={k} value={k}>{n}</option>)}
      </select>
      <label className="flex items-center gap-2 px-1 text-sm">
        <input type="checkbox" name="shorts" value="1" defaultChecked={shorts} className="size-4 accent-accent" /> Shorts only
      </label>
      {destinations.length > 0 && (
        <select name="to" defaultValue={to} aria-label="Ideas go to" className={input}>
          {destinations.map((d) => <option key={d.id} value={d.id}>Ideas → {d.channel} · {d.category}</option>)}
        </select>
      )}
      <button className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground">
        {tab === "search" ? "Search" : "Show"}
      </button>
    </form>
  );
}
