"use client";

import { useActionState, useState, useTransition } from "react";

import type { ActionState } from "../actions";
import { createChannel, deleteChannel, disconnectAccount, makeDefaultChannel, updateChannel } from "../channel-actions";

const input = "rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent";

function Feedback({ state }: { state: ActionState }) {
  if (state?.error) return <p role="alert" className="rounded-xl bg-danger-surface px-3 py-2 text-sm text-danger">{state.error}</p>;
  if (state?.message) return <p className="text-sm text-ok">{state.message}</p>;
  return null;
}

type ChannelData = {
  id: string; name: string; niche: string; audience: string; voice: string; language: string; timezone: string;
  default_publish_time: string; ideas_daily: boolean; ideas_daily_at: string; video_look?: string;
};
export type LookOption = { look_id: string; name: string; best_for: string[] };

export function ChannelForm({ channel, looks = [] }: { channel?: ChannelData; looks?: LookOption[] }) {
  const action = channel ? updateChannel.bind(null, channel.id) : createChannel;
  const [state, formAction, pending] = useActionState<ActionState, FormData>(action, null);
  const c = channel;
  return (
    <form action={formAction} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <label className="flex flex-col gap-1 text-sm sm:col-span-2">Name
        <input name="name" required maxLength={80} defaultValue={c?.name} placeholder="Cutaway" className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm sm:col-span-2">Niche
        <textarea name="niche" rows={2} maxLength={500} defaultValue={c?.niche} className={input}
                  placeholder="3D-animated explainers of the body, science and everyday things" />
      </label>
      <label className="flex flex-col gap-1 text-sm">Audience
        <textarea name="audience" rows={2} maxLength={500} defaultValue={c?.audience} className={input}
                  placeholder="Curious 16-35-year-olds who scroll Shorts" />
      </label>
      <label className="flex flex-col gap-1 text-sm">Voice
        <textarea name="voice" rows={2} maxLength={500} defaultValue={c?.voice} className={input}
                  placeholder="Calm, punchy, slightly eerie" />
      </label>
      <label className="flex flex-col gap-1 text-sm">Language
        <input name="language" required defaultValue={c?.language ?? "English"} className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">Timezone
        <input name="timezone" required defaultValue={c?.timezone ?? "Asia/Kolkata"} className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">Usual posting time
        <input name="default_publish_time" type="time" step={60} required defaultValue={c?.default_publish_time ?? "18:00"} className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm">New ideas every day at
        <input name="ideas_daily_at" type="time" step={60} required defaultValue={c?.ideas_daily_at ?? "08:00"} className={input} />
      </label>
      <label className="flex flex-col gap-1 text-sm sm:col-span-2">Video look
        <select name="video_look" defaultValue={c?.video_look ?? "auto"} className={input}>
          <option value="auto">Auto — Jev picks the best look for each story</option>
          <option value="format">Each format&apos;s own look text</option>
          {looks.map((l) => <option key={l.look_id} value={l.look_id}>{l.name} — {l.best_for.slice(0, 3).join(", ")}</option>)}
        </select>
        <span className="text-xs text-muted">How generated shots look: photoreal, documentary, 3D, cartoon, anime, retro,
          black and white… Real footage always stays as filmed. Sensitive stories never get a playful look.</span>
      </label>
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <input name="ideas_daily" type="checkbox" defaultChecked={c?.ideas_daily ?? true} className="size-4 accent-[var(--accent)]" />
        Find new ideas automatically every day
      </label>
      <div className="flex flex-col gap-2 sm:col-span-2">
        <Feedback state={state} />
        <button disabled={pending} className="w-fit rounded-xl bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60">
          {pending ? "Saving…" : c ? "Save" : "Create channel"}
        </button>
      </div>
    </form>
  );
}

export function ChannelMenu({ channelId, isDefault }: { channelId: string; isDefault: boolean }) {
  const [pending, start] = useTransition();
  const [state, setState] = useState<ActionState>(null);
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex gap-2">
        {!isDefault && (
          <button disabled={pending} onClick={() => start(async () => setState(await makeDefaultChannel(channelId)))}
                  className="rounded-xl border border-border px-3 py-1.5 text-sm hover:border-accent">Make default</button>
        )}
        <button disabled={pending}
                onClick={() => confirm("Delete this channel with its posts, ideas, formats and connected accounts? "
                  + "Videos already on YouTube or Instagram stay there. This can't be undone.") &&
                  start(async () => setState(await deleteChannel(channelId)))}
                className="rounded-xl border border-border px-3 py-1.5 text-sm text-danger hover:border-danger">Delete</button>
      </div>
      <Feedback state={state} />
    </div>
  );
}

type AccountData = { id: string; handle: string | null; display_name: string | null; avatar_url: string | null;
                     status: string; token_expires_at: Date | null };

const NAMES = { youtube: "YouTube", instagram: "Instagram" } as const;
const NOTES = {
  youtube: "Uploads your finished Shorts. Until Google reviews the app, uploads stay private.",
  instagram: "Posts your reels to an Instagram professional (creator or business) account.",
} as const;

export function ConnectionCard({ platform, channelId, account, ready }: {
  platform: "youtube" | "instagram"; channelId: string; account: AccountData | null; ready: boolean;
}) {
  const [pending, start] = useTransition();
  const [state, setState] = useState<ActionState>(null);
  const connected = account?.status === "connected";
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4">
      <div className="flex items-center gap-3">
        {account?.avatar_url
          // eslint-disable-next-line @next/next/no-img-element
          ? <img src={account.avatar_url} alt="" className="size-10 rounded-full" />
          : <span className="grid size-10 place-items-center rounded-full bg-background text-sm font-semibold text-muted">
              {platform === "youtube" ? "YT" : "IG"}
            </span>}
        <div className="min-w-0 flex-1">
          <p className="font-medium">{NAMES[platform]}</p>
          <p className="truncate text-sm text-muted">
            {connected ? (account?.handle ?? account?.display_name) : account ? `Needs reconnecting (${account.status})` : "Not connected"}
          </p>
        </div>
      </div>
      <p className="text-xs text-muted">{NOTES[platform]}</p>
      <div className="flex gap-2">
        {ready ? (
          <a href={`/api/connect/${platform}/start?channel=${channelId}`}
             className="rounded-xl bg-accent px-3 py-2 text-sm font-medium text-accent-foreground">
            {connected ? "Reconnect" : `Connect ${NAMES[platform]}`}
          </a>
        ) : (
          <span className="rounded-xl border border-dashed border-border px-3 py-2 text-sm text-muted">Waiting for app keys on the server</span>
        )}
        {account && (
          <button disabled={pending} onClick={() => start(async () => setState(await disconnectAccount(account.id)))}
                  className="rounded-xl border border-border px-3 py-2 text-sm hover:border-danger hover:text-danger">Disconnect</button>
        )}
      </div>
      <Feedback state={state} />
    </div>
  );
}
