"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState, useTransition } from "react";

import {
  approveScript, cancelPublish, deletePost, generateScript, rejectScript, requestPackage, requestPublish, requestRender,
  setAssetRights,
  type ActionState,
} from "../../actions";

/** Allow or withdraw a piece of footage. */
export function AssetRightsButton({ assetId, allowed }: { assetId: string; allowed: boolean }) {
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  return (
    <span className="flex flex-col items-end gap-1">
      <button disabled={pending} onClick={() => start(async () => setState(await setAssetRights(assetId, !allowed)))}
              className={`text-xs font-medium disabled:opacity-50 ${allowed ? "text-danger" : "text-accent"} hover:underline`}>
        {allowed ? "Don't use it" : "Use it"}
      </button>
      <ErrorNote state={state} />
    </span>
  );
}

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

/** "Write again": a fresh title, caption, first comment and cover. */
export function RepackageButton({ postId }: { postId: string }) {
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  return (
    <span className="flex flex-col gap-1">
      <button disabled={pending} onClick={() => start(async () => setState(await requestPackage(postId)))}
              className="w-fit rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent disabled:opacity-60">
        {pending ? "Asking…" : "Write again"}
      </button>
      {state?.message && <span className="text-xs text-muted">{state.message}</span>}
      <ErrorNote state={state} />
    </span>
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

type Platform = "youtube" | "instagram";
const NAMES: Record<Platform, string> = { youtube: "YouTube", instagram: "Instagram" };
const input = "rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";

/** Choose platforms, then post now (after a second click) or at a time. */
export function PublishForm({ postId, platforms, youtubePrivacy, plannedLocal, tz }: {
  postId: string; platforms: Platform[]; youtubePrivacy: string; plannedLocal: string | null; tz: string;
}) {
  const [chosen, setChosen] = useState<Platform[]>(platforms);
  const [privacy, setPrivacy] = useState(youtubePrivacy);
  const [at, setAt] = useState(plannedLocal ?? "");
  const [confirming, setConfirming] = useState(false);
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  const where = chosen.map((p) => NAMES[p]).join(" and ");
  const go = (when: string | null) => start(async () => {
    setConfirming(false);
    setState(await requestPublish(postId, {
      platforms: chosen, at: when, youtube_privacy: chosen.includes("youtube") ? (privacy as "private") : null,
    }));
  });
  const toggle = (p: Platform) => setChosen((c) => (c.includes(p) ? c.filter((x) => x !== p) : [...c, p]));
  return (
    <div className="flex flex-col gap-3 border-t border-border pt-4">
      <fieldset className="flex flex-wrap gap-x-5 gap-y-2">
        <legend className="mb-2 text-muted">Post to</legend>
        {platforms.map((p) => (
          <label key={p} className="flex items-center gap-2">
            <input type="checkbox" checked={chosen.includes(p)} onChange={() => toggle(p)} className="size-4 accent-accent" />
            {NAMES[p]}
          </label>
        ))}
      </fieldset>
      {chosen.includes("youtube") && (
        <label className="flex flex-wrap items-center gap-2">
          <span className="text-muted">YouTube visibility</span>
          <select value={privacy} onChange={(e) => setPrivacy(e.target.value)} className={input}>
            <option value="public">Public</option>
            <option value="unlisted">Unlisted</option>
            <option value="private">Private</option>
          </select>
        </label>
      )}
      {confirming ? (
        <div className="flex flex-col gap-2 rounded-lg bg-background p-3">
          <p>Post this reel to {where} now?</p>
          <div className="flex gap-2">
            <button disabled={pending} onClick={() => go(null)}
                    className="rounded-md bg-accent px-4 py-2 font-medium text-accent-foreground disabled:opacity-60">
              {pending ? "Starting…" : "Yes, post now"}
            </button>
            <button onClick={() => setConfirming(false)} className="rounded-md border border-border px-4 py-2">Not yet</button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button disabled={pending || !chosen.length} onClick={() => setConfirming(true)}
                  className="rounded-md bg-accent px-4 py-2 font-medium text-accent-foreground disabled:opacity-60">
            Post now
          </button>
          <span className="text-muted">or at</span>
          <input type="datetime-local" step={60} value={at} onChange={(e) => setAt(e.target.value)}
                 aria-label="Date and time to post" className={input} />
          <button disabled={pending || !chosen.length || !at} onClick={() => go(at)}
                  className="rounded-md border border-border px-4 py-2 font-medium disabled:opacity-60">
            {pending ? "Scheduling…" : "Schedule"}
          </button>
        </div>
      )}
      <p className="text-xs text-muted">Times are in {tz}. The caption is the script&apos;s title, description and hashtags.</p>
      <ErrorNote state={state} />
    </div>
  );
}

export function CancelPublishButton({ postId, platform }: { postId: string; platform: Platform }) {
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  return (
    <>
      <button disabled={pending} onClick={() => start(async () => setState(await cancelPublish(postId, platform)))}
              className="text-sm text-danger hover:underline disabled:opacity-60">
        {pending ? "Cancelling…" : "Cancel"}
      </button>
      <ErrorNote state={state} />
    </>
  );
}
