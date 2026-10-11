"use client";

import { useActionState } from "react";

import { createPost, updatePost, type ActionState } from "../actions";

type Defaults = { slot_date?: string; topic?: string; brief?: string | null; target_seconds?: number | null };

const input = "rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";

export function PostForm({ postId, defaults = {} }: { postId?: string; defaults?: Defaults }) {
  const action = postId ? updatePost.bind(null, postId) : createPost;
  const [state, formAction, pending] = useActionState<ActionState, FormData>(action, null);

  return (
    <form action={formAction} className="flex flex-col gap-4">
      <label className="flex flex-col gap-1 text-sm">
        Topic
        <input name="topic" required minLength={3} maxLength={300} defaultValue={defaults.topic}
               placeholder="Startup founders 5 minutes before a client escalation" className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Brief <span className="text-xs text-muted">optional — angle, jokes, must-haves, things to avoid</span>
        <textarea name="brief" rows={4} maxLength={2000} defaultValue={defaults.brief ?? ""} className={input} />
      </label>
      <div className="grid grid-cols-2 gap-4">
        <label className="flex flex-col gap-1 text-sm">
          Day
          <input name="slot_date" type="date" required defaultValue={defaults.slot_date} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Length (seconds)
          <input name="target_seconds" type="number" min={5} max={90} placeholder="default"
                 defaultValue={defaults.target_seconds ?? ""} className={input} />
        </label>
      </div>
      {state?.error && <p role="alert" className="rounded-md bg-danger-surface px-3 py-2 text-sm text-danger">{state.error}</p>}
      {state?.message && <p className="text-sm text-ok">{state.message}</p>}
      <button disabled={pending}
              className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
        {pending ? "Saving…" : postId ? "Save changes" : "Create post"}
      </button>
    </form>
  );
}
