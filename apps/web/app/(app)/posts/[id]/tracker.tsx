import type { Step } from "@/lib/pipeline";

// The post's way from idea to posted reel: each step done, happening now, waiting for
// the owner, still to come, or where it stopped. Refreshes with the page (AutoRefresh).

const DOT: Record<Step["state"], string> = {
  done: "bg-ok text-white",
  active: "bg-accent text-white",
  waiting: "bg-warn text-white",
  failed: "bg-danger text-white",
  todo: "bg-border text-muted",
  skipped: "bg-border text-muted",
};

function Mark({ state, n }: { state: Step["state"]; n: number }) {
  if (state === "done")
    return <svg viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2.5}
                strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M3.5 8.5l3 3 6-7" /></svg>;
  if (state === "failed") return <span aria-hidden className="text-xs font-bold">!</span>;
  if (state === "active")
    return <span aria-hidden className="size-2.5 animate-ping rounded-full bg-white/90" />;
  return <span aria-hidden className="text-[11px] font-semibold tabular-nums">{n}</span>;
}

export function Tracker({ steps }: { steps: Step[] }) {
  const shown = steps.filter((s) => s.state !== "skipped");
  return (
    <ol className="flex flex-col">
      {shown.map((s, i) => {
        const last = i === shown.length - 1;
        return (
          <li key={s.id} className="relative flex gap-3 pb-4 last:pb-0"
              aria-current={s.state === "active" || s.state === "waiting" ? "step" : undefined}>
            {!last && (
              <span aria-hidden className={`absolute top-7 left-[13px] h-[calc(100%-1.5rem)] w-0.5 rounded-full ${
                s.state === "done" ? "bg-ok/60" : "bg-border"}`} />
            )}
            <span className={`relative z-[1] grid size-7 shrink-0 place-items-center rounded-full transition-colors ${DOT[s.state]}`}>
              <Mark state={s.state} n={i + 1} />
            </span>
            <span className="flex min-w-0 flex-col pt-0.5">
              <span className={`text-sm ${s.state === "todo" ? "text-muted" : "font-medium"}`}>
                {s.label}
                {s.state === "waiting" && <span className="ml-2 rounded-full bg-warn/15 px-2 py-0.5 text-[11px] font-medium text-warn">Your turn</span>}
                {s.state === "active" && <span className="ml-2 rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent">Now</span>}
              </span>
              {s.detail && <span className="text-xs text-muted">{s.detail}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
