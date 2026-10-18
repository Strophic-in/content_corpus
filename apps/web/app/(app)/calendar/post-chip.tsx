"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import { bulkPostAction } from "../library/table-actions";

// A post on a calendar day: tap it to open, or delete it there — anything not being
// rendered, scheduled or posted (the database refuses those). The × asks once more.

const DELETABLE = new Set(["draft", "scripting", "awaiting_approval", "approved", "failed", "cancelled", "ready",
  "needs_review"]);

export function PostChip({ id, topic, time, status, badge }: {
  id: string; topic: string; time: string | null; status: string; badge: { label: string; className: string };
}) {
  const [armed, setArmed] = useState(false);
  const [gone, setGone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  if (gone) return null;

  const remove = () => start(async () => {
    const r = await bulkPostAction({ ids: [id], action: "delete" });
    if (r.ok) setGone(true);
    else { setArmed(false); setError(r.failed[0]?.error ?? r.message); }
  });

  return (
    <div className={`group relative rounded-md transition-opacity ${pending ? "opacity-40" : ""}`}>
      <Link href={`/posts/${id}`} className="flex flex-col gap-1 rounded-md p-1 pr-6 hover:bg-background">
        <span className="line-clamp-2 text-xs font-medium sm:text-sm">
          {time && <span className="mr-1 text-muted tabular-nums">{time}</span>}
          {topic}
        </span>
        <span className={`w-fit rounded px-1.5 py-0.5 text-[10px] font-medium sm:text-xs ${badge.className}`}>{badge.label}</span>
      </Link>
      {DELETABLE.has(status) && (armed ? (
        <span className="absolute inset-x-0 bottom-0 z-10 flex items-center gap-1 rounded-md border border-danger/40 bg-surface p-1 text-[11px] shadow-lg">
          <button onClick={remove} disabled={pending}
                  className="flex-1 rounded bg-danger px-1.5 py-1 font-medium text-white">
            {pending ? "Deleting…" : "Delete"}
          </button>
          <button onClick={() => setArmed(false)} className="px-1.5 py-1 text-muted hover:text-foreground">Keep</button>
        </span>
      ) : (
        <button onClick={() => { setArmed(true); setError(null); }} aria-label={`Delete ${topic}`} title="Delete"
                className="absolute top-1 right-1 grid size-5 place-items-center rounded-full border border-border bg-surface text-muted transition hover:border-danger/50 hover:bg-danger/10 hover:text-danger">
          <svg viewBox="0 0 24 24" aria-hidden className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2.2}
               strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      ))}
      {error && <span className="block px-1 text-[10px] text-danger">{error}</span>}
    </div>
  );
}
