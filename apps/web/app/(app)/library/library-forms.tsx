"use client";

import { useActionState, useRef, useState, useTransition } from "react";

import type { ActionState } from "../actions";
import { createFormat, deleteFormat, makeDefaultFormat, restoreVersion, updateFormat } from "./actions";

const input = "rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";
const area = `${input} font-mono text-[13px] leading-relaxed`;

function Feedback({ state }: { state: ActionState }) {
  if (state?.error) return <p role="alert" className="rounded-xl bg-danger-surface px-3 py-2 text-sm text-danger">{state.error}</p>;
  if (state?.message) return <p className="text-sm text-ok">{state.message}</p>;
  return null;
}

export function NewFormatForm() {
  const [state, action, pending] = useActionState<ActionState, FormData>(createFormat, null);
  return (
    <form action={action} className="flex flex-col gap-3 sm:flex-row sm:items-end">
      <label className="flex flex-1 flex-col gap-1 text-sm">Name
        <input name="name" required maxLength={60} placeholder="Meme of the day" className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">Start from
        <select name="template" className={input}>
          <option value="narrated">Narrated explainer (voice-over)</option>
          <option value="dialogue">Characters speak (on-screen dialogue)</option>
          <option value="news">News explainer (news desk ideas, narrated)</option>
        </select>
      </label>
      <button disabled={pending} className="rounded-xl bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
        {pending ? "Creating…" : "Create"}
      </button>
      <Feedback state={state} />
    </form>
  );
}

type FormatData = {
  id: string; name: string; description: string; audio_source: "kokoro" | "ltx_native";
  target_seconds: number; ideas_per_batch: number; visual_style: string; idea_prompt: string;
  script_prompt: string; sources: { name: string; url: string }[];
};
type Defaults = { idea_prompt: string; script_prompt: string; visual_style: string; sources: { name: string; url: string }[] };

function PromptField({ label, hint, name, value, onChange, onReset, placeholders, rows }: {
  label: string; hint: string; name: string; value: string; onChange: (v: string) => void; onReset: () => void;
  placeholders?: readonly string[]; rows: number;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  function insert(token: string) {
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.setRangeText(`{${token}}`, el.selectionStart, el.selectionEnd, "end");
    onChange(el.value);
  }
  return (
    <section className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-baseline gap-2">
        <h2 className="font-medium">{label}</h2>
        <button type="button" onClick={onReset} className="ml-auto text-xs text-muted hover:text-accent">Reset to default</button>
      </div>
      <p className="text-xs text-muted">{hint}</p>
      <textarea ref={ref} name={name} rows={rows} value={value} onChange={(e) => onChange(e.target.value)}
                spellCheck={false} className={area} />
      {placeholders && (
        <div className="flex flex-wrap gap-1.5">
          {placeholders.map((p) => (
            <button key={p} type="button" onClick={() => insert(p)}
                    className="rounded-md border border-border px-1.5 py-0.5 font-mono text-[11px] text-muted hover:border-accent hover:text-accent">
              {`{${p}}`}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export function FormatEditor({ format, defaults, placeholders }: {
  format: FormatData & Record<string, unknown>; defaults: Defaults;
  placeholders: { idea_prompt: readonly string[]; script_prompt: readonly string[] };
}) {
  const [state, action, pending] = useActionState<ActionState, FormData>(updateFormat.bind(null, format.id), null);
  const [v, setV] = useState({
    idea_prompt: format.idea_prompt, script_prompt: format.script_prompt, visual_style: format.visual_style,
  });
  const set = (k: keyof typeof v) => (val: string) => setV((s) => ({ ...s, [k]: val }));
  return (
    <form action={action} className="flex flex-col gap-4">
      <section className="grid gap-3 rounded-2xl border border-border bg-surface p-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">Name
          <input name="name" required maxLength={60} defaultValue={format.name} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">What this format is
          <textarea name="description" rows={2} maxLength={1000} defaultValue={format.description} className={input}
                    placeholder="Shown to the idea agent as {format_description}." />
        </label>
        <label className="flex flex-col gap-1 text-sm">Audio
          <select name="audio_source" defaultValue={format.audio_source} className={input}>
            <option value="kokoro">Narrated voice-over</option>
            <option value="ltx_native">Characters speak</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">Length (seconds)
          <input name="target_seconds" type="number" min={5} max={300} defaultValue={format.target_seconds} className={input} />
        </label>
      </section>

      <PromptField label="Look of every shot" name="visual_style" rows={4} value={v.visual_style}
                   onChange={set("visual_style")} onReset={() => set("visual_style")(defaults.visual_style)}
                   hint="Added once to every shot the video model renders. Describe what should be seen — the model reads every word as something to show, so avoid “no …”." />
      <PromptField label="Idea agent" name="idea_prompt" rows={14} value={v.idea_prompt}
                   onChange={set("idea_prompt")} onReset={() => set("idea_prompt")(defaults.idea_prompt)}
                   placeholders={placeholders.idea_prompt}
                   hint="How the agent turns today's trends into ideas for you to swipe." />
      <PromptField label="Script writer" name="script_prompt" rows={18} value={v.script_prompt}
                   onChange={set("script_prompt")} onReset={() => set("script_prompt")(defaults.script_prompt)}
                   placeholders={placeholders.script_prompt}
                   hint="Turns an accepted idea into the script: narration, shots, sound." />
      <p className="rounded-2xl border border-dashed border-border p-4 text-sm text-muted">
        Where ideas come from — Reddit communities, news sites, feeds — is set per category, on the channel&apos;s page
        under Categories.
      </p>

      <div className="sticky bottom-24 z-10 flex flex-col gap-2 rounded-2xl border border-border bg-surface/95 p-3 shadow-lg backdrop-blur md:bottom-4">
        <Feedback state={state} />
        <button disabled={pending} className="rounded-xl bg-accent py-3 text-sm font-semibold text-accent-foreground disabled:opacity-60">
          {pending ? "Saving…" : "Save as a new version"}
        </button>
      </div>
    </form>
  );
}

export function FormatMenu({ formatId, isDefault }: { formatId: string; isDefault: boolean }) {
  const [pending, start] = useTransition();
  const [state, setState] = useState<ActionState>(null);
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex gap-2">
        {!isDefault && (
          <button disabled={pending} onClick={() => start(async () => setState(await makeDefaultFormat(formatId)))}
                  className="rounded-xl border border-border px-3 py-1.5 text-sm hover:border-accent">Make default</button>
        )}
        {!isDefault && (
          <button disabled={pending}
                  onClick={() => confirm("Delete this format? Its ideas go with it.") && start(async () => setState(await deleteFormat(formatId)))}
                  className="rounded-xl border border-border px-3 py-1.5 text-sm text-danger hover:border-danger">Delete</button>
        )}
      </div>
      <Feedback state={state} />
    </div>
  );
}

export function VersionList({ formatId, versions }: {
  formatId: string; versions: { version: number; savedAt: string; preview: string }[];
}) {
  const [pending, start] = useTransition();
  const [state, setState] = useState<ActionState>(null);
  return (
    <section className="rounded-2xl border border-border bg-surface p-4">
      <h2 className="font-medium">History</h2>
      <p className="mt-1 text-xs text-muted">Every save keeps the version before it. Restoring keeps the current one too.</p>
      <ul className="mt-3 flex flex-col divide-y divide-border">
        {versions.map((v) => (
          <li key={v.version} className="flex items-center gap-3 py-2 text-sm">
            <span className="w-10 font-medium">v{v.version}</span>
            <span className="flex-1 truncate text-muted">{v.savedAt} · {v.preview}</span>
            <button disabled={pending} onClick={() => start(async () => setState(await restoreVersion(formatId, v.version)))}
                    className="rounded-lg border border-border px-2 py-1 text-xs hover:border-accent">Restore</button>
          </li>
        ))}
      </ul>
      <Feedback state={state} />
    </section>
  );
}
