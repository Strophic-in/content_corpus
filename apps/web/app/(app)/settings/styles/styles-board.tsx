"use client";

import { useState, useTransition } from "react";

import type { ActionState } from "../../actions";
import { setStyleEnabled } from "../style-actions";

export type BoardPreset = { id: string; name: string; description: string; families: string[]; preview: string };

const FAMILY: Record<string, string> = { meme: "Meme", ad: "Ad" };

function Grid({ kind, presets, enabled }: { kind: "caption" | "thumb"; presets: BoardPreset[]; enabled: string[] }) {
  const [on, setOn] = useState(new Set(enabled));
  const [state, setState] = useState<ActionState>(null);
  const [busy, start] = useTransition();
  const flip = (id: string) => {
    const next = new Set(on);
    const v = !on.has(id);
    if (v) next.add(id); else next.delete(id);
    setOn(next);
    start(async () => {
      const r = await setStyleEnabled(kind, id, v);
      if (!r?.ok) setOn(on);
      setState(r?.ok ? null : r);
    });
  };
  return (
    <>
      {state?.error && <p className="text-sm text-danger">{state.error}</p>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {presets.map((p) => {
          const active = on.has(p.id);
          const special = p.families.find((f) => f in FAMILY);
          return (
            <button key={p.id} type="button" onClick={() => flip(p.id)} disabled={busy} aria-pressed={active}
                    className={`pressable group flex flex-col gap-2 rounded-2xl border bg-surface p-2 text-left transition ${
                      active ? "border-accent ring-1 ring-accent/40" : "border-border opacity-70 hover:opacity-100"}`}>
              <span className="relative block aspect-[9/16] overflow-hidden rounded-xl bg-background">
                {/* eslint-disable-next-line @next/next/no-img-element -- a static preview */}
                <img src={p.preview} alt="" loading="lazy" className="size-full object-cover" />
                <span className={`absolute top-2 right-2 grid size-6 place-items-center rounded-full text-xs font-bold ${
                  active ? "bg-accent text-white" : "bg-black/60 text-white/70"}`}>{active ? "✓" : ""}</span>
                {special && <span className="absolute top-2 left-2 rounded-full bg-black/70 px-2 py-0.5 text-[11px] text-white">
                  {FAMILY[special]} formats</span>}
              </span>
              <span className="px-1 pb-1">
                <span className="block text-sm font-medium">{p.name}</span>
                <span className="line-clamp-2 block text-xs text-muted">{p.description}</span>
              </span>
            </button>
          );
        })}
      </div>
    </>
  );
}

export function StylesBoard({ captions, thumbs, captionsOn, thumbsOn }: {
  captions: BoardPreset[]; thumbs: BoardPreset[]; captionsOn: string[]; thumbsOn: string[];
}) {
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <div>
          <h2 className="font-semibold">Captions in the video</h2>
          <p className="text-sm text-muted">How the spoken words appear on screen. Tap to switch a style on or off —
            Jev picks the best one switched on for each video.</p>
        </div>
        <Grid kind="caption" presets={captions} enabled={captionsOn} />
      </section>
      <section className="flex flex-col gap-3">
        <div>
          <h2 className="font-semibold">Covers</h2>
          <p className="text-sm text-muted">The thumbnail on YouTube and the cover on Instagram. Jev picks the layout that
            makes people tap — truthfully: Before / Now only with a real before photo, Big number only when there is one.</p>
        </div>
        <Grid kind="thumb" presets={thumbs} enabled={thumbsOn} />
      </section>
    </div>
  );
}
