"use client";

import { useState, useTransition } from "react";

import { pauseDailyIdeas } from "./actions";

const CHOICES: [string, number | "forever"][] = [
  ["1 day", 1], ["3 days", 3], ["1 week", 7], ["2 weeks", 14], ["Until I resume", "forever"],
];

/** The channel's morning batch of ideas: on, off (channel setting), or paused for a while. */
export function DailyIdeasPause({ channelId, daily, at, paused }: {
  channelId: string; daily: boolean; at: string; paused: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const run = (days: number | "forever" | null) => start(async () => {
    const r = await pauseDailyIdeas(channelId, days);
    setError(r?.ok ? null : r?.error ?? "Couldn't change it.");
    setOpen(false);
  });
  if (!daily) return null;
  return (
    <div className="relative flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
      {paused ? (
        <>
          <span className="rounded-full bg-warn/15 px-2 py-0.5 text-warn">
            Daily ideas paused {paused === "forever" ? "until you resume" : `until ${paused}`}
          </span>
          <button disabled={pending} onClick={() => run(null)} className="font-medium text-accent hover:underline">
            Resume
          </button>
        </>
      ) : (
        <>
          <span>New ideas every morning at {at}</span>
          <button disabled={pending} onClick={() => setOpen((o) => !o)} aria-expanded={open}
                  className="font-medium text-accent hover:underline">Pause daily ideas</button>
        </>
      )}
      {open && (
        <div role="menu" className="absolute top-6 left-0 z-30 flex flex-col rounded-xl border border-border bg-surface p-1 shadow-xl">
          {CHOICES.map(([label, days]) => (
            <button key={label} role="menuitem" onClick={() => run(days)}
                    className="rounded-lg px-3 py-1.5 text-left text-sm text-foreground hover:bg-background">
              {label}
            </button>
          ))}
        </div>
      )}
      {error && <span className="text-danger">{error}</span>}
    </div>
  );
}
