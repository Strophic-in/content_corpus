export type PostStatus =
  | "draft" | "scripting" | "awaiting_approval" | "approved" | "queued_for_render" | "rendering"
  | "rendered" | "post_processing" | "ready" | "scheduled" | "published" | "needs_review"
  | "failed" | "cancelled";

type Tone = "neutral" | "busy" | "attention" | "good" | "bad";

export const STATUS: Record<PostStatus, { label: string; tone: Tone }> = {
  draft: { label: "Draft", tone: "neutral" },
  scripting: { label: "Writing script…", tone: "busy" },
  awaiting_approval: { label: "Needs review", tone: "attention" },
  approved: { label: "Approved", tone: "good" },
  queued_for_render: { label: "Queued to render", tone: "busy" },
  rendering: { label: "Rendering", tone: "busy" },
  rendered: { label: "Rendered", tone: "good" },
  post_processing: { label: "Assembling", tone: "busy" },
  ready: { label: "Ready", tone: "good" },
  scheduled: { label: "Scheduled", tone: "good" },
  published: { label: "Published", tone: "good" },
  needs_review: { label: "Needs attention", tone: "bad" },
  failed: { label: "Failed", tone: "bad" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-border/60 text-muted",
  busy: "bg-accent/15 text-accent",
  attention: "bg-warn/15 text-warn",
  good: "bg-ok/15 text-ok",
  bad: "bg-danger/15 text-danger",
};

export function statusBadge(status: string) {
  const s = STATUS[status as PostStatus] ?? { label: status, tone: "neutral" as Tone };
  return { label: s.label, className: TONE_CLASS[s.tone] };
}

/** Statuses during which the page should keep refreshing itself. */
export const IN_FLIGHT = new Set<string>(["scripting", "queued_for_render", "rendering", "post_processing"]);
