"use client";

import { useState, useTransition } from "react";

import { movePost } from "../actions";

export const DRAG_TYPE = "application/x-corpus-post";

/** A calendar day a post can be dropped on: it moves there (same time of day). */
export function DropDay({ day, past, className, children }: {
  day: string; past: boolean; className: string; children: React.ReactNode;
}) {
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const accepts = (e: React.DragEvent) => !past && e.dataTransfer.types.includes(DRAG_TYPE);
  return (
    <div className={`${className} transition-colors ${over ? "bg-accent/10 outline-2 -outline-offset-2 outline-accent" : ""} ${pending ? "opacity-60" : ""}`}
         onDragOver={(e) => { if (accepts(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setOver(true); } }}
         onDragLeave={() => setOver(false)}
         onDrop={(e) => {
           setOver(false);
           const raw = e.dataTransfer.getData(DRAG_TYPE);
           if (!raw || past) return;
           e.preventDefault();
           const { id, from } = JSON.parse(raw) as { id: string; from: string };
           if (from === day) return;
           setError(null);
           start(async () => {
             const r = await movePost(id, day);
             if (!r?.ok) setError(r?.error ?? "Couldn't move it.");
           });
         }}>
      {children}
      {error && <span className="text-[10px] text-danger">{error}</span>}
    </div>
  );
}
