"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

// The Library's table: every post of the channel in one row each — stage, script,
// shots, length, look, cost, GPU time, where it went live and how it did.
// Sorted and searched in the browser; the server sends the rows ready to show.

export type TableRow = {
  id: string; title: string; topic: string; date: string; time: string | null; kind: string; template: string;
  stage: string; dot: string; stageOrder: number; error: string | null;
  script: string | null; scriptScore: number | null; versions: number;
  shots: number; shotsDone: number; slides: number; seconds: number | null; look: string | null;
  cost: { writing: number; pictures: number; voice: number; gpu: number; idea: number; total: number; unpriced: number };
  gpuMinutes: number | null;
  live: { platform: "youtube" | "instagram"; url: string | null }[];
  views: number | null; likes: number | null; comments: number | null; updated: string;
};

type Key = "title" | "date" | "kind" | "stage" | "script" | "shots" | "seconds" | "look" | "cost" | "gpu" | "posted"
  | "views" | "updated";

const COLS: { key: Key; label: string; num?: boolean; value: (r: TableRow) => string | number }[] = [
  { key: "title", label: "Post", value: (r) => r.title.toLowerCase() },
  { key: "date", label: "Date", value: (r) => `${r.date} ${r.time ?? ""}` },
  { key: "kind", label: "Format", value: (r) => `${r.kind} ${r.template}` },
  { key: "stage", label: "Stage", value: (r) => r.stageOrder },
  { key: "script", label: "Script", value: (r) => r.scriptScore ?? -1 },
  { key: "shots", label: "Shots", num: true, value: (r) => r.shots || r.slides },
  { key: "seconds", label: "Length", num: true, value: (r) => r.seconds ?? -1 },
  { key: "look", label: "Look", value: (r) => r.look ?? "" },
  { key: "cost", label: "Cost", num: true, value: (r) => r.cost.total },
  { key: "gpu", label: "GPU time", num: true, value: (r) => r.gpuMinutes ?? -1 },
  { key: "posted", label: "Posted", value: (r) => r.live.length },
  { key: "views", label: "Views", num: true, value: (r) => r.views ?? -1 },
  { key: "updated", label: "Updated", value: (r) => r.updated },
];

const PLATFORM = { youtube: "YouTube", instagram: "Instagram" } as const;

const inr = (n: number) => `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const num = (n: number | null) => (n == null ? "—" : n.toLocaleString("en-IN"));
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

export function OverviewTable({ rows }: { rows: TableRow[] }) {
  const [sort, setSort] = useState<{ key: Key; desc: boolean }>({ key: "date", desc: true });
  const [q, setQ] = useState("");

  const shown = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const col = COLS.find((c) => c.key === sort.key)!;
    return rows
      .filter((r) => {
        const hay = `${r.title} ${r.topic} ${r.stage} ${r.kind} ${r.template} ${r.look ?? ""}`.toLowerCase();
        return words.every((w) => hay.includes(w));
      })
      .sort((a, b) => {
        const x = col.value(a), y = col.value(b);
        const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
        return sort.desc ? -c : c;
      });
  }, [rows, q, sort]);

  const sum = (f: (r: TableRow) => number | null) => shown.reduce((t, r) => t + (f(r) ?? 0), 0);
  const unpriced = sum((r) => r.cost.unpriced);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, stage, format, look…"
               className="w-full max-w-xs rounded-lg border border-border bg-surface px-3 py-1.5 text-sm outline-none focus:border-accent" />
        <span className="text-sm text-muted">
          {shown.length} post{shown.length === 1 ? "" : "s"} · {inr(sum((r) => r.cost.total))} spent
          · {Math.round(sum((r) => r.gpuMinutes))} GPU min · {num(sum((r) => r.views))} views
        </span>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-border bg-surface">
        <table className="w-full min-w-[1200px] text-left text-sm">
          <thead className="border-b border-border text-xs text-muted">
            <tr>
              {COLS.map((c) => {
                const on = sort.key === c.key;
                return (
                  <th key={c.key} className={`whitespace-nowrap px-3 py-2 font-medium ${c.num ? "text-right" : ""}`}>
                    <button onClick={() => setSort({ key: c.key, desc: on ? !sort.desc : c.key !== "title" })}
                            className={`hover:text-foreground ${on ? "text-foreground" : ""}`}>
                      {c.label}{on ? (sort.desc ? " ↓" : " ↑") : ""}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className="border-b border-border/60 align-top last:border-0 hover:bg-background/60">
                <td className="max-w-[18rem] px-3 py-2">
                  <Link href={`/posts/${r.id}`} className="line-clamp-2 font-medium hover:text-accent">{r.title}</Link>
                  {r.title !== r.topic && <span className="line-clamp-1 text-xs text-muted">{r.topic}</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-2 tabular-nums">
                  {r.date}{r.time && <span className="block text-xs text-muted">{r.time}</span>}
                </td>
                <td className="px-3 py-2">
                  {r.kind}<span className="block text-xs text-muted">{r.template}</span>
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  <span className="inline-flex items-center gap-1.5">
                    <span className={`size-1.5 rounded-full ${r.dot}`} />{r.stage}
                  </span>
                  {r.error && <span className="block max-w-[14rem] truncate text-xs text-danger" title={r.error}>{r.error}</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  {r.script ?? <span className="text-muted">Not written</span>}
                  {r.script && (
                    <span className="block text-xs text-muted">
                      {r.scriptScore != null ? `scored ${r.scriptScore}/10` : ""}
                      {r.versions > 1 ? `${r.scriptScore != null ? " · " : ""}${r.versions} versions` : ""}
                    </span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                  {r.slides ? `${r.slides} slides` : r.shots ? `${r.shotsDone}/${r.shots}` : "—"}
                  {!r.slides && r.shots > 0 && <span className="block text-xs text-muted">rendered</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{r.seconds != null ? clock(r.seconds) : "—"}</td>
                <td className="px-3 py-2 text-xs">{r.look ?? <span className="text-muted">—</span>}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums"
                    title={[["Writing", r.cost.writing], ["Pictures", r.cost.pictures], ["Voice", r.cost.voice],
                            ["GPU", r.cost.gpu], ["Idea search share", r.cost.idea]]
                      .filter(([, v]) => (v as number) > 0).map(([k, v]) => `${k}: ${inr(v as number)}`).join("\n")}>
                  {r.cost.total > 0 ? inr(r.cost.total) : "—"}
                  {r.cost.gpu > 0 && <span className="block text-xs text-muted">GPU {inr(r.cost.gpu)}</span>}
                  {r.cost.unpriced > 0 && <span className="block text-xs text-warn">+{r.cost.unpriced} unpriced</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {r.gpuMinutes != null ? `${r.gpuMinutes.toFixed(1)} min` : "—"}
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  {r.live.length ? r.live.map((l) => (
                    l.url
                      ? <a key={l.platform} href={l.url} target="_blank" rel="noreferrer" className="block text-accent hover:underline">{PLATFORM[l.platform]} ↗</a>
                      : <span key={l.platform} className="block">{PLATFORM[l.platform]}</span>
                  )) : <span className="text-muted">—</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                  {num(r.views)}
                  {(r.likes != null || r.comments != null) && (
                    <span className="block text-xs text-muted">{num(r.likes)} ♥ · {num(r.comments)} 💬</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-xs text-muted tabular-nums">{r.updated.slice(0, 16).replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
          {shown.length > 1 && (
            <tfoot className="border-t border-border text-xs text-muted">
              <tr>
                <td className="px-3 py-2 font-medium text-foreground" colSpan={5}>Total</td>
                <td className="px-3 py-2 text-right tabular-nums">{sum((r) => r.shotsDone)}/{sum((r) => r.shots)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{clock(sum((r) => r.seconds))}</td>
                <td />
                <td className="px-3 py-2 text-right tabular-nums text-foreground">
                  {inr(sum((r) => r.cost.total))}{unpriced > 0 && <span className="block text-warn">+{unpriced} unpriced</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{sum((r) => r.gpuMinutes).toFixed(1)} min</td>
                <td />
                <td className="px-3 py-2 text-right tabular-nums">{num(sum((r) => r.views))}</td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      <p className="text-xs text-muted">
        Cost is what each post spent (writing, pictures, voice, GPU) plus its share of the idea search that found it;
        hover a cost for the breakdown. Times are the channel&apos;s. Views are the latest fetched from each platform.
      </p>
    </div>
  );
}
