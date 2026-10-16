import Link from "next/link";

import { workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";

import { openChannel } from "../channel-actions";
import { AutoRefresh } from "../posts/[id]/post-actions";

export const metadata = { title: "Discover · Content Corpus" };

type ChannelCard = {
  id: string; name: string; niche: string; new_ideas: number; looking: boolean; scheduled: number;
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
                      and j.payload->>'format_id' in (select f.id::text from formats f where f.channel_id = c.id)
                   ) as looking,
            (select count(*) from posts p where p.channel_id = c.id and p.status = 'scheduled')::int as scheduled,
            coalesce((select json_agg(json_build_object('platform', a.platform, 'handle', a.handle, 'status', a.status)
                                      order by a.platform)
                        from channel_accounts a where a.channel_id = c.id), '[]') as accounts
       from channels c order by c.is_default desc, c.name`)).rows as ChannelCard[]);

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-5">
      {channels.some((c) => c.looking) && <AutoRefresh everyMs={5000} />}
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Discover</h1>
          <p className="text-sm text-muted">Pick a channel to swipe through its ideas.</p>
        </div>
        <Link href="/channels" className="rounded-full border border-border px-3 py-1.5 text-sm font-medium hover:border-accent">
          + Channel
        </Link>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2">
        {channels.map((c) => (
          <li key={c.id}>
            <form action={openChannel.bind(null, c.id)}>
              <button className="flex w-full flex-col gap-3 rounded-2xl border border-border bg-surface p-4 text-left transition hover:border-accent active:scale-[.99]">
                <span className="flex items-center gap-3">
                  <span aria-hidden
                        className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-linear-to-br from-indigo-500 via-purple-500 to-pink-500 text-lg font-semibold text-white">
                    {c.name.trim().charAt(0).toUpperCase() || "?"}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{c.name}</span>
                    {c.niche && <span className="line-clamp-2 text-sm text-muted">{c.niche}</span>}
                  </span>
                </span>
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                  <span className={c.new_ideas ? "font-medium text-accent" : "text-muted"}>
                    {c.looking ? "Finding ideas…" : `${c.new_ideas || "No"} new idea${c.new_ideas === 1 ? "" : "s"}`}
                  </span>
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
          </li>
        ))}
      </ul>
    </div>
  );
}
