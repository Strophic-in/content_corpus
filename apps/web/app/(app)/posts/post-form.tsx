"use client";

import { useActionState } from "react";

import { createPost, updatePost, type ActionState } from "../actions";

type Defaults = {
  slot_date?: string; publish_time?: string | null; topic?: string; brief?: string | null;
  target_seconds?: number | null; format_id?: string | null;
};

const input = "rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";

export function PostForm({ postId, defaults = {}, formats }: {
  postId?: string; defaults?: Defaults; formats: { id: string; name: string; is_default: boolean }[];
}) {
  const action = postId ? updatePost.bind(null, postId) : createPost;
  const [state, formAction, pending] = useActionState<ActionState, FormData>(action, null);
  const fmt = defaults.format_id ?? formats.find((f) => f.is_default)?.id ?? formats[0]?.id;

  return (
    <form action={formAction} className="flex flex-col gap-4">
      <label className="flex flex-col gap-1 text-sm">
        Topic
        <input name="topic" required minLength={3} maxLength={300} defaultValue={defaults.topic}
               placeholder="Why does your stomach growl?" className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Brief <span className="text-xs text-muted">optional — angle, jokes, must-haves, things to avoid</span>
        <textarea name="brief" rows={4} maxLength={2000} defaultValue={defaults.brief ?? ""} className={input} />
      </label>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <label className="col-span-2 flex flex-col gap-1 text-sm sm:col-span-2">
          Format
          <select name="format_id" defaultValue={fmt} className={input}>
            {formats.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Day
          <input name="slot_date" type="date" required defaultValue={defaults.slot_date} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Time
          <input name="publish_time" type="time" step={60} required defaultValue={defaults.publish_time ?? "18:00"} className={input} />
        </label>
        <label className="col-span-2 flex flex-col gap-1 text-sm">
          Length (seconds)
          <input name="target_seconds" type="number" min={5} max={300} placeholder="the format's length"
                 defaultValue={defaults.target_seconds ?? ""} className={input} />
        </label>
      </div>
      {state?.error && <p role="alert" className="rounded-xl bg-danger-surface px-3 py-2 text-sm text-danger">{state.error}</p>}
      {state?.message && <p className="text-sm text-ok">{state.message}</p>}
      <button disabled={pending}
              className="w-fit rounded-xl bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
        {pending ? "Saving…" : postId ? "Save changes" : "Create post"}
      </button>
    </form>
  );
}
