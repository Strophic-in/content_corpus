import Link from "next/link";

import { workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";

import { openChannel } from "../channel-actions";
import { AutoRefresh } from "../posts/[id]/post-actions";
import { ChannelDelete } from "./channel-delete";

export const metadata = { title: "Discover · Content Corpus" };

type ChannelCard = {
  id: string; name: string; niche: string; new_ideas: number; looking: boolean; scheduled: number;
  posts: number; ideas: number; making: number; ready: number;
  accounts: { platform: "youtube" | "instagram"; handle: string | null; status: string }[];
};

const PLATFORM = { youtube: "YouTube", instagram: "Instagram" } as const;

// The home screen: every channel with its waiting ideas. Tapping one opens its
// cards, and makes it the channel the rest of the app (calendar, library) shows.
export default async function DiscoverHome() {
  const user = await requireUser();
  await workspace(user.id);                     // first visit: creates a channel if there is none
  const channels = await asUser(user.id, async (db) => (await db.query(
    `select c.id, c.name, c.niche,
            (select count(*) from ideas i where i.channel_id = c.id and i.status = 'new')::int as new_ideas,
            exists (select 1 from jobs j where j.kind = 'suggest_ideas' and j.state in ('queued','claimed')
                      and j.not_before <= now() + interval '1 minute'
                      and (j.payload->>'channel_id' = c.id::text
                           or j.payload->>'category_id' in (select k.id::text from categories k
                                                              where k.channel_id = c.id))
                   ) as looking,
            (select count(*) from posts p where p.channel_id = c.id and p.status = 'scheduled')::int as scheduled,
            (select count(*) from posts p where p.channel_id = c.id)::int as posts,
            (select count(*) from posts p where p.channel_id = c.id
               and p.status in ('scripting','approved','queued_for_render','rendering','rendered','post_processing'))::int as making,
            (select count(*) from posts p where p.channel_id = c.id and p.status in ('ready','awaiting_approval'))::int as ready,
            (select count(*) from ideas i where i.channel_id = c.id)::int as ideas,
            coalesce((select json_agg(json_build_object('platform', a.platform, 'handle', a.handle, 'status', a.status)
                                      order by a.platform)
                        from channel_accounts a where a.channel_id = c.id), '[]') as accounts
       from channels c order by c.is_default desc, c.name`)).rows as ChannelCard[]);
  const setup = await asUser(user.id, async (db) => (await db.query(
    `select exists (select 1 from user_keys where name = 'openai') as key,
            exists (select 1 from channels where coalesce(niche, '') <> '') as described,
            exists (select 1 from categories k where k.enabled and exists (
                      select 1 from category_sources s where s.category_id = k.id and s.enabled)) as sources,
            exists (select 1 from channel_accounts where status = 'connected') as accounts,
            exists (select 1 from ideas) as ideas`)).rows[0] as
    { key: boolean; described: boolean; sources: boolean; accounts: boolean; ideas: boolean });
  const first = channels[0]?.id;
  const steps = [
    { done: setup.key, label: "Add your OpenAI key", note: "Scripts, captions and covers are written with it.", href: "/settings" },
    { done: setup.described, label: "Describe your channel", note: "Its niche and audience steer every idea and script.",
      href: first ? `/channels/${first}` : "/channels" },
    { done: setup.sources, label: "Pick categories and sources", note: "Where the daily ideas come from.",
      href: first ? `/channels/${first}#categories` : "/channels" },
    { done: setup.accounts, label: "Connect YouTube or Instagram", note: "So finished reels can be posted for you.",
      href: first ? `/channels/${first}` : "/channels" },
    { done: setup.ideas, label: "Get your first ideas", note: "Open the channel and press More ideas.",
      href: first ? `/discover/${first}` : "/discover" },
  ];
  const left = steps.filter((x) => !x.done).length;

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-5">
      {channels.some((c) => c.looking) && <AutoRefresh everyMs={5000} />}
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Discover</h1>
          <p className="text-sm text-muted">Pick a channel to swipe through its ideas.</p>
        </div>
        <span className="flex gap-2">
          <Link href="/channels" className="rounded-full border border-border px-3 py-1.5 text-sm font-medium hover:border-accent">
            + Channel
          </Link>
        </span>
      </div>
      {left > 0 && (
        <section className="flex flex-col gap-3 rounded-2xl border border-accent/30 bg-surface p-5">
          <div className="flex items-baseline gap-3">
            <h2 className="font-semibold">Get set up</h2>
            <span className="text-sm text-muted">{steps.length - left} of {steps.length} done</span>
            <span aria-hidden className="ml-auto h-1.5 w-24 overflow-hidden rounded-full bg-border">
              <span className="btn-primary block h-full" style={{ width: `${((steps.length - left) / steps.length) * 100}%` }} />
            </span>
          </div>
          <ol className="flex flex-col gap-1">
            {steps.map((x, i) => (
              <li key={x.label}>
                <Link href={x.href}
                      className={`pressable flex items-center gap-3 rounded-xl p-2 ${x.done ? "opacity-60" : "hover:bg-background"}`}>
                  <span className={`grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold ${
                    x.done ? "bg-ok text-white" : "bg-border text-muted"}`}>
                    {x.done ? "✓" : i + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block text-sm font-medium ${x.done ? "line-through" : ""}`}>{x.label}</span>
                    {!x.done && <span className="block text-xs text-muted">{x.note}</span>}
                  </span>
                  {!x.done && <span aria-hidden className="text-muted">›</span>}
                </Link>
              </li>
            ))}
          </ol>
        </section>
      )}
      {/* Every card the same shape: name, two lines of niche, then the counts and the
          accounts pinned to the bottom, so cards in a row line up whatever they hold. */}
      <ul className="grid auto-rows-fr gap-3 sm:grid-cols-2">
        {channels.map((c) => (
          <li key={c.id} className="relative">
            <form action={openChannel.bind(null, c.id)} className="h-full">
              <button className="flex h-full w-full flex-col gap-3 rounded-2xl border border-border bg-surface p-4 pr-14 text-left transition hover:border-accent active:scale-[.99]">
                <span className="flex items-start gap-3">
                  <span aria-hidden
                        className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-linear-to-br from-indigo-500 via-purple-500 to-pink-500 text-lg font-semibold text-white">
                    {c.name.trim().charAt(0).toUpperCase() || "?"}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{c.name}</span>
                    <span className="line-clamp-2 min-h-10 text-sm text-muted">{c.niche || "No niche set yet"}</span>
                  </span>
                </span>
                <span className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                  <span className={c.new_ideas ? "font-medium text-accent" : "text-muted"}>
                    {c.looking ? "Finding ideas…" : `${c.new_ideas || "No"} new idea${c.new_ideas === 1 ? "" : "s"}`}
                  </span>
                  {c.making > 0 && <span className="text-muted">{c.making} being made</span>}
                  {c.ready > 0 && <span className="text-warn">{c.ready} waiting for you</span>}
                  {c.scheduled > 0 && <span className="text-muted">{c.scheduled} scheduled</span>}
                </span>
                <span className="flex flex-wrap gap-1.5">
                  {c.accounts.length === 0 && <span className="text-xs text-muted">No accounts connected</span>}
                  {c.accounts.map((a) => (
                    <span key={a.platform}
                          className={`rounded-full px-2 py-0.5 text-xs ${a.status === "connected" ? "bg-ok/15 text-ok" : "bg-warn/15 text-warn"}`}>
                      {PLATFORM[a.platform]}{a.handle ? ` ${a.handle}` : ""}{a.status === "connected" ? "" : " · reconnect"}
                    </span>
                  ))}
                </span>
              </button>
            </form>
            <ChannelDelete id={c.id} name={c.name} posts={c.posts} ideas={c.ideas} accounts={c.accounts.length}
                           last={channels.length < 2} />
          </li>
        ))}
      </ul>
    </div>
  );
}
