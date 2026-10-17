"use client";

import { useActionState } from "react";

import type { ActionState } from "../actions";
import { setConfig, setMember } from "./admin-actions";

const input = "rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-accent";

function Note({ state }: { state: ActionState }) {
  if (!state) return null;
  return <span className={`text-xs ${state.error ? "text-danger" : "text-ok"}`}>{state.error ?? state.message}</span>;
}

export function MemberForm({ userId, status, limitRupees }: {
  userId: string; status: string; limitRupees: number | null;
}) {
  const [state, action, pending] = useActionState<ActionState, FormData>(setMember.bind(null, userId), null);
  return (
    <form action={action} className="flex flex-wrap items-center gap-2">
      <select name="status" defaultValue={status} className={input} aria-label="Status">
        <option value="pending">Waiting</option>
        <option value="active">Active</option>
        <option value="suspended">Suspended</option>
      </select>
      <label className="flex items-center gap-1 text-xs text-muted">₹
        <input name="limit" type="number" min={0} step={1} defaultValue={limitRupees ?? ""} placeholder="no limit"
               className={`${input} w-24`} aria-label="Monthly limit in rupees" />/month
      </label>
      <button disabled={pending} className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground disabled:opacity-60">
        {pending ? "Saving…" : "Save"}
      </button>
      <Note state={state} />
    </form>
  );
}

export function ConfigForm({ approval, limitRupees }: { approval: boolean; limitRupees: number }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(setConfig, null);
  return (
    <form action={action} className="flex flex-col gap-3 text-sm">
      <label className="flex items-center gap-2">
        <input type="checkbox" name="approval" defaultChecked={approval} className="size-4 accent-accent" />
        New accounts wait for my approval
      </label>
      <label className="flex flex-wrap items-center gap-2">A new member&apos;s monthly limit: ₹
        <input name="limit" type="number" min={0} step={1} defaultValue={limitRupees} className={`${input} w-28`} />
      </label>
      <div className="flex items-center gap-3">
        <button disabled={pending} className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
          {pending ? "Saving…" : "Save"}
        </button>
        <Note state={state} />
      </div>
    </form>
  );
}
