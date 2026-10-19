"use client";

import { useState, useTransition } from "react";

import { addAssetLink, collectAssets, type ActionState } from "../../actions";

/** Paste a link — a picture, a video (YouTube, X, a news player) or an article (its main picture). */
export function AddLink({ postId }: { postId: string }) {
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState<"auto" | "image" | "video">("auto");
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  const add = () => start(async () => {
    const r = await addAssetLink(postId, url, kind);
    setState(r);
    if (r?.ok) setUrl("");
  });
  return (
    <form className="flex flex-col gap-1.5" onSubmit={(e) => { e.preventDefault(); if (url.trim()) add(); }}>
      <div className="flex flex-wrap gap-2">
        <input type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} disabled={pending}
               placeholder="Paste a link to a picture, a video or an article"
               className="min-w-0 flex-1 basis-60 rounded-md border border-border bg-background px-3 py-2 text-sm" />
        <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} disabled={pending}
                aria-label="What the link is" className="rounded-md border border-border bg-background px-2 py-2 text-sm">
          <option value="auto">Work it out</option>
          <option value="image">A picture</option>
          <option value="video">A video</option>
        </select>
        <button type="submit" disabled={pending || !url.trim()}
                className="pressable rounded-md border border-border px-3 py-2 text-sm font-medium hover:border-accent disabled:opacity-50">
          {pending ? "Adding…" : "Add link"}
        </button>
      </div>
      {state?.error ? <p className="text-xs text-danger">{state.error}</p>
        : state?.ok ? <p className="text-xs text-ok">Added — fetching it now.</p>
        : <p className="text-xs text-muted">An article link adds its main picture; a video link (YouTube, X, a news
            site&apos;s player) adds the video. It&apos;s credited to the site it came from.</p>}
    </form>
  );
}

export function CollectAgain({ postId, first }: { postId: string; first: boolean }) {
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  return (
    <span className="flex shrink-0 flex-col items-end gap-1">
      <button type="button" disabled={pending} onClick={() => start(async () => setState(await collectAssets(postId)))}
              className="pressable rounded-full border border-border px-3 py-1.5 text-xs font-medium hover:border-accent disabled:opacity-50">
        {pending ? "Starting…" : first ? "Collect assets" : "Collect again"}
      </button>
      {state?.error && <span className="max-w-56 text-right text-xs text-danger">{state.error}</span>}
    </span>
  );
}
