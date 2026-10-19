"use client";

import Image from "next/image";
import { useState } from "react";

// Real screens of the app (the demo account), one at a time.
const SHOTS = [
  { id: "post", label: "Every step, live", src: "/site/post.webp",
    text: "Each video shows where it is — sources and assets, script, your review, voice, render, packaging, posting — and what to do next." },
  { id: "calendar", label: "Calendar", src: "/site/calendar.webp",
    text: "The month at a glance. Drag a video to another day; scheduled posts move with it." },
  { id: "table", label: "Library table", src: "/site/table.webp",
    text: "Every video in one table: stage, script, shots, GPU time, cost and views. Approve, render or delete in bulk." },
  { id: "styles", label: "Caption & cover styles", src: "/site/styles.webp",
    text: "Twelve caption styles and thirteen cover layouts — Jev picks the best fit for each story." },
  { id: "voices", label: "Voices", src: "/site/voices.webp",
    text: "Forty-four narrators in English and Hindi, free and AI. Hear each one, switch on the ones you like." },
  { id: "formats", label: "Formats", src: "/site/formats.webp",
    text: "Twenty-two formats: explainers, before/after, countdowns, footage with captions, carousels, picture cards." },
] as const;

export function Showcase() {
  const [at, setAt] = useState(0);
  const shot = SHOTS[at];
  return (
    <div className="flex flex-col gap-5">
      <div role="tablist" aria-label="Screens" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:justify-center sm:px-0">
        {SHOTS.map((s, i) => (
          <button key={s.id} role="tab" aria-selected={i === at} onClick={() => setAt(i)}
                  className={`shrink-0 rounded-full border px-3.5 py-1.5 text-sm font-medium transition ${
                    i === at ? "border-accent bg-accent text-accent-foreground" : "border-border bg-surface text-muted hover:text-foreground"}`}>
            {s.label}
          </button>
        ))}
      </div>
      <p className="mx-auto max-w-2xl text-center text-muted">{shot.text}</p>
      <div className="browser-frame mx-auto w-full max-w-5xl">
        <div className="flex items-center gap-1.5 border-b border-border px-4 py-2.5" aria-hidden>
          <span className="size-2.5 rounded-full bg-[#ff5f57]" /><span className="size-2.5 rounded-full bg-[#febc2e]" />
          <span className="size-2.5 rounded-full bg-[#28c840]" />
          <span className="ml-3 truncate rounded-md bg-surface-2 px-3 py-0.5 text-xs text-muted">content-corpus.strophic.in</span>
        </div>
        <div className="relative aspect-[16/10] bg-white">
          {SHOTS.map((s, i) => (
            <Image key={s.id} src={s.src} alt={`Content Corpus — ${s.label}`} fill sizes="(min-width: 1024px) 1024px, 100vw"
                   className={`object-cover object-top transition-opacity duration-500 ${i === at ? "opacity-100" : "opacity-0"}`}
                   priority={i === 0} />
          ))}
        </div>
      </div>
    </div>
  );
}
