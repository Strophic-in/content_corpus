"use client";

import { useRef, useState, useTransition } from "react";

import type { ActionState } from "../../actions";
import { setVoiceEnabled, setVoiceMode, setVoiceStyleEnabled } from "../voice-actions";

export type BoardVoice = {
  id: string; engine: "kokoro" | "openai"; name: string; gender: string; accent: string; languages: string[];
  tone: string; sample: string | null;
};
export type BoardStyle = { id: string; name: string; description: string; hindiOnly: boolean; sample: string | null;
                           group: string; expressive: boolean };
const GROUP_ORDER = ["News", "Documentary & story", "Dark & dramatic", "Fun", "Energy", "Calm"];

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
  { title: "Directable voices", note: "Follow the style's instructions · English and Hindi · about ₹1 a reel on your OpenAI key",
    has: (v) => v.engine === "openai" },
  { title: "English — American", note: "Free · on the server", has: (v) => v.engine === "kokoro" && v.accent === "US" },
  { title: "English — British", note: "Free · on the server", has: (v) => v.engine === "kokoro" && v.accent === "UK" },
  { title: "Hindi", note: "Free · on the server", has: (v) => v.engine === "kokoro" && v.languages.includes("hi") },
];

export function VoicesBoard({ voices, styles, enabled, stylesOn, mode, fixedVoice, fixedStyle }: {
  voices: BoardVoice[]; styles: BoardStyle[]; enabled: string[]; stylesOn: string[]; mode: "auto" | "fixed";
  fixedVoice: string | null; fixedStyle: string | null;
}) {
  const [on, setOn] = useState(new Set(enabled));
  const [sOn, setSOn] = useState(new Set(stylesOn));
  const [m, setM] = useState(mode);
  const [fv, setFv] = useState(fixedVoice ?? voices[0]?.id ?? "");
  const [fs, setFs] = useState(fixedStyle ?? "");
  const [state, setState] = useState<ActionState>(null);
  const [busy, start] = useTransition();
  const player = usePlayer();

  const flip = (set: Set<string>, put: (s: Set<string>) => void, id: string, v: boolean,
                save: (id: string, v: boolean) => Promise<ActionState>) => {
    const next = new Set(set);
    if (v) next.add(id); else next.delete(id);
    put(next);
    start(async () => {
      const r = await save(id, v);
      if (!r?.ok) put(set);
      setState(r?.ok ? null : r);
    });
  };
  const saveMode = (mode: "auto" | "fixed", voice = fv, style = fs) => {
    setM(mode);
    start(async () => setState(await setVoiceMode(mode, voice || null, style || null)));
  };

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5">
        <h2 className="font-semibold">Who picks the voice</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          {([["auto", "Jev picks for each post", "The best voice and style switched on below, for the story and the channel's language — never upbeat for a tragedy."],
             ["fixed", "Always one voice", "The same voice on every post, in the style you choose."]] as const).map(([id, title, note]) => (
            <button key={id} type="button" onClick={() => saveMode(id)}
                    className={`pressable flex flex-col gap-1 rounded-xl border p-3 text-left ${m === id ? "border-accent bg-accent/10" : "border-border hover:border-accent"}`}>
              <span className="text-sm font-medium">{title}</span>
              <span className="text-xs text-muted">{note}</span>
            </button>
          ))}
        </div>
        {m === "fixed" && (
          <div className="flex flex-wrap gap-2">
            <select value={fv} onChange={(e) => { setFv(e.target.value); saveMode("fixed", e.target.value, fs); }}
                    className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
              {voices.map((v) => <option key={v.id} value={v.id}>{v.name} — {v.engine === "openai" ? "directable" : `${v.accent} ${v.gender}`}</option>)}
            </select>
            <select value={fs} onChange={(e) => { setFs(e.target.value); saveMode("fixed", fv, e.target.value); }}
                    className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
              <option value="">Style: Jev picks</option>
              {styles.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
        )}
        {state?.error && <p className="text-sm text-danger">{state.error}</p>}
      </section>

      <section className="flex flex-col gap-4">
        <div>
          <h2 className="font-semibold">Styles</h2>
          <p className="text-sm text-muted">How a script is read. Jev picks the style first, then a voice that suits it.
            Styles marked <span className="font-medium text-accent">acted</span> need a directable voice — the free voices
            can only change their pace. Samples are read by the voice that suits each style best.</p>
        </div>
        {[...GROUP_ORDER.filter((g) => styles.some((s) => s.group === g)),
          ...[...new Set(styles.map((s) => s.group))].filter((g) => !GROUP_ORDER.includes(g))].map((g) => (
        <div key={g} className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{g}</h3>
          <div className="grid gap-2 sm:grid-cols-2">
          {styles.filter((s) => s.group === g).map((s) => (
            <div key={s.id} className={`flex items-center gap-3 rounded-xl border bg-surface p-3 ${sOn.has(s.id) ? "border-border" : "border-border opacity-60"}`}>
              <Play src={s.sample} player={player} />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{s.name}
                  {s.hindiOnly && <span className="ml-2 text-xs text-muted">Hindi</span>}
                  {s.expressive && <span className="ml-2 rounded-full bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">acted</span>}
                </span>
                <span className="block text-xs text-muted">{s.description}</span>
              </span>
              <Toggle on={sOn.has(s.id)} busy={busy} label={s.name}
                      onChange={(v) => flip(sOn, setSOn, s.id, v, setVoiceStyleEnabled)} />
            </div>
          ))}
          </div>
        </div>
        ))}
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
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((v) => (
                <div key={v.id} className={`flex items-center gap-3 rounded-xl border bg-surface p-3 ${on.has(v.id) ? "border-accent/40" : "border-border"}`}>
                  <Play src={v.sample} player={player} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{v.name}</span>
                    <span className="block truncate text-xs text-muted">{v.gender} · {v.tone}</span>
                  </span>
                  <Toggle on={on.has(v.id)} busy={busy} label={v.name}
                          onChange={(x) => flip(on, setOn, v.id, x, setVoiceEnabled)} />
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
