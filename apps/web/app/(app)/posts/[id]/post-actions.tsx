"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState, useTransition } from "react";

import { approveScript, deletePost, generateScript, rejectScript, requestRender, type ActionState } from "../../actions";

/** Re-render the server page every few seconds while work is in flight. */
export function AutoRefresh({ everyMs = 3000 }: { everyMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    const t = setInterval(() => router.refresh(), everyMs);
    return () => clearInterval(t);
  }, [router, everyMs]);
  return null;
}

function ErrorNote({ state }: { state: ActionState }) {
  return state?.error ? (
    <p role="alert" className="rounded-md bg-danger-surface px-3 py-2 text-sm text-danger">{state.error}</p>
  ) : null;
}

export function GenerateButton({ postId, regenerate }: { postId: string; regenerate: boolean }) {
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  return (
    <div className="flex flex-col gap-2">
      <button
        disabled={pending}
        onClick={() => start(async () => setState(await generateScript(postId)))}
        className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60"
      >
        {pending ? "Starting…" : regenerate ? "Write a new version" : "Write script"}
      </button>
      <ErrorNote state={state} />
    </div>
  );
}

export function RenderButton({ postId, retry, label }: { postId: string; retry: boolean; label?: string }) {
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  return (
    <div className="flex flex-col gap-2">
      <button
        disabled={pending}
        onClick={() => start(async () => setState(await requestRender(postId)))}
        className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60"
      >
        {pending ? "Starting…" : label ?? (retry ? "Try rendering again" : "Render reel")}
      </button>
      <ErrorNote state={state} />
    </div>
  );
}

export function ReviewActions({ scriptId }: { scriptId: string }) {
  const [approveState, setApproveState] = useState<ActionState>(null);
  const [approving, start] = useTransition();
  const [rejectState, rejectAction, rejecting] = useActionState<ActionState, FormData>(
    rejectScript.bind(null, scriptId),
    null,
  );
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-warn/40 bg-surface p-5">
      <div>
        <h2 className="font-medium">Your review</h2>
        <p className="text-sm text-muted">Approving fixes this version for rendering; nothing renders without it.</p>
      </div>
      <button
        disabled={approving || rejecting}
        onClick={() => start(async () => setApproveState(await approveScript(scriptId)))}
        className="w-fit rounded-md bg-ok px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
      >
        {approving ? "Approving…" : "Approve script"}
      </button>
      <ErrorNote state={approveState} />
      <form action={rejectAction} className="flex flex-col gap-2 border-t border-border pt-4">
        <label className="flex flex-col gap-1 text-sm">
          Or reject, with a note for the next version
          <textarea name="note" rows={2} maxLength={1000} placeholder="e.g. the hook is slow; make the founder funnier"
                    className="rounded-md border border-border bg-background px-3 py-2 outline-none focus:border-accent" />
        </label>
        <button disabled={approving || rejecting}
                className="w-fit rounded-md border border-border px-4 py-2 text-sm font-medium disabled:opacity-60">
          {rejecting ? "Rejecting…" : "Reject"}
        </button>
        <ErrorNote state={rejectState} />
      </form>
    </section>
  );
}

export function DeletePostButton({ postId }: { postId: string }) {
  const [confirming, setConfirming] = useState(false);
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  if (!confirming)
    return (
      <button onClick={() => setConfirming(true)} className="text-sm text-danger hover:underline">
        Delete post…
      </button>
    );
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm">Delete this post and all its script versions? This can’t be undone.</p>
      <div className="flex gap-2">
        <button disabled={pending} onClick={() => start(async () => setState(await deletePost(postId)))}
                className="rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60">
          {pending ? "Deleting…" : "Delete"}
        </button>
        <button onClick={() => setConfirming(false)} className="rounded-md border border-border px-3 py-1.5 text-sm">
          Keep it
        </button>
      </div>
      <ErrorNote state={state} />
    </div>
  );
}
