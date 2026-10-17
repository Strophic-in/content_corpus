"use client";

import { useState, useTransition } from "react";

import { deleteChannel } from "../channel-actions";

/** The card's delete button, and the confirmation that covers the card when pressed. */
export function ChannelDelete({ id, name, posts, ideas, accounts, last }: {
  id: string; name: string; posts: number; ideas: number; accounts: number; last: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const what = [posts && `${posts} post${posts === 1 ? "" : "s"}`, ideas && `${ideas} idea${ideas === 1 ? "" : "s"}`,
                accounts && `${accounts} connected account${accounts === 1 ? "" : "s"}`].filter(Boolean).join(", ");
  return (
    <>
      <button type="button" aria-label={`Delete ${name}`} onClick={() => { setError(null); setAsking(true); }}
              className="absolute top-3 right-3 z-10 flex size-9 items-center justify-center rounded-full text-muted transition hover:bg-danger-surface hover:text-danger">
        <svg viewBox="0 0 24 24" aria-hidden className="size-5" fill="none" stroke="currentColor" strokeWidth={1.8}
             strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" />
        </svg>
      </button>
      {asking && (
        <div role="alertdialog" aria-label={`Delete ${name}?`}
             className="absolute inset-0 z-20 flex flex-col justify-between gap-3 rounded-2xl border border-danger bg-surface p-4">
          {last ? (
            <p className="text-sm">This is your only channel — make another one before deleting it.</p>
          ) : (
            <div className="text-sm">
              <p className="font-medium">Delete “{name}”?</p>
              <p className="mt-1 text-muted">
                {what ? `Its ${what} go with it.` : "It has no posts or ideas yet."} Videos already on YouTube or
                Instagram stay there. This can&apos;t be undone.
              </p>
              {error && <p className="mt-1 text-danger">{error}</p>}
            </div>
          )}
          <div className="flex gap-2">
            <button type="button" onClick={() => setAsking(false)} disabled={pending}
                    className="flex-1 rounded-xl border border-border py-2 text-sm font-medium">Keep it</button>
            {!last && (
              <button type="button" disabled={pending}
                      onClick={() => start(async () => {
                        const r = await deleteChannel(id, "/discover");
                        if (r && !r.ok) setError(r.error ?? "Couldn't delete it.");
                      })}
                      className="flex-1 rounded-xl bg-danger py-2 text-sm font-semibold text-white disabled:opacity-60">
                {pending ? "Deleting…" : "Delete"}
              </button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
