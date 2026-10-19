import "server-only";

import fs from "node:fs";
import path from "node:path";

import { promptsDir } from "./prompt-defaults";

// Caption styles and cover styles, as worker/corpus/styles.py reads them
// (prompts/caption_styles/, prompts/thumb_styles/). Previews: public/styles/.

export type StylePreset = { id: string; name: string; description: string; families: string[]; best_for: string[] };

const cache = new Map<string, StylePreset[]>();

function load(kind: "caption_styles" | "thumb_styles"): StylePreset[] {
  if (!cache.has(kind)) {
    const dir = path.join(/*turbopackIgnore: true*/ promptsDir(), kind);
    cache.set(kind, fs.readdirSync(dir).filter((f) => f.endsWith(".json")).sort().map((f) =>
      JSON.parse(fs.readFileSync(path.join(/*turbopackIgnore: true*/ dir, f), "utf8")) as StylePreset));
  }
  return cache.get(kind)!;
}

export const captionStyles = () => load("caption_styles");
export const thumbStyles = () => load("thumb_styles");

export function styleName(kind: "caption" | "thumb", id: string | null | undefined): string | null {
  return (kind === "caption" ? captionStyles() : thumbStyles()).find((s) => s.id === id)?.name ?? null;
}
