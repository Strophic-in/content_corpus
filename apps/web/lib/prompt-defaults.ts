import "server-only";

import fs from "node:fs";
import path from "node:path";

// The shipped default prompts (repo-root prompts/): where every new format starts
// and what "Reset to default" restores. The Docker image carries them at
// /app/prompts; in development they are two directories up.
function promptsDir(): string {
  for (const d of [process.env.PROMPTS_DIR, path.resolve(process.cwd(), "prompts"), path.resolve(process.cwd(), "../../prompts")]) {
    if (d && fs.existsSync(path.join(d, "ideas.md"))) return d;
  }
  throw new Error("default prompts not found — set PROMPTS_DIR");
}

const read = (file: string) => fs.readFileSync(path.join(promptsDir(), file), "utf8").trim();

export type Template = "narrated" | "dialogue";
export type Source = { name: string; url: string };

export function defaultPrompts(template: Template) {
  return {
    idea_prompt: read("ideas.md"),
    script_prompt: read(template === "narrated" ? "script_narrated.md" : "script_reel.md"),
    visual_style: read("visual_style.md"),
    sources: JSON.parse(read("sources.json")) as Source[],
    audio_source: template === "narrated" ? ("kokoro" as const) : ("ltx_native" as const),
  };
}

// What each prompt may use. Unknown {braces} are left as written.
export const PLACEHOLDERS = {
  idea_prompt: ["channel_name", "channel_niche", "channel_audience", "channel_voice", "script_language",
                "format_name", "format_description", "trends", "avoid", "rejected", "count"],
  script_prompt: ["channel_name", "channel_niche", "channel_audience", "channel_voice", "script_language",
                  "visual_style", "target_seconds", "shot_count_hint", "narration_words",
                  "narration_words_per_second", "revision_note"],
} as const;
