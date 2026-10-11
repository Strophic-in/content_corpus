import { workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";

import { AutoRefresh } from "../posts/[id]/post-actions";
import { Deck, type IdeaCard } from "./deck";

export const metadata = { title: "Discover · Content Corpus" };

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export default async function DiscoverPage() {
  const user = await requireUser();
  const { active, formats } = await workspace(user.id);
  const data = await asUser(user.id, async (db) => {
    const ideas = (await db.query(
      `select i.id, i.title, i.hook, i.brief, i.why_now, i.sources, f.name as format_name
         from ideas i left join formats f on f.id = i.format_id
        where i.channel_id = $1 and i.status = 'new' order by i.created_at, i.id`, [active.id])).rows;
    const looking = (await db.query(
      `select count(*)::int as n from jobs where kind = 'suggest_ideas' and state in ('queued','claimed')
          and not_before <= now() + interval '1 minute'
          and payload->>'format_id' in (select id::text from formats where channel_id = $1)`, [active.id])).rows[0].n;
    // The next free day at the channel's usual time: the schedule sheet's suggestion.
    const next = (await db.query(
      `select to_char(d, 'YYYY-MM-DD') as day from generate_series(
                (now() at time zone $2)::date + 1, (now() at time zone $2)::date + 60, interval '1 day') d
        where not exists (select 1 from posts p where p.channel_id = $1 and p.slot_date = d::date)
        limit 1`, [active.id, active.timezone])).rows[0]?.day as string | undefined;
    const today = (await db.query("select to_char(now() at time zone $1, 'YYYY-MM-DD') as d",
                                  [active.timezone])).rows[0].d as string;
    return { ideas, looking, next, today };
  });

  const cards: IdeaCard[] = data.ideas.map((i) => ({
    id: i.id, title: i.title, hook: i.hook, brief: i.brief, whyNow: i.why_now, format: i.format_name ?? "",
    sources: (i.sources as { url: string }[]).map((s) => ({ url: s.url, label: host(s.url) })),
  }));
  const fallbackFormat = formats.find((f) => f.is_default) ?? formats[0];

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4">
      {data.looking > 0 && <AutoRefresh everyMs={5000} />}
      <Deck
        key={active.id}
        cards={cards}
        looking={data.looking > 0}
        channel={{ name: active.name, timezone: active.timezone }}
        formats={formats.map((f) => ({ id: f.id, name: f.name }))}
        defaultFormatId={fallbackFormat?.id ?? ""}
        suggestion={{ date: data.next ?? data.today, time: active.default_publish_time, min: data.today }}
      />
    </div>
  );
}
