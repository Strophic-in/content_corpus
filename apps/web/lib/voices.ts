import "server-only";

import fs from "node:fs";
import path from "node:path";

import { promptsDir } from "./prompt-defaults";

// Narrator voices, as worker/corpus/voices.py reads them (prompts/voices/catalog.json).

export type VoiceInfo = {
  id: string; engine: "kokoro" | "openai"; voice: string; name: string; gender: string; accent: string;
  languages: string[]; tone: string; best_for: string[];
};

let voiceCache: VoiceInfo[] | null = null;

export function voices(): VoiceInfo[] {
  voiceCache ??= (JSON.parse(fs.readFileSync(
    path.join(/*turbopackIgnore: true*/ promptsDir(), "voices", "catalog.json"), "utf8")) as { voices: VoiceInfo[] }).voices;
  return voiceCache;
}

export function voiceLabel(id: string | null | undefined): string | null {
  return voices().find((x) => x.id === id)?.name ?? null;
}

/** A voice's sample, when one was recorded (public/voices/). */
export function sample(id: string): string | null {
  const file = `voice-${id.replace(":", "_")}.mp3`;
  const pub = path.join(/*turbopackIgnore: true*/ process.cwd(), "public", "voices", file);
  return fs.existsSync(pub) ? `/voices/${file}` : null;
}
