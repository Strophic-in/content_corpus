import "server-only";

import fs from "node:fs";
import path from "node:path";

import { promptsDir } from "./prompt-defaults";

// The template registry (prompts/templates/<id>.json), as the worker reads it
// (worker/corpus/templates.py): what each kind of post is, how it renders by
// default, and what it needs. A format is a template plus the owner's prompts and
// params. Read once per process; the files ship with the image.

export type ContentType = "video" | "carousel" | "image";
export type Audio = "kokoro" | "none" | "ltx_native";

export type Template = {
  template_id: string;
  display_name: string;
  content_type: ContentType;
  supported_platforms: string[];
  aspect_ratio: "9:16" | "4:5" | "1:1";
  recommended_duration_seconds: [number, number];
  recommended_slide_count: [number, number] | null;
  required_assets: string[];
  optional_assets: string[];
  scene_structure: string[];
  caption_style: string;
  visual_style: string;
  music_mood: string[];
  music_source_mode: "licensed_asset" | "platform_native" | "none";
  automation_level: "high" | "medium" | "low";
  estimated_render_cost: "low" | "medium" | "high";
  rights_requirements: string[];
  render_notes: string[];
  platform_notes: string[];
  format: string;
  best_for: string[];
  ai_pick: boolean;
  needs_owned_footage: boolean;
  base_prompt: string;
  render: {
    captions: "karaoke" | "beats" | "kinetic" | "speech" | "none";
    layouts?: ("full" | "split")[];
    layout?: "full" | "split";
    transition?: string;
    transitions?: string[];
    audio?: Audio;
    audios?: Audio[];
    slides?: { layout: string; aspect: "4:5" | "1:1"; count: [number, number] };
  };
};

let cache: Map<string, Template> | null = null;

export function templates(): Template[] {
  if (!cache) {
    const dir = path.join(/*turbopackIgnore: true*/ promptsDir(), "templates");
    cache = new Map();
    for (const f of fs.readdirSync(dir).filter((n) => n.endsWith(".json")).sort()) {
      const t = JSON.parse(fs.readFileSync(path.join(/*turbopackIgnore: true*/ dir, f), "utf8")) as Template;
      t.ai_pick ??= true;
      t.needs_owned_footage ??= false;
      t.base_prompt ??= "script_video.md";
      t.recommended_slide_count ??= null;
      t.render.layouts ??= ["full"];
      t.render.layout ??= "full";
      t.render.transition ??= "cut";
      t.render.transitions ??= ["cut"];
      t.render.audio ??= "kokoro";
      t.render.audios ??= [t.render.audio];
      cache.set(t.template_id, t);
    }
  }
  return [...cache.values()];
}

export function template(id: string | null | undefined): Template {
  templates();
  return cache!.get(id ?? "") ?? cache!.get("cinematic_3d_explainer")!;
}

// The order the library shows them in: the owner's likely first picks first.
export const ORDER = [
  "cinematic_3d_explainer", "full_screen_text_overlay", "top_bottom_split_screen", "educational_carousel",
  "picture_above_text_below", "animated_infographic", "documentary_storytelling", "mini_news_explainer",
  "kinetic_typography", "question_answer_demo", "ranked_countdown", "myth_vs_fact", "before_after_comparison",
  "pov_immersive_scenario", "transformation_match_cut", "seamless_loop", "satisfying_process_timelapse",
  "reaction_commentary", "photo_dump_collage", "podcast_interview_clip", "screen_recording_tutorial",
  "character_dialogue",
];

export function ordered(): Template[] {
  const all = templates();
  return [...all].sort((a, b) => (ORDER.indexOf(a.template_id) + 1 || 99) - (ORDER.indexOf(b.template_id) + 1 || 99));
}

/** Where a new format of this template starts. */
export function templateDefaults(id: string) {
  const t = template(id);
  const read = (file: string) =>
    fs.readFileSync(path.join(/*turbopackIgnore: true*/ promptsDir(), file), "utf8").trim();
  const [lo, hi] = t.recommended_duration_seconds;
  return {
    idea_prompt: read(id === "mini_news_explainer" ? "ideas_news.md" : "ideas.md"),
    script_prompt: read(t.base_prompt),
    visual_style: read(id === "mini_news_explainer" ? "visual_style_news.md" : "visual_style.md"),
    audio_source: (t.content_type === "video" ? t.render.audio : "none") as Audio,
    target_seconds: Math.max(5, Math.round((lo + hi) / 2)),
  };
}

export const KIND_LABEL: Record<ContentType, string> = {
  video: "Reel / Short", carousel: "Carousel", image: "Picture post",
};
export const COST_LABEL = { low: "No GPU", medium: "Some GPU", high: "GPU every shot" } as const;

/** The serialisable part a client component needs (library-forms TemplateInfo). */
export function templateInfo(t: Template) {
  return {
    template_id: t.template_id, display_name: t.display_name, content_type: t.content_type, format: t.format,
    best_for: t.best_for, estimated_render_cost: t.estimated_render_cost, needs_owned_footage: t.needs_owned_footage,
    scene_structure: t.scene_structure, recommended_duration_seconds: t.recommended_duration_seconds,
    required_assets: t.required_assets, platform_notes: t.platform_notes, rights_requirements: t.rights_requirements,
    music_source_mode: t.music_source_mode,
    // A sample frame or slide of each template, rendered by `python -m corpus.demo` (public/templates/).
    poster: `/templates/${t.template_id}.jpg`,
    render: {
      captions: t.render.captions, layouts: t.render.layouts ?? ["full"], layout: t.render.layout ?? "full",
      transition: t.render.transition ?? "cut", transitions: t.render.transitions ?? ["cut"],
      audios: t.render.audios ?? ["kokoro"], slides: t.render.slides,
    },
  };
}
