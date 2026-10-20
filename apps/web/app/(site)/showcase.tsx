"use client";

import { AnimatePresence, motion } from "motion/react";
import Image from "next/image";
import { useState } from "react";

// Real screens of the app (the demo account), one feed at a time, like a gallery's
// camera switcher.
const SHOTS = [
  { id: "post", label: "Every step, live", src: "/site/post.webp",
    text: "Each video shows where it is (sources and assets, script, your review, voice, render, packaging, posting) and what to do next." },
  { id: "calendar", label: "Calendar", src: "/site/calendar.webp",
    text: "The month at a glance. Drag a video to another day; scheduled posts move with it." },
  { id: "table", label: "Library", src: "/site/table.webp",
    text: "Every video in one table: stage, script, shots, GPU time, cost and views. Approve, render or delete in bulk." },
  { id: "styles", label: "Styles", src: "/site/styles.webp",
    text: "Twelve caption styles and thirteen cover layouts. Jev picks the best fit for each story." },
  { id: "voices", label: "Voices", src: "/site/voices.webp",
    text: "Forty-four narrators in English and Hindi, free and AI. Hear each one, switch on the ones you like." },
  { id: "formats", label: "Formats", src: "/site/formats.webp",
    text: "Twenty-two formats: explainers, before/after, countdowns, footage with captions, carousels, picture cards." },
] as const;

export function Showcase() {
  const [at, setAt] = useState(0);
  const shot = SHOTS[at];
  return (
    <div className="flex flex-col gap-6">
      <div role="tablist" aria-label="Screens"
           className="no-scrollbar -mx-4 flex gap-1 overflow-x-auto border-y border-border px-4 sm:mx-0 sm:justify-center sm:px-0">
        {SHOTS.map((s, i) => (
          <button key={s.id} role="tab" aria-selected={i === at} onClick={() => setAt(i)}
                  className={`relative shrink-0 px-3 py-3 text-left transition-colors ${i === at ? "text-foreground" : "text-muted hover:text-foreground"}`}>
            <span className="kicker block text-[10px]">CAM {i + 1}</span>
            <span className="text-sm font-medium">{s.label}</span>
            {i === at && (
              <motion.span layoutId="cam-live" aria-hidden className="absolute inset-x-2 -top-px h-[3px] bg-accent"
                           transition={{ type: "spring", stiffness: 500, damping: 40 }} />
            )}
          </button>
        ))}
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.p key={shot.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.25 }} className="mx-auto max-w-2xl text-center text-muted">
          {shot.text}
        </motion.p>
      </AnimatePresence>
      <div className="screen-frame mx-auto w-full max-w-5xl">
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-2 font-mono text-[11px] text-white/70">
          <span className="flex items-center gap-2"><span className="on-air-dot" /> PROGRAM · CAM {at + 1}</span>
          <span className="hidden sm:inline">content-corpus.strophic.in</span>
        </div>
        <div className="relative aspect-[16/10] bg-white">
          <AnimatePresence initial={false}>
            <motion.div key={shot.id} className="absolute inset-0" initial={{ opacity: 0, scale: 1.015 }}
                        animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.5 }}>
              <Image src={shot.src} alt={`Content Corpus: ${shot.label}`} fill priority={at === 0}
                     sizes="(min-width: 1024px) 1024px, 100vw" className="object-cover object-top" />
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
