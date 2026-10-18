"use client";

import Link from "next/link";
import { useMemo, useState, useTransition } from "react";

import { bulkPostAction, type BulkResult } from "./table-actions";

// The Library's table: every post of the channel in one row each — stage, script,
// shots, length, look, cost, GPU time, where it went live and how it did — with
// actions on one row or on every ticked row. Sorted and searched in the browser;
// the server sends the rows ready to show.

export type TableRow = {
  id: string; title: string; topic: string; date: string; time: string | null; kind: string; template: string;
  stage: string; dot: string; stageOrder: number; error: string | null; status: string; goAhead: boolean;
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

// What each action may touch (the database refuses the rest anyway).
type Action = "go_ahead" | "approve" | "write" | "delete";
const CAN: Record<Action, (r: TableRow) => boolean> = {
  go_ahead: (r) => ["draft", "failed", "awaiting_approval", "approved"].includes(r.status)
    || (r.status === "scripting" && !r.goAhead),
  approve: (r) => r.status === "awaiting_approval",
  write: (r) => ["draft", "awaiting_approval", "failed"].includes(r.status),
  delete: (r) => ["draft", "scripting", "awaiting_approval", "approved", "failed", "cancelled"].includes(r.status),
};
const ACTION_LABEL: Record<Action, string> = {
  go_ahead: "Approve & render", approve: "Approve script", write: "Write script", delete: "Delete",
};
// The one-click action on a row, named for where that post is.
const ROW_GO: Record<string, string> = {
  draft: "Make it", failed: "Retry", awaiting_approval: "Approve & render", approved: "Render", scripting: "Then render",
};

const PLATFORM = { youtube: "YouTube", instagram: "Instagram" } as const;

const inr = (n: number) => `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const num = (n: number | null) => (n == null ? "—" : n.toLocaleString("en-IN"));
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

export function OverviewTable({ rows }: { rows: TableRow[] }) {
  const [sort, setSort] = useState<{ key: Key; desc: boolean }>({ key: "date", desc: true });
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  // An action waiting for its second click (rendering spends money; deleting is final).
  const [confirm, setConfirm] = useState<{ action: Action; ids: string[] } | null>(null);
  const [result, setResult] = useState<BulkResult | null>(null);
  const [pending, start] = useTransition();

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

  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);
  const selected = [...picked].map((id) => byId.get(id)).filter((r): r is TableRow => !!r);
  const sum = (f: (r: TableRow) => number | null) => shown.reduce((t, r) => t + (f(r) ?? 0), 0);
  const unpriced = sum((r) => r.cost.unpriced);
  // What a render has cost so far, on average: the estimate shown before rendering more.
  const rendered = rows.filter((r) => r.cost.gpu > 0);
  const perRender = rendered.length ? rendered.reduce((t, r) => t + r.cost.total, 0) / rendered.length : null;

  function run(action: Action, ids: string[]) {
    setConfirm(null);
    start(async () => {
      const r = await bulkPostAction({ ids, action });
      setResult(r);
      setPicked((p) => new Set([...p].filter((id) => !ids.includes(id) || r.failed.some((f) => f.id === id))));
    });
  }

  function ask(action: Action, ids: string[]) {
    if (action === "approve" || action === "write") return run(action, ids);
    setConfirm({ action, ids });
  }

  const toggle = (id: string) => setPicked((p) => {
    const n = new Set(p);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const allShown = shown.length > 0 && shown.every((r) => picked.has(r.id));

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

      {(selected.length > 0 || confirm || result) && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-sm">
          {confirm ? (
            <>
              <span>
                {confirm.action === "delete"
                  ? `Delete ${confirm.ids.length} post${confirm.ids.length === 1 ? "" : "s"}? This can't be undone.`
                  : `Approve and render ${confirm.ids.length} post${confirm.ids.length === 1 ? "" : "s"}?` +
                    (perRender ? ` About ${inr(perRender * confirm.ids.length)} going by your past renders.` : "") +
                    " Scripts not written yet are written first."}
              </span>
              <button onClick={() => run(confirm.action, confirm.ids)} disabled={pending}
                      className={`rounded-full px-3 py-1 font-medium text-white ${confirm.action === "delete" ? "bg-danger" : "bg-accent"}`}>
                {confirm.action === "delete" ? "Delete" : "Yes, make them"}
              </button>
              <button onClick={() => setConfirm(null)} className="rounded-full px-3 py-1 text-muted hover:text-foreground">Cancel</button>
            </>
          ) : selected.length > 0 ? (
            <>
              <span className="font-medium">{selected.length} selected</span>
              {(Object.keys(ACTION_LABEL) as Action[]).map((a) => {
                const ids = selected.filter(CAN[a]).map((r) => r.id);
                return (
                  <button key={a} onClick={() => ask(a, ids)} disabled={!ids.length || pending}
                          title={ids.length < selected.length ? `${selected.length - ids.length} of the selected can't be` : undefined}
                          className={`rounded-full border px-3 py-1 disabled:opacity-40 ${a === "delete"
                            ? "border-danger/40 text-danger hover:bg-danger/10" : "border-border hover:border-accent"}`}>
                    {ACTION_LABEL[a]}{ids.length !== selected.length ? ` (${ids.length})` : ""}
                  </button>
                );
              })}
              <button onClick={() => setPicked(new Set())} className="ml-auto text-muted hover:text-foreground">Clear</button>
            </>
          ) : null}
          {pending && <span className="text-muted">Working…</span>}
          {result && !confirm && !pending && (
            <span className={`w-full text-xs ${result.ok ? "text-ok" : "text-warn"}`}>
              {result.message}.
              {result.failed.map((f) => (
                <span key={f.id} className="block text-muted">{byId.get(f.id)?.title ?? "A post"}: {f.error}</span>
              ))}
            </span>
          )}
        </div>
      )}

      <div className="max-h-[calc(100dvh-15rem)] min-h-64 overflow-auto rounded-2xl border border-border bg-surface">
        <table className="w-full min-w-[1320px] border-separate border-spacing-0 text-left text-sm">
          <thead className="text-xs text-muted">
            <tr>
              {COLS.map((c) => {
                const on = sort.key === c.key;
                return (
                  <th key={c.key}
                      className={`sticky top-0 z-10 whitespace-nowrap border-b border-border bg-surface px-3 py-2 font-medium ${c.num ? "text-right" : ""} ${c.key === "title" ? "left-0 z-20" : ""}`}>
                    <span className="flex items-center gap-2">
                      {c.key === "title" && (
                        <input type="checkbox" aria-label="Select all shown" checked={allShown}
                               onChange={() => setPicked(allShown ? new Set() : new Set(shown.map((r) => r.id)))} />
                      )}
                      <button onClick={() => setSort({ key: c.key, desc: on ? !sort.desc : c.key !== "title" })}
                              className={`hover:text-foreground ${c.num ? "ml-auto" : ""} ${on ? "text-foreground" : ""}`}>
                        {c.label}{on ? (sort.desc ? " ↓" : " ↑") : ""}
                      </button>
                    </span>
                  </th>
                );
              })}
              <th className="sticky top-0 z-10 border-b border-border bg-surface px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className="group align-top [&>td]:border-b [&>td]:border-border/60 [&>td]:group-hover:bg-background">
                <td className="sticky left-0 z-[5] max-w-[19rem] bg-surface px-3 py-2">
                  <div className="flex gap-2">
                    <input type="checkbox" aria-label={`Select ${r.title}`} checked={picked.has(r.id)}
                           onChange={() => toggle(r.id)} className="mt-1 shrink-0" />
                    <div className="min-w-0">
                      <Link href={`/posts/${r.id}`} className="line-clamp-2 font-medium hover:text-accent">{r.title}</Link>
                      {r.title !== r.topic && <span className="line-clamp-1 text-xs text-muted">{r.topic}</span>}
                    </div>
                  </div>
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
                  {r.goAhead && <span className="block text-xs text-accent">then renders on its own</span>}
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
                <td className="whitespace-nowrap px-3 py-2 text-xs text-muted tabular-nums">{r.updated}</td>
                <td className="whitespace-nowrap px-3 py-2">
                  <span className="flex items-center gap-1.5 text-xs">
                    {CAN.go_ahead(r) && (
                      <button onClick={() => ask("go_ahead", [r.id])} disabled={pending}
                              className="rounded-full bg-accent px-2.5 py-1 font-medium text-white disabled:opacity-50">
                        {ROW_GO[r.status] ?? "Make it"}
                      </button>
                    )}
                    {CAN.approve(r) && (
                      <button onClick={() => ask("approve", [r.id])} disabled={pending}
                              className="rounded-full border border-border px-2.5 py-1 hover:border-accent disabled:opacity-50">
                        Approve
                      </button>
                    )}
                    <Link href={`/posts/${r.id}`} className="rounded-full border border-border px-2.5 py-1 hover:border-accent">Edit</Link>
                    {CAN.delete(r) && (
                      <button onClick={() => ask("delete", [r.id])} disabled={pending} aria-label={`Delete ${r.title}`}
                              className="rounded-full border border-danger/40 px-2.5 py-1 text-danger hover:bg-danger/10 disabled:opacity-50">
                        Delete
                      </button>
                    )}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
          {shown.length > 1 && (
            <tfoot className="text-xs text-muted">
              <tr>
                <td className="sticky left-0 bg-surface px-3 py-2 font-medium text-foreground" colSpan={1}>Total</td>
                <td colSpan={4} />
                <td className="px-3 py-2 text-right tabular-nums">{sum((r) => r.shotsDone)}/{sum((r) => r.shots)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{clock(sum((r) => r.seconds))}</td>
                <td />
                <td className="px-3 py-2 text-right tabular-nums text-foreground">
                  {inr(sum((r) => r.cost.total))}{unpriced > 0 && <span className="block text-warn">+{unpriced} unpriced</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{sum((r) => r.gpuMinutes).toFixed(1)} min</td>
                <td />
                <td className="px-3 py-2 text-right tabular-nums">{num(sum((r) => r.views))}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      <p className="text-xs text-muted">
        <b className="font-medium text-foreground">Approve &amp; render</b> takes a post the rest of the way: it writes the
        script if there isn&apos;t one, approves it, and renders once its shots are ready — no stops for review.
        A post can be deleted until it is rendered. Cost is what each post spent plus its share of the idea search that
        found it; hover a cost for the breakdown.
      </p>
    </div>
  );
}
