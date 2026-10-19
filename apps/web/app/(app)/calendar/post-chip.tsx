"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import { movePost } from "../actions";
import { bulkPostAction } from "../library/table-actions";
import { DRAG_TYPE } from "./drop-day";

// A post on a calendar day: tap it to open, or delete it there — anything not being
// rendered, scheduled or posted (the database refuses those). The × asks once more.

const DELETABLE = new Set(["draft", "scripting", "awaiting_approval", "approved", "failed", "cancelled", "ready",
  "needs_review"]);
// Drag to another day (or, on a phone, "Move" and pick one): not while it is being
// rendered or put together, nor once it is posted.
const FIXED = new Set(["rendering", "post_processing", "published", "cancelled"]);

export function PostChip({ id, topic, time, status, badge, day, today }: {
  id: string; topic: string; time: string | null; status: string; badge: { label: string; className: string };
  day: string; today: string;
}) {
  const movable = !FIXED.has(status);
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

  const moveTo = (date: string) => {
    if (!date || date === day) return;
    setError(null);
    start(async () => {
      const r = await movePost(id, date);
      if (!r?.ok) setError(r?.error ?? "Couldn't move it.");
    });
  };

  return (
    <div className={`group relative rounded-md transition-opacity ${pending ? "opacity-40" : ""} ${movable ? "cursor-grab active:cursor-grabbing" : ""}`}
         draggable={movable}
         onDragStart={(e) => {
           e.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ id, from: day }));
           e.dataTransfer.effectAllowed = "move";
         }}>
      <Link href={`/posts/${id}`} draggable={false} className="flex flex-col gap-1 rounded-md p-1 pr-6 hover:bg-background">
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
      {movable && (
        // A phone has no drag and drop: "Move" opens the date picker.
        <label className="mx-1 mb-1 inline-flex w-fit cursor-pointer items-center gap-1 rounded text-[11px] text-muted hover:text-accent sm:hidden">
          <svg viewBox="0 0 24 24" aria-hidden className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2}
               strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></svg>
          Move
          <input type="date" min={today} defaultValue={day} aria-label={`Move ${topic} to another day`}
                 onChange={(e) => moveTo(e.target.value)} className="sr-only" />
        </label>
      )}
      {error && <span className="block px-1 text-[10px] text-danger">{error}</span>}
    </div>
  );
}
