"use client";

import { useState, useTransition } from "react";

import type { Video } from "@/lib/youtube";

import type { ActionState } from "../actions";
import { makeIdea } from "./actions";

export function MakeIdea({ categoryId, video }: { categoryId: string | null; video: Video }) {
  const [state, setState] = useState<ActionState>(null);
  const [pending, start] = useTransition();
  if (state?.ok) return <p className="text-xs text-ok">{state.message}</p>;
  return (
    <div className="flex flex-col gap-1">
      <button type="button" disabled={pending || !categoryId}
              onClick={() => categoryId && start(async () => setState(await makeIdea(categoryId, video)))}
              className="w-fit rounded-full bg-accent px-3 py-1.5 text-xs font-semibold text-accent-foreground disabled:opacity-50">
        {pending ? "Sending…" : "Make an idea"}
      </button>
      {state?.error && <p className="text-xs text-danger">{state.error}</p>}
    </div>
  );
}
