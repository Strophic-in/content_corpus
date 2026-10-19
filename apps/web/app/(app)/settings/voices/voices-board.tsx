"use client";

import { useRef, useState, useTransition } from "react";

import type { ActionState } from "../../actions";
import { setVoiceEnabled, setVoiceMode } from "../voice-actions";

export type BoardVoice = {
  id: string; engine: "kokoro" | "openai"; name: string; gender: string; accent: string; languages: string[];
  tone: string; sample: string | null;
};

function Toggle({ on, onChange, label, busy }: { on: boolean; onChange: (v: boolean) => void; label: string; busy: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={busy} onClick={() => onChange(!on)}
            className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? "bg-accent" : "bg-border"}`}>
      <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-all ${on ? "left-[1.375rem]" : "left-0.5"}`} />
    </button>
  );
}

/** One <audio> for the page: a new sample stops the one playing. */
function usePlayer() {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const play = (src: string) => {
    if (!audio.current) {
      audio.current = new Audio();
      audio.current.onended = () => setPlaying(null);
    }
    if (playing === src) { audio.current.pause(); setPlaying(null); return; }
    audio.current.src = src;
    void audio.current.play();
    setPlaying(src);
  };
  return { playing, play };
}

function Play({ src, player }: { src: string | null; player: ReturnType<typeof usePlayer> }) {
  if (!src) return <span className="w-9" />;
  const on = player.playing === src;
  return (
    <button type="button" onClick={() => player.play(src)} aria-label={on ? "Stop the sample" : "Play a sample"}
            className={`pressable grid size-9 shrink-0 place-items-center rounded-full border ${on ? "border-accent bg-accent/15 text-accent" : "border-border hover:border-accent"}`}>
      <svg viewBox="0 0 24 24" className="size-4" fill="currentColor" aria-hidden>
        {on ? <path d="M7 6h3v12H7zM14 6h3v12h-3z" /> : <path d="M8 5v14l11-7L8 5Z" />}
      </svg>
    </button>
  );
}

const GROUPS: { title: string; note: string; has: (v: BoardVoice) => boolean }[] = [
  { title: "English — American", note: "Free · on the server · used first for English",
    has: (v) => v.engine === "kokoro" && v.accent === "US" },
  { title: "English — British", note: "Free · on the server · used first for English",
    has: (v) => v.engine === "kokoro" && v.accent === "UK" },
  { title: "AI voices", note: "Used for Hindi (and English if no free voice is on) · tone set from the script · about ₹1 a reel on your OpenAI key",
    has: (v) => v.engine === "openai" },
  { title: "Hindi — free", note: "Free · on the server · used for Hindi only when no AI voice is on",
    has: (v) => v.engine === "kokoro" && v.languages.includes("hi") },
];

export function VoicesBoard({ voices, enabled, mode, fixedVoice }: {
  voices: BoardVoice[]; enabled: string[]; mode: "auto" | "fixed"; fixedVoice: string | null;
}) {
  const [on, setOn] = useState(new Set(enabled));
  const [m, setM] = useState(mode);
  const [fv, setFv] = useState(fixedVoice ?? voices[0]?.id ?? "");
  const [state, setState] = useState<ActionState>(null);
  const [busy, start] = useTransition();
  const player = usePlayer();

  const flip = (id: string, v: boolean) => {
    const before = on;
    const next = new Set(on);
    if (v) next.add(id); else next.delete(id);
    setOn(next);
    start(async () => {
      const r = await setVoiceEnabled(id, v);
      if (!r?.ok) setOn(before);
      setState(r?.ok ? null : r);
    });
  };
  const saveMode = (mode: "auto" | "fixed", voice = fv) => {
    setM(mode);
    start(async () => setState(await setVoiceMode(mode, voice || null)));
  };

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5">
        <h2 className="font-semibold">Who picks the voice</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {([["auto", "Jev picks for each post", "The voice switched on below that suits the story best, in the channel's language."],
             ["fixed", "Always one voice", "The same voice on every post."]] as const).map(([id, title, note]) => (
            <button key={id} type="button" onClick={() => saveMode(id)}
                    className={`pressable flex flex-col gap-1 rounded-xl border p-3 text-left ${m === id ? "border-accent bg-accent/10" : "border-border hover:border-accent"}`}>
              <span className="text-sm font-medium">{title}</span>
              <span className="text-xs text-muted">{note}</span>
            </button>
          ))}
        </div>
        {m === "fixed" && (
          <div className="flex flex-wrap gap-2">
            <select value={fv} onChange={(e) => { setFv(e.target.value); saveMode("fixed", e.target.value); }}
                    className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
              {voices.map((v) => <option key={v.id} value={v.id}>{v.name} — {v.engine === "openai" ? "AI" : `${v.accent} ${v.gender}, free`}</option>)}
            </select>
          </div>
        )}
        {state?.error && <p className="text-sm text-danger">{state.error}</p>}
      </section>

      {GROUPS.map((g) => {
        const list = voices.filter(g.has);
        const count = list.filter((v) => on.has(v.id)).length;
        return (
          <section key={g.title} className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <h2 className="font-semibold">{g.title}</h2>
              <span className="text-sm text-muted">{g.note}</span>
              <span className="ml-auto text-xs text-muted">{count} of {list.length} on</span>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((v) => (
                <div key={v.id} className={`flex items-center gap-3 rounded-xl border bg-surface p-3 ${on.has(v.id) ? "border-accent/40" : "border-border"}`}>
                  <Play src={v.sample} player={player} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{v.name}</span>
                    <span className="block truncate text-xs text-muted">{v.gender} · {v.tone}</span>
                  </span>
                  <Toggle on={on.has(v.id)} busy={busy} label={v.name}
                          onChange={(x) => flip(v.id, x)} />
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
