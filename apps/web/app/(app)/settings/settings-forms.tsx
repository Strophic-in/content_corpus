"use client";

import { useActionState } from "react";

import { saveOpenAIKey, saveSettings, type ActionState } from "../actions";

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
  return (
    <form action={action} className="flex flex-col gap-6">
      <section className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
        <div>
          <h2 className="font-medium">Channel</h2>
          <p className="mt-1 text-sm text-muted">Every script is written for this channel.</p>
        </div>
        <label className="flex flex-col gap-1 text-sm">Channel name
          <input name="channel_name" maxLength={120} defaultValue={s.channel_name ?? ""} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm">Niche
          <textarea name="channel_niche" rows={2} maxLength={500} defaultValue={s.channel_niche ?? ""}
                    placeholder="Startup and office humour for Indian tech workers" className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm">Audience
          <textarea name="channel_audience" rows={2} maxLength={500} defaultValue={s.channel_audience ?? ""}
                    placeholder="Founders, developers and PMs, 22-35" className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm">Voice
          <textarea name="channel_voice" rows={2} maxLength={500} defaultValue={s.channel_voice ?? ""}
                    placeholder="Deadpan, relatable, never mean" className={input} />
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">Script language
            <input name="script_language" required maxLength={40} defaultValue={s.script_language} className={input} />
          </label>
          <label className="flex flex-col gap-1 text-sm">Default reel length (s)
            <input name="default_reel_seconds" type="number" min={5} max={90} required
                   defaultValue={s.default_reel_seconds} className={input} />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">Audio style
          <select name="default_audio_source" defaultValue={s.default_audio_source} className={input}>
            <option value="kokoro">Narrated voice-over — one narrator over animation (explainers)</option>
            <option value="ltx_native">Characters speak — dialogue voiced by the video model (sketches)</option>
          </select>
          <span className="text-xs text-muted">Applies to new posts.</span>
        </label>
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
        <label className="flex flex-col gap-1 text-sm">Script model
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
      </section>

      <section className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
        <h2 className="font-medium">Publishing</h2>
        <label className="flex items-start gap-3 text-sm">
          <input name="auto_approve" type="checkbox" defaultChecked={s.auto_approve} className="mt-1" />
          <span>
            Auto-approve scripts for new posts
            <span className="block text-xs text-muted">
              Applies to posts created after you turn it on. Existing posts keep the setting they were created with.
            </span>
          </span>
        </label>
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-sm">Timezone
            <input name="timezone" required defaultValue={s.timezone} className={input} />
          </label>
          <label className="flex flex-col gap-1 text-sm">Publish time
            <input name="default_publish_time" type="time" step={60} required defaultValue={s.default_publish_time.slice(0, 5)} className={input} />
          </label>
          <label className="flex flex-col gap-1 text-sm">YouTube visibility
            <select name="youtube_privacy" defaultValue={s.youtube_privacy} className={input}>
              <option value="private">Private</option>
              <option value="unlisted">Unlisted</option>
              <option value="public">Public</option>
            </select>
          </label>
        </div>
        <p className="text-xs text-muted">
          Until YouTube approves this app’s API audit, YouTube keeps every upload private whatever is chosen here.
        </p>
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
