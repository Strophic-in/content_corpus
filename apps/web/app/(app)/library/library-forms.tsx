"use client";

import { useActionState, useMemo, useRef, useState, useTransition } from "react";

import type { ActionState } from "../actions";
import { createFormat, deleteFormat, makeDefaultFormat, restoreVersion, updateFormat } from "./actions";

const input = "rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";
const area = `${input} font-mono text-[13px] leading-relaxed`;

function Feedback({ state }: { state: ActionState }) {
  if (state?.error) return <p role="alert" className="rounded-xl bg-danger-surface px-3 py-2 text-sm text-danger">{state.error}</p>;
  if (state?.message) return <p className="text-sm text-ok">{state.message}</p>;
  return null;
}

/** What the client needs to know about a template (templates.ts). */
export type TemplateInfo = {
  template_id: string; display_name: string; content_type: "video" | "carousel" | "image"; format: string;
  best_for: string[]; estimated_render_cost: "low" | "medium" | "high"; needs_owned_footage: boolean;
  scene_structure: string[]; recommended_duration_seconds: [number, number]; required_assets: string[];
  platform_notes: string[]; rights_requirements: string[]; music_source_mode: string; poster: string | null;
  render: {
    captions: string; layouts: string[]; layout: string; transition: string; transitions: string[]; audios: string[];
    slides?: { layout: string; aspect: "4:5" | "1:1"; count: [number, number] };
  };
};

const KIND = { video: "Reel / Short", carousel: "Carousel", image: "Picture post" } as const;
const COST = { low: "No GPU", medium: "Some GPU", high: "GPU every shot" } as const;
const words = (s: string) => s.replaceAll("_", " ");

export function NewFormatForm({ templates }: { templates: TemplateInfo[] }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(createFormat, null);
  const [kind, setKind] = useState<"all" | "video" | "carousel" | "image">("all");
  const [picked, setPicked] = useState<string | null>(null);
  const shown = templates.filter((t) => kind === "all" || t.content_type === kind);
  const t = templates.find((x) => x.template_id === picked);
  return (
    <form action={action} className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-1.5 text-xs">
        {(["all", "video", "carousel", "image"] as const).map((k) => (
          <button key={k} type="button" onClick={() => setKind(k)}
                  className={`rounded-full border px-3 py-1 ${kind === k ? "border-accent text-accent" : "border-border text-muted"}`}>
            {k === "all" ? `All · ${templates.length}` : KIND[k]}
          </button>
        ))}
      </div>
      <ul className="grid gap-2 sm:grid-cols-2">
        {shown.map((x) => (
          <li key={x.template_id}>
            <label className={`flex h-full cursor-pointer gap-3 rounded-xl border p-3 text-sm transition ${picked === x.template_id
              ? "border-accent bg-background" : "border-border hover:border-accent/60"}`}>
              <input type="radio" name="template" value={x.template_id} checked={picked === x.template_id}
                     onChange={() => setPicked(x.template_id)} className="sr-only" />
              {x.poster && (
                // eslint-disable-next-line @next/next/no-img-element -- a small static sample
                <img src={x.poster} alt="" loading="lazy"
                     className="h-24 w-[54px] shrink-0 rounded-md bg-background object-cover" />
              )}
              <span className="min-w-0">
                <span className="block font-medium">{x.display_name}</span>
                <span className="mt-0.5 block text-xs text-muted">{KIND[x.content_type]} · {COST[x.estimated_render_cost]}
                  {x.needs_owned_footage ? " · your footage" : ""}</span>
                <span className="mt-1 line-clamp-2 block text-xs text-muted">{x.format}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      {t && (
        <div className="flex flex-col gap-3 rounded-xl border border-border p-3 text-sm sm:flex-row sm:items-end">
          <label className="flex flex-1 flex-col gap-1">Name
            <input name="name" required maxLength={60} key={t.template_id} defaultValue={t.display_name} className={input} />
          </label>
          <button disabled={pending} className="rounded-xl bg-accent px-4 py-2 font-medium text-accent-foreground disabled:opacity-60">
            {pending ? "Creating…" : "Create format"}
          </button>
        </div>
      )}
      <Feedback state={state} />
    </form>
  );
}

type FormatData = {
  id: string; name: string; description: string; audio_source: "kokoro" | "ltx_native" | "none";
  target_seconds: number; visual_style: string; idea_prompt: string; script_prompt: string;
  params: Record<string, unknown>; template_id: string;
};
type Defaults = { idea_prompt: string; script_prompt: string; visual_style: string };

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

const CAPTIONS: Record<string, string> = {
  karaoke: "Word captions (the spoken words, the active one highlighted)",
  speech: "Big speech captions", beats: "Text beats (large text in the middle)",
  kinetic: "Kinetic typography (words pop onto the screen)", none: "None",
};
const TRANSITIONS: Record<string, string> = {
  cut: "Hard cut", fade: "Fade through black", crossfade: "Crossfade", whip: "Whip pan", wipe: "Wipe",
  zoom: "Zoom", flash: "Flash",
};

function Select({ name, label, value, options, hint }: {
  name: string; label: string; value: string; options: [string, string][]; hint?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">{label}
      <select name={`p_${name}`} defaultValue={value} className={input}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  );
}

function Colour({ name, label, value, fallback }: { name: string; label: string; value?: string; fallback: string }) {
  const [v, setV] = useState(value ?? "");
  return (
    <label className="flex flex-col gap-1 text-sm">{label}
      <span className="flex items-center gap-2">
        <input type="color" value={v || fallback} onChange={(e) => setV(e.target.value)} aria-label={label}
               className="size-9 shrink-0 cursor-pointer rounded-lg border border-border bg-background" />
        <input name={`p_${name}`} value={v} onChange={(e) => setV(e.target.value)} placeholder={fallback}
               className={`${input} min-w-0 flex-1 font-mono`} />
      </span>
    </label>
  );
}

/** The look a format adds to its template: every field blank = the template's own. */
function LookFields({ t, params }: { t: TemplateInfo; params: Record<string, unknown> }) {
  const p = (k: string) => (params[k] == null ? "" : String(params[k]));
  const video = t.content_type === "video";
  const s = t.render.slides;
  return (
    <section className="grid gap-3 rounded-2xl border border-border bg-surface p-4 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <h2 className="font-medium">Look</h2>
        <p className="text-xs text-muted">Leave a field on “template default” to follow {t.display_name}.</p>
      </div>
      {video && (
        <>
          <Select name="captions" label="On-screen words" value={p("captions")}
                  options={[["", `Template default — ${CAPTIONS[t.render.captions] ?? t.render.captions}`],
                            ...Object.entries(CAPTIONS).filter(([k]) => k !== t.render.captions)]} />
          <Select name="transition" label="Between shots" value={p("transition")}
                  options={[["", `Template default — ${TRANSITIONS[t.render.transition]}`],
                            ...t.render.transitions.filter((k) => k !== t.render.transition)
                              .map((k): [string, string] => [k, TRANSITIONS[k] ?? k])]} />
          {t.render.layouts.length > 1 && (
            <Select name="layout" label="Layout" value={p("layout")}
                    options={[["", `Template default — ${t.render.layout === "split" ? "split screen" : "full screen"}`],
                              ...t.render.layouts.filter((k) => k !== t.render.layout)
                                .map((k): [string, string] => [k, k === "split" ? "Split screen" : "Full screen"])]} />
          )}
          <Select name="caption_position" label="Caption position" value={p("caption_position")}
                  options={[["", "Template default"], ["top", "Upper third"], ["middle", "Middle"], ["bottom", "Lower third"]]} />
        </>
      )}
      <Select name="font" label="Font" value={p("font")}
              options={[["", "Template default — Montserrat"], ["Noto Serif", "Noto Serif (documentary)"]]} />
      <Select name="music_source_mode" label="Music" value={p("music_source_mode")}
              options={[["", `Template default — ${t.music_source_mode === "licensed_asset" ? "CC0 track by mood"
                : t.music_source_mode === "none" ? "no music" : "added in the app"}`],
                        ["licensed_asset", "CC0 track by mood, under the voice"],
                        ["platform_native", "None in the file — I add a trending song in the app"],
                        ["none", "No music"]]}
              hint="“In the app” leaves the file without music and doesn't post it automatically." />
      <Colour name="primary_color" label="Text colour" value={p("primary_color")} fallback="#FFFFFF" />
      <Colour name="accent_color" label="Accent colour" value={p("accent_color")} fallback="#FFE000" />
      <Colour name="background_color" label="Background colour" value={p("background_color")} fallback="#0F172A" />
      {video && <Colour name="panel_color" label="Split-screen panel colour" value={p("panel_color")} fallback="#111827" />}
      <label className="flex flex-col gap-1 text-sm">Brand line
        <input name="p_brand_text" maxLength={40} defaultValue={p("brand_text")} placeholder="@yourhandle"
               className={input} />
        <span className="text-xs text-muted">Shown at the foot of slides and cards.</span>
      </label>
      {s && (
        <>
          <Select name="slide_aspect" label="Slide shape" value={p("slide_aspect")}
                  options={[["", `Template default — ${s.aspect}`], ["4:5", "4:5 portrait (1080×1350)"], ["1:1", "Square (1080×1080)"]]} />
          {s.count[0] !== s.count[1] && (
            <Select name="slide_count" label="Slides" value={p("slide_count")}
                    options={[["", `Template default — ${s.count[0]}-${s.count[1]}`],
                              ...Array.from({ length: s.count[1] - s.count[0] + 1 }, (_, i): [string, string] =>
                                [String(s.count[0] + i), `Exactly ${s.count[0] + i}`])]} />
          )}
          <Select name="ai_images" label="AI pictures" value={p("ai_images")}
                  options={[["", "Template default — the cover only"], ["cover", "The cover only (about ₹1.3)"],
                            ["all", "Any slide that needs one (about ₹1.3 each)"], ["none", "Never"]]}
                  hint="Used only where the post has no picture of its own." />
        </>
      )}
      {video && (
        <label className="flex flex-col gap-1 text-sm">Side margin (px)
          <input name="p_safe_margin_px" type="number" min={30} max={160} defaultValue={p("safe_margin_px")}
                 placeholder="60" className={input} />
        </label>
      )}
    </section>
  );
}

export function TemplateCard({ t }: { t: TemplateInfo }) {
  const [lo, hi] = t.recommended_duration_seconds;
  return (
    <details className="rounded-2xl border border-border bg-surface p-4 text-sm">
      <summary className="cursor-pointer">
        <span className="font-medium">{t.display_name}</span>
        <span className="text-muted"> · {KIND[t.content_type]} · {COST[t.estimated_render_cost]}</span>
      </summary>
      <div className="mt-3 flex gap-4">
        {t.poster && (
          // eslint-disable-next-line @next/next/no-img-element -- a small static sample
          <img src={t.poster} alt="" className="h-48 w-[108px] shrink-0 rounded-lg bg-background object-cover" />
        )}
        <dl className="grid flex-1 gap-x-4 gap-y-2 text-xs sm:grid-cols-[7rem_1fr]">
          <dt className="text-muted">What it is</dt><dd>{t.format}</dd>
          <dt className="text-muted">Structure</dt><dd>{t.scene_structure.map(words).join(" → ")}</dd>
          <dt className="text-muted">Best for</dt><dd>{t.best_for.join(", ")}</dd>
          <dt className="text-muted">Needs</dt><dd>{t.required_assets.map(words).join(", ")}</dd>
          <dt className="text-muted">Length</dt>
          <dd>{t.render.slides ? `${t.render.slides.count[0]}-${t.render.slides.count[1]} slides` : `${lo}-${hi} s`}</dd>
          {t.rights_requirements.length > 0 && (<><dt className="text-muted">Rights</dt><dd>{t.rights_requirements.join(" ")}</dd></>)}
          {t.platform_notes.length > 0 && (<><dt className="text-muted">Notes</dt><dd>{t.platform_notes.join(" ")}</dd></>)}
        </dl>
      </div>
    </details>
  );
}

const AUDIO: Record<string, string> = { kokoro: "Narrated voice-over", ltx_native: "Characters speak", none: "No voice — text, music and sound" };

export function FormatEditor({ format, template, defaults, placeholders, results }: {
  format: FormatData; template: TemplateInfo; defaults: Defaults;
  placeholders: { idea_prompt: readonly string[]; script_prompt: readonly string[] };
  results: string | null;
}) {
  const [state, action, pending] = useActionState<ActionState, FormData>(
    updateFormat.bind(null, format.id, format.template_id), null);
  const [v, setV] = useState({
    idea_prompt: format.idea_prompt, visual_style: format.visual_style,
    // An empty prompt follows the template's own: show it, so saving keeps it.
    script_prompt: format.script_prompt || defaults.script_prompt,
  });
  const set = (k: keyof typeof v) => (val: string) => setV((s) => ({ ...s, [k]: val }));
  const video = template.content_type === "video";
  const audios = useMemo(() => template.render.audios, [template]);
  return (
    <form action={action} className="flex flex-col gap-4">
      <TemplateCard t={template} />
      {results && <p className="rounded-xl bg-accent/10 px-3 py-2 text-sm text-accent">{results}</p>}
      <section className="grid gap-3 rounded-2xl border border-border bg-surface p-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">Name
          <input name="name" required maxLength={60} defaultValue={format.name} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">What this format is
          <textarea name="description" rows={2} maxLength={1000} defaultValue={format.description} className={input}
                    placeholder="Shown to the idea agent as {format_description}." />
        </label>
        {video ? (
          <>
            <label className="flex flex-col gap-1 text-sm">Audio
              <select name="audio_source" defaultValue={format.audio_source} className={input}>
                {audios.map((a) => <option key={a} value={a}>{AUDIO[a] ?? a}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">Length (seconds)
              <input name="target_seconds" type="number" min={5} max={300} defaultValue={format.target_seconds} className={input} />
            </label>
          </>
        ) : (
          <>
            <input type="hidden" name="audio_source" value="none" />
            <input type="hidden" name="target_seconds" value={format.target_seconds} />
          </>
        )}
      </section>

      <LookFields t={template} params={format.params} />

      <PromptField label={video ? "Look of every generated shot" : "Look of AI pictures"} name="visual_style" rows={4}
                   value={v.visual_style} onChange={set("visual_style")} onReset={() => set("visual_style")(defaults.visual_style)}
                   hint="Describe what should be seen — the model reads every word as something to show, so avoid “no …”." />
      <PromptField label="Idea agent" name="idea_prompt" rows={14} value={v.idea_prompt}
                   onChange={set("idea_prompt")} onReset={() => set("idea_prompt")(defaults.idea_prompt)}
                   placeholders={placeholders.idea_prompt}
                   hint="How the agent turns today's trends into ideas, when this is a category's first format." />
      <PromptField label={video ? "Script writer" : "Slide writer"} name="script_prompt" rows={18} value={v.script_prompt}
                   onChange={set("script_prompt")} onReset={() => set("script_prompt")(defaults.script_prompt)}
                   placeholders={placeholders.script_prompt}
                   hint={`Turns an accepted idea into the ${video ? "script" : "slides"}. The template's guide to its structure and on-screen text is added after it automatically.`} />

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
