"use client";

import { useRouter } from "next/navigation";
import { useActionState, useState, useTransition } from "react";

import {
  refreshModels, saveOpenAIKey, savePrices, saveRedditKeys, saveServiceKey, saveSettings, type ActionState,
  type ServiceKey,
} from "../actions";

/** The key's model list, re-read now (new models also appear by themselves daily). */
function RefreshModels() {
  const router = useRouter();
  const [note, setNote] = useState<string | null>(null);
  const [pending, start] = useTransition();
  return (
    <span className="text-xs text-muted">
      <button type="button" disabled={pending} className="text-accent hover:underline disabled:opacity-50"
              onClick={() => start(async () => {
                const r = await refreshModels();
                setNote(r?.ok ? "Updating…" : r?.error ?? "Couldn't refresh.");
                setTimeout(() => { router.refresh(); setNote(null); }, 5000);
              })}>
        Refresh list
      </button>
      {note && <span className="ml-2">{note}</span>}
    </span>
  );
}

const input = "rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";

function Feedback({ state }: { state: ActionState }) {
  if (state?.error) return <p role="alert" className="rounded-md bg-danger-surface px-3 py-2 text-sm text-danger">{state.error}</p>;
  if (state?.message) return <p className="text-sm text-ok">{state.message}</p>;
  return null;
}

export function KeyForm({ hasKey }: { hasKey: boolean }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(saveOpenAIKey, null);
  return (
    <form action={action} className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <input name="openai_key" type="password" required autoComplete="off" spellCheck={false}
               placeholder={hasKey ? "Paste a new key to replace it" : "sk-…"} className={`${input} min-w-0 flex-1`} />
        <button disabled={pending}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
          {pending ? "Checking…" : hasKey ? "Replace" : "Save"}
        </button>
      </div>
      <p className="text-xs text-muted">The key is checked with OpenAI before it is saved.</p>
      <Feedback state={state} />
    </form>
  );
}

type Settings = {
  channel_name: string | null; channel_niche: string | null; channel_audience: string | null;
  channel_voice: string | null; script_language: string; default_reel_seconds: number;
  script_model: string | null; openai_models: string[]; timezone: string;
  default_publish_time: string; youtube_privacy: string; auto_approve: boolean;
  default_audio_source: "kokoro" | "ltx_native";
  narrator_voice: string; narrator_speed: number;
  pipeline_mode: "manual" | "auto"; auto_spend_cap_paise_day: number | null; vision_model: string | null;
  image_model: string; image_quality: "low" | "medium" | "high"; image_models: string[];
};

// Mirrors worker/corpus/media/tts.py VOICES.
const VOICES: [string, string][] = [
  ["am_michael", "Michael — calm US male"], ["am_fenrir", "Fenrir — deeper US male"],
  ["am_onyx", "Onyx — low US male"], ["bm_george", "George — British documentary"],
  ["bm_lewis", "Lewis — British male"], ["af_heart", "Heart — warm US female"],
  ["af_bella", "Bella — bright US female"], ["bf_emma", "Emma — British female"],
];

export function SettingsForm({ settings: s }: { settings: Settings }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(saveSettings, null);
  const [mode, setMode] = useState(s.pipeline_mode);
  return (
    <form action={action} className="flex flex-col gap-6">
      <section className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
        <div>
          <h2 className="font-medium">Writing &amp; narration</h2>
          <p className="mt-1 text-sm text-muted">
            For every channel. Each channel&apos;s voice lives in Channels; each kind of video&apos;s prompts in its Library.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">Narrator voice
            <select name="narrator_voice" defaultValue={s.narrator_voice} className={input}>
              {VOICES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">Narration speed
            <input name="narrator_speed" type="number" min={0.7} max={1.5} step={0.05}
                   defaultValue={s.narrator_speed} className={input} />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="flex items-baseline gap-2">Script model <RefreshModels /></span>
          {s.openai_models.length ? (
            <select name="script_model" defaultValue={s.script_model ?? ""} className={input}>
              <option value="">Choose a model…</option>
              {s.openai_models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <>
              <input type="hidden" name="script_model" value="" />
              <span className="text-xs text-muted">Save an OpenAI key first — its available models appear here.</span>
            </>
          )}
        </label>
        <label className="flex flex-col gap-1 text-sm">Vision model (reads Reddit videos for the cards)
          {s.openai_models.length ? (
            <select name="vision_model" defaultValue={s.vision_model ?? ""} className={input}>
              <option value="">Don&apos;t describe videos</option>
              {s.openai_models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : <input type="hidden" name="vision_model" value="" />}
          <span className="text-xs text-muted">
            One call per video, on a sheet of nine frames: a small model (a “mini” or “nano”) is plenty and costs a
            fraction of a cent.
          </span>
        </label>
        <label className="flex flex-col gap-1 text-sm">Image model (AI versions of pictures)
          <span className="flex gap-2">
            <select name="image_model" defaultValue={s.image_model} className={`${input} min-w-0 flex-1`}>
              {[...new Set([s.image_model, ...s.image_models])].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <select name="image_quality" defaultValue={s.image_quality} className={input} aria-label="Image quality">
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </span>
          <span className="text-xs text-muted">
            One picture per “AI version”, 1024×1536. gpt-image-1-mini costs about $0.006 (low) or $0.015 (medium) a
            picture.
          </span>
        </label>
      </section>

      <section className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
        <div>
          <h2 className="font-medium">After you accept an idea</h2>
          <p className="mt-1 text-sm text-muted">
            Applies to posts made from now on; a post keeps the mode it was made with.
          </p>
        </div>
        <input type="hidden" name="pipeline_mode" value={mode} />
        <div className="grid gap-2 sm:grid-cols-2">
          {([["manual", "Manual", "You write, approve, render and post each one."],
             ["auto", "Automatic", "Script, render and posting at the time you picked — no more clicks. A desk-editor check holds anything doubtful for you."]] as const)
            .map(([v, label, hint]) => (
              <button key={v} type="button" onClick={() => setMode(v)}
                      className={`rounded-xl border p-3 text-left text-sm ${mode === v ? "border-accent bg-accent/10" : "border-border"}`}>
                <span className="font-medium">{label}</span>
                <span className="mt-1 block text-xs text-muted">{hint}</span>
              </button>
            ))}
        </div>
        {mode === "auto" ? (
          <>
            <input type="hidden" name="auto_approve" value={s.auto_approve ? "on" : ""} />
            <label className="flex flex-col gap-1 text-sm sm:w-1/2">Daily spending limit for automatic renders (₹)
              <input name="auto_spend_cap" type="number" min={0} step={1} className={input}
                     defaultValue={s.auto_spend_cap_paise_day != null ? s.auto_spend_cap_paise_day / 100 : ""}
                     placeholder="No limit" />
              <span className="text-xs text-muted">Once today&apos;s OpenAI + GPU spend reaches it, new renders wait for you.</span>
            </label>
          </>
        ) : (
          <label className="flex items-start gap-3 text-sm">
            <input type="hidden" name="auto_spend_cap" value={s.auto_spend_cap_paise_day != null ? s.auto_spend_cap_paise_day / 100 : ""} />
            <input name="auto_approve" type="checkbox" defaultChecked={s.auto_approve} className="mt-1" />
            <span>
              Approve scripts automatically
              <span className="block text-xs text-muted">Rendering and posting still wait for you.</span>
            </span>
          </label>
        )}
      </section>

      <section className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
        <h2 className="font-medium">Publishing</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-sm">YouTube visibility
            <select name="youtube_privacy" defaultValue={s.youtube_privacy} className={input}>
              <option value="private">Private</option>
              <option value="unlisted">Unlisted</option>
              <option value="public">Public</option>
            </select>
          </label>
        </div>
        <p className="text-xs text-muted">The default for new posts; each post can choose its own when you post it.</p>
      </section>

      <div className="flex items-center gap-3">
        <button disabled={pending}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
          {pending ? "Saving…" : "Save settings"}
        </button>
        <Feedback state={state} />
      </div>
    </form>
  );
}


export function RedditKeysForm({ saved }: { saved: boolean }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(saveRedditKeys, null);
  return (
    <form action={action} className="flex flex-col gap-2">
      <div className="grid gap-2 sm:grid-cols-2">
        <input name="client_id" autoComplete="off" spellCheck={false} placeholder="Client id" className={input} />
        <input name="client_secret" type="password" autoComplete="off" spellCheck={false} placeholder="Client secret" className={input} />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button disabled={pending} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
          {pending ? "Saving…" : saved ? "Replace" : "Save"}
        </button>
        {saved && <button name="remove" value="1" disabled={pending} className="text-sm text-danger hover:underline">Remove</button>}
      </div>
      <Feedback state={state} />
    </form>
  );
}

export function ServiceKeyForm({ service, saved, placeholder }: {
  service: ServiceKey; saved: boolean; placeholder: string;
}) {
  const [state, action, pending] = useActionState<ActionState, FormData>(saveServiceKey.bind(null, service), null);
  return (
    <form action={action} className="flex flex-col gap-2">
      <input name="key" type="password" autoComplete="off" spellCheck={false} placeholder={placeholder}
             className={input} />
      <div className="flex flex-wrap items-center gap-3">
        <button disabled={pending} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
          {pending ? "Saving…" : saved ? "Replace" : "Save"}
        </button>
        {saved && <button name="remove" value="1" disabled={pending} className="text-sm text-danger hover:underline">Remove</button>}
      </div>
      <Feedback state={state} />
    </form>
  );
}

type PriceRow = { model: string; own: { input_per_m: number | null; cached_input_per_m: number | null;
                                        output_per_m: number | null; per_image: number | null } | null;
                  defaults: [number, number, number] | null };

export function PricesForm({ rows, fx, override }: {
  rows: PriceRow[]; fx: { day: string; usd_inr: number; source: string } | undefined; override: number | null;
}) {
  const [state, action, pending] = useActionState<ActionState, FormData>(savePrices, null);
  const cell = `${input} w-20 px-2 py-1 text-right tabular-nums`;
  return (
    <form action={action} className="flex flex-col gap-3">
      {rows.length === 0 ? <p className="text-sm text-muted">No models used yet.</p> : (
        <div className="-mx-1 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr><th className="p-1 font-normal">Model</th><th className="p-1 font-normal">Input</th>
                <th className="p-1 font-normal">Cached</th><th className="p-1 font-normal">Output</th>
                <th className="p-1 font-normal">Per image</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.model} className="align-top">
                  <td className="p-1">
                    <input type="hidden" name="model" value={r.model} />
                    <span className="font-mono text-xs">{r.model}</span>
                    {!r.own && !r.defaults && <span className="block text-xs text-warn">no price — set one</span>}
                    {!r.own && r.defaults && <span className="block text-xs text-muted">list price</span>}
                  </td>
                  {(["input", "cached", "output"] as const).map((k, i) => (
                    <td key={k} className="p-1">
                      <input name={k} inputMode="decimal" className={cell}
                             defaultValue={r.own ? (r.own[(["input_per_m", "cached_input_per_m", "output_per_m"] as const)[i]] ?? "") : ""}
                             placeholder={r.defaults ? String(r.defaults[i]) : "—"} />
                    </td>
                  ))}
                  <td className="p-1"><input name="image" inputMode="decimal" className={cell}
                                             defaultValue={r.own?.per_image ?? ""} placeholder="—" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted">US dollars per million tokens. Leave a row empty to use the list price shown.</p>
      <label className="flex flex-col gap-1 text-sm sm:w-1/2">US dollar in rupees
        <input name="usd_inr" inputMode="decimal" defaultValue={override ?? ""} className={input}
               placeholder={fx ? `${fx.usd_inr.toFixed(2)} (ECB, ${fx.day})` : "e.g. 84.5"} />
        <span className="text-xs text-muted">Empty: the day&apos;s reference rate, fetched automatically.</span>
      </label>
      <div className="flex items-center gap-3">
        <button disabled={pending} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
          {pending ? "Saving…" : "Save prices"}
        </button>
        <Feedback state={state} />
      </div>
    </form>
  );
}
