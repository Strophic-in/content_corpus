import "server-only";

import fs from "node:fs";
import path from "node:path";

// The shipped default prompts (repo-root prompts/): where every new format starts
// and what "Reset to default" restores. The Docker image carries them at
// /app/prompts; in development they are two directories up.
// The paths are runtime-only (turbopackIgnore): the image copies prompts/ itself,
// and letting the bundler trace a dynamic path would pull the whole project in.
function promptsDir(): string {
  for (const d of [process.env.PROMPTS_DIR,
                   path.resolve(/*turbopackIgnore: true*/ process.cwd(), "prompts"),
                   path.resolve(/*turbopackIgnore: true*/ process.cwd(), "../../prompts")]) {
    if (d && fs.existsSync(path.join(/*turbopackIgnore: true*/ d, "ideas.md"))) return d;
  }
  throw new Error("default prompts not found — set PROMPTS_DIR");
}

const read = (file: string) =>
  fs.readFileSync(path.join(/*turbopackIgnore: true*/ promptsDir(), file), "utf8").trim();

// narrated: a 3D explainer with a voice-over; dialogue: characters speak; news: a narrated
// news explainer, with the news desk's idea prompt (crime, politics, incidents allowed under
// editorial rules) and an illustrative look that never fakes footage of a real event.
export type Template = "narrated" | "dialogue" | "news";
export type Source = { name: string; url: string };

export function defaultPrompts(template: Template) {
  return {
    idea_prompt: read(template === "news" ? "ideas_news.md" : "ideas.md"),
    script_prompt: read(template === "dialogue" ? "script_reel.md" : "script_narrated.md"),
    visual_style: read(template === "news" ? "visual_style_news.md" : "visual_style.md"),
    sources: JSON.parse(read("sources.json")) as Source[],
    audio_source: template === "dialogue" ? ("ltx_native" as const) : ("kokoro" as const),
  };
}

// What each prompt may use. Unknown {braces} are left as written.
export const PLACEHOLDERS = {
  idea_prompt: ["channel_name", "channel_niche", "channel_audience", "channel_voice", "script_language",
                "category_name", "category_brief", "category_keywords",
                "format_name", "format_description", "trends", "avoid", "rejected", "count"],
  script_prompt: ["channel_name", "channel_niche", "channel_audience", "channel_voice", "script_language",
                  "visual_style", "target_seconds", "shot_count_hint", "narration_words",
                  "narration_words_per_second", "revision_note"],
} as const;
