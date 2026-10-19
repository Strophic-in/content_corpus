// Where a post is on its way from idea to posted reel, step by step — the one place
// the post page's tracker, the Library and Discover read it from.

export type StepState = "done" | "active" | "waiting" | "todo" | "failed" | "skipped";
export type Step = { id: StepId; label: string; state: StepState; detail?: string };
export type StepId = "sources" | "script" | "review" | "voice" | "render" | "assemble" | "package" | "post";

export type PipelineInput = {
  status: string;
  research_state: "pending" | "ready" | "none" | null;
  assets?: { total: number; pending: number };   // collected for the post, and still being fetched
  slides: boolean;                       // a carousel or picture post (no voice, no GPU)
  narrated: boolean;
  shots: { total: number; uploaded: number; voiced: number };
  packaged: boolean;
  go_ahead: boolean;
  error_stage?: string | null;
  live_on?: string[];                    // platforms it is live on
  publish_time?: string | null;          // "HH:MM" of a scheduled post
};

const ORDER = ["draft", "scripting", "awaiting_approval", "approved", "queued_for_render", "rendering", "rendered",
  "post_processing", "ready", "scheduled", "published"];

// Which step a failure stopped at (posts.error.stage).
const FAILED_AT: Record<string, StepId> = {
  input: "script", config: "script", quota: "script", validate: "script", llm: "script", llm_request: "script",
  llm_rate_limit: "script", llm_model: "script", llm_auth: "script", moderation: "script", fetch: "sources",
  upload: "sources", narration_too_long: "voice", narrate: "voice", render: "render", no_gpu: "render",
  rights: "render", stock: "render", storage_full: "render", download: "assemble", assemble: "assemble",
  package: "package", publish: "post", publish_auth: "post", publish_quota: "post",
};

export function pipeline(p: PipelineInput): Step[] {
  const at = ORDER.indexOf(p.status);
  const past = (s: string) => at > ORDER.indexOf(s);
  const is = (...s: string[]) => s.includes(p.status);
  const steps: Step[] = [];

  const fetching = (p.assets?.pending ?? 0) > 0;
  const collected = p.assets?.total ?? 0;
  steps.push({
    id: "sources", label: "Collect sources & assets",
    state: p.research_state === "pending" || fetching ? "active" : p.research_state || collected ? "done" : "skipped",
    detail: p.research_state === "pending" ? "Reading the reports; finding logos, photos and videos"
      : fetching ? `${collected - (p.assets?.pending ?? 0)} of ${collected} assets ready`
      : collected ? `${collected} asset${collected === 1 ? "" : "s"} collected` : undefined,
  });
  steps.push({
    id: "script", label: p.slides ? "Write the slides" : "Write the script",
    state: is("scripting") ? "active" : is("draft") ? "todo" : at >= ORDER.indexOf("awaiting_approval") ? "done" : "todo",
    detail: is("scripting") ? "The writer is drafting it — usually under a minute" : undefined,
  });
  steps.push({
    id: "review", label: "Your review",
    state: is("awaiting_approval") ? (p.go_ahead ? "active" : "waiting") : past("awaiting_approval") ? "done" : "todo",
    detail: is("awaiting_approval") ? (p.go_ahead ? "Approving it for you (autopilot)" : "Read it and approve, or ask for changes")
      : p.go_ahead && at < ORDER.indexOf("awaiting_approval") ? "On autopilot: approved as written" : undefined,
  });
  if (!p.slides) {
    const voiced = p.narrated ? p.shots.voiced : p.shots.total;
    const planning = is("approved") && (p.shots.total === 0 || voiced < p.shots.total);
    steps.push({
      id: "voice", label: p.narrated ? "Plan the shots and record the voice" : "Plan the shots",
      state: planning ? "active" : is("approved") || past("approved") ? "done" : "todo",
      detail: planning ? (p.shots.total ? `${voiced} of ${p.shots.total} lines recorded` : "Planning the shots") : undefined,
    });
  }
  const rendering = is("queued_for_render", "rendering");
  steps.push({
    id: "render", label: p.slides ? "Draw the slides" : "Render the shots",
    state: rendering ? "active" : is("approved") && !p.go_ahead ? "waiting"
      : past("rendering") || is("rendered") ? "done" : "todo",
    detail: rendering ? (is("queued_for_render") ? "Waiting for a GPU"
      : p.shots.total ? `${p.shots.uploaded} of ${p.shots.total} shots done` : "Rendering")
      : is("approved") && !p.go_ahead ? "Ready when you are" : undefined,
  });
  steps.push({
    id: "assemble", label: "Put the reel together",
    state: is("rendered", "post_processing") ? "active" : past("post_processing") ? "done" : "todo",
    detail: is("rendered", "post_processing") ? "Joining shots, captions, voice and music" : undefined,
  });
  steps.push({
    id: "package", label: "Write the caption and cover",
    state: past("post_processing") ? (p.packaged ? "done" : "active") : "todo",
    detail: past("post_processing") && !p.packaged ? "Title, caption, sources, hashtags and a cover" : undefined,
  });
  const live = p.live_on ?? [];
  steps.push({
    id: "post", label: "Post it",
    state: is("published") || live.length ? "done" : is("scheduled") ? "active" : is("ready") ? "waiting" : "todo",
    detail: live.length ? `Live on ${live.join(" and ")}` : is("scheduled") ? `Scheduled${p.publish_time ? ` for ${p.publish_time}` : ""}`
      : is("ready") ? "Choose where and when" : undefined,
  });

  if (is("failed", "needs_review")) {
    const stop = FAILED_AT[p.error_stage ?? ""] ?? (p.shots.uploaded ? "render" : "script");
    let reached = false;
    for (const s of steps) {
      if (s.state === "skipped") continue;
      if (s.id === stop) { s.state = "failed"; reached = true; continue; }
      if (!reached) s.state = "done";
      else s.state = "todo";
    }
  }
  return steps;
}

/** How far along, 0-1, for a bar (the Library's cards). */
export function progress(status: string): number {
  if (status === "published") return 1;
  const at = ORDER.indexOf(status);
  return at < 0 ? 0 : Math.max(0.04, at / (ORDER.length - 1));
}
