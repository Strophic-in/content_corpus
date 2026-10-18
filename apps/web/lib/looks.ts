import "server-only";

import fs from "node:fs";
import path from "node:path";

import { promptsDir } from "./prompt-defaults";

// The video looks (prompts/looks/<id>.json, as worker/corpus/looks.py reads them):
// how a post's generated shots look. A channel uses "auto" (Jev picks per post),
// "format" (each format's own look text) or one look.

export type VideoLook = { look_id: string; name: string; realism: "photoreal" | "stylised"; best_for: string[] };

let cache: VideoLook[] | null = null;

export function looks(): VideoLook[] {
  if (!cache) {
    const dir = path.join(/*turbopackIgnore: true*/ promptsDir(), "looks");
    cache = fs.readdirSync(dir).filter((f) => f.endsWith(".json")).sort().map((f) => {
      const l = JSON.parse(fs.readFileSync(path.join(/*turbopackIgnore: true*/ dir, f), "utf8")) as VideoLook;
      return { look_id: l.look_id, name: l.name, realism: l.realism, best_for: l.best_for };
    });
  }
  return cache;
}

export function lookName(id: string | null | undefined): string | null {
  if (!id) return null;
  if (id === "format") return "The format's own look";
  return looks().find((l) => l.look_id === id)?.name ?? null;
}
