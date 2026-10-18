import { TONE_CLASS } from "@/lib/status";

// What the Library's cards and table say about a post (shared, so they agree).
type Staged = { status: string; live: unknown[]; scheduled: boolean };

// The Library's plain-words status: has it gone out, is it waiting to, or did it stop.
export type Group = "posted" | "scheduled" | "ready" | "review" | "making" | "failed" | "cancelled";
export const GROUP: Record<Group, { label: string; tone: keyof typeof TONE_CLASS }> = {
  posted: { label: "Posted", tone: "good" },
  scheduled: { label: "Scheduled", tone: "good" },
  ready: { label: "Ready to post", tone: "busy" },
  review: { label: "Needs review", tone: "attention" },
  making: { label: "In progress", tone: "neutral" },
  failed: { label: "Failed", tone: "bad" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export function group(p: Staged): Group {
  if (p.status === "published" || p.live.length) return "posted";
  if (p.status === "scheduled" || p.scheduled) return "scheduled";
  if (p.status === "ready" || p.status === "rendered") return "ready";
  if (p.status === "awaiting_approval" || p.status === "needs_review") return "review";
  if (p.status === "failed") return "failed";
  if (p.status === "cancelled") return "cancelled";
  return "making";
}

// The step a post is at, named exactly: a draft has not even a script yet, and
// "being made" for it would be wrong. (hint: what the card's empty frame says.)
export const STEP: Record<string, { label: string; hint: string }> = {
  draft: { label: "Not started", hint: "Script not written yet" },
  scripting: { label: "Writing script", hint: "Writing the script…" },
  awaiting_approval: { label: "Script to review", hint: "Script written — waiting for your OK" },
  needs_review: { label: "Needs attention", hint: "Stopped — open it to see why" },
  approved: { label: "Not rendered yet", hint: "Script approved — not rendered yet" },
  queued_for_render: { label: "Queued to render", hint: "Waiting for a GPU" },
  rendering: { label: "Rendering", hint: "Rendering…" },
  post_processing: { label: "Assembling", hint: "Putting it together…" },
  failed: { label: "Failed", hint: "Failed — open it to see why" },
  cancelled: { label: "Cancelled", hint: "Cancelled" },
};

export function chip(p: Staged, g: Group = group(p)) {
  return g === "making" || g === "review" || g === "failed" ? STEP[p.status]?.label ?? GROUP[g].label : GROUP[g].label;
}

// The filter chips: "Not posted yet" is everything still on its way out.
export const FILTERS: { id: string; label: string; has: (g: Group, status: string) => boolean }[] = [
  { id: "all", label: "All", has: () => true },
  { id: "posted", label: "Posted", has: (g: Group) => g === "posted" },
  { id: "waiting", label: "Not posted yet", has: (g: Group) => ["scheduled", "ready", "review", "making"].includes(g) },
  { id: "notstarted", label: "Not started", has: (_g, s) => s === "draft" },
  { id: "stopped", label: "Failed or cancelled", has: (g: Group) => g === "failed" || g === "cancelled" },
];

export const DOT: Record<keyof typeof TONE_CLASS, string> = {
  neutral: "bg-white/60", busy: "bg-accent", attention: "bg-warn", good: "bg-ok", bad: "bg-danger",
};
