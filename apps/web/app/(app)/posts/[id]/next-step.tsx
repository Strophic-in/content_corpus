"use client";

import { useState, useTransition } from "react";

import { approveScript, generateScript, publishNow, setAutopilot, type ActionState } from "../../actions";
import { bulkPostAction } from "../../library/table-actions";

// The one thing to do next on a post, as a single button — and the autopilot switch
// that does every remaining step without stopping (then posts it at its time).

type Props = {
  postId: string; status: string; autopilot: boolean; scriptId: string | null; publishTime: string | null;
  failedAtAssembly: boolean;
};

const BUSY = new Set(["scripting", "queued_for_render", "rendering", "rendered", "post_processing"]);

export function NextStep({ postId, status, autopilot, scriptId, publishTime, failedAtAssembly }: Props) {
  const [on, setOn] = useState(autopilot);
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  const run = (f: () => Promise<ActionState>) => start(async () => setState(await f()));
  const goAhead = () => run(async () => {
    const r = await bulkPostAction({ ids: [postId], action: "go_ahead" });
    return { ok: r.ok, error: r.ok ? undefined : r.failed[0]?.error ?? r.message, message: r.ok ? "On its way." : undefined };
  });

  let title = "", note = "", primary: { label: string; act: () => void } | null = null;
  let secondary: { label: string; act: () => void } | null = null;
  if (status === "draft") {
    title = "Ready to make"; note = "Write the script, then approve and render it — or let autopilot do it all.";
    primary = { label: "Make it", act: goAhead };
    secondary = { label: "Write the script only", act: () => run(() => generateScript(postId)) };
  } else if (status === "awaiting_approval") {
    title = "The script is ready for you"; note = "Read it below. Approve it as it is, or ask for changes.";
    primary = { label: "Approve & render", act: goAhead };
    if (scriptId) secondary = { label: "Approve only", act: () => run(() => approveScript(scriptId)) };
  } else if (status === "approved") {
    title = "Approved"; note = on ? "It renders as soon as the shots are planned." : "Render it when you're ready.";
    primary = on ? null : { label: "Render now", act: goAhead };
  } else if (status === "failed" || status === "needs_review") {
    title = "It stopped"; note = failedAtAssembly ? "The shots are saved — putting it together again costs nothing."
      : "Try again from where it stopped.";
    primary = { label: "Try again", act: goAhead };
  } else if (BUSY.has(status)) {
    title = "Being made"; note = "This page follows along by itself — you can leave it.";
  } else if (status === "ready") {
    title = "Finished"; note = on ? `Autopilot posts it at ${publishTime ?? "its time"}.` : "Choose where and when to post it below.";
    primary = on ? null : { label: "Post it", act: () => document.getElementById("publish")?.scrollIntoView({ behavior: "smooth" }) };
  } else if (status === "scheduled") {
    title = "Scheduled"; note = publishTime ? `Goes out at ${publishTime} — or post it now.` : "It goes out at its time — or post it now.";
    primary = { label: "Post it now", act: () => run(() => publishNow(postId)) };
  } else if (status === "published") {
    title = "Posted"; note = "Its numbers come in below as they arrive.";
  }

  const flip = () => {
    const next = !on;
    setOn(next);
    start(async () => {
      const r = await setAutopilot(postId, next);
      if (!r?.ok) setOn(!next);
      setState(r);
    });
  };
  const canAuto = !["published", "scheduled", "cancelled"].includes(status);

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{title}</p>
          <p className="text-sm text-muted">{note}</p>
        </div>
        {BUSY.has(status) && <span aria-hidden className="mt-1 size-2.5 shrink-0 animate-pulse rounded-full bg-accent" />}
      </div>
      {(primary || secondary) && (
        <div className="flex flex-wrap items-center gap-2">
          {primary && (
            <button onClick={primary.act} disabled={pending}
                    className="pressable btn-primary rounded-full px-5 py-2 text-sm font-semibold disabled:opacity-60">
              {pending ? "Working…" : primary.label}
            </button>
          )}
          {secondary && (
            <button onClick={secondary.act} disabled={pending}
                    className="pressable rounded-full border border-border px-4 py-2 text-sm hover:border-accent disabled:opacity-60">
              {secondary.label}
            </button>
          )}
        </div>
      )}
      {canAuto && (
        <label className="flex cursor-pointer items-center gap-3 border-t border-border pt-3 text-sm">
          <button type="button" role="switch" aria-checked={on} onClick={flip} disabled={pending}
                  className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? "bg-accent" : "bg-border"}`}>
            <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-all ${on ? "left-[1.375rem]" : "left-0.5"}`} />
          </button>
          <span className="min-w-0">
            <span className="font-medium">Autopilot</span>
            <span className="block text-xs text-muted">Writes, approves, renders and posts it at its time — no stops.</span>
          </span>
        </label>
      )}
      {state?.error && <p className="text-xs text-danger">{state.error}</p>}
      {state?.ok && state.message && <p className="text-xs text-ok">{state.message}</p>}
    </div>
  );
}
