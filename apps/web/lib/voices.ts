import "server-only";

import fs from "node:fs";
import path from "node:path";

import { promptsDir } from "./prompt-defaults";

// Narrator voices and voice styles, as worker/corpus/voices.py reads them
// (prompts/voices/catalog.json, prompts/voice_styles/<id>.json).

export type VoiceInfo = {
  id: string; engine: "kokoro" | "openai"; voice: string; name: string; gender: string; accent: string;
  languages: string[]; tone: string; best_for: string[];
};
export type VoiceStyleInfo = {
  style_id: string; name: string; description: string; speed: number; playful?: boolean; sensitive?: boolean;
  languages?: string[]; best_for: string[]; group?: string; expressive?: boolean; voice_hint?: string;
};

let voiceCache: VoiceInfo[] | null = null;
let styleCache: VoiceStyleInfo[] | null = null;

export function voices(): VoiceInfo[] {
  voiceCache ??= (JSON.parse(fs.readFileSync(
    path.join(/*turbopackIgnore: true*/ promptsDir(), "voices", "catalog.json"), "utf8")) as { voices: VoiceInfo[] }).voices;
  return voiceCache;
}

export function voiceStyles(): VoiceStyleInfo[] {
  if (!styleCache) {
    const dir = path.join(/*turbopackIgnore: true*/ promptsDir(), "voice_styles");
    styleCache = fs.readdirSync(dir).filter((f) => f.endsWith(".json")).sort().map((f) =>
      JSON.parse(fs.readFileSync(path.join(/*turbopackIgnore: true*/ dir, f), "utf8")) as VoiceStyleInfo);
  }
  return styleCache;
}

export function voiceLabel(id: string | null | undefined, style: string | null | undefined): string | null {
  const v = voices().find((x) => x.id === id);
  if (!v) return null;
  const s = voiceStyles().find((x) => x.style_id === style);
  return `${v.name}${s ? ` · ${s.name}` : ""}`;
}

/** A voice's or style's sample, when one was recorded (public/voices/). */
export function sample(kind: "voice" | "style", id: string): string | null {
  const file = `${kind}-${id.replace(":", "_")}.mp3`;
  const pub = path.join(/*turbopackIgnore: true*/ process.cwd(), "public", "voices", file);
  return fs.existsSync(pub) ? `/voices/${file}` : null;
}
