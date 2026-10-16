import Link from "next/link";
import { notFound } from "next/navigation";

import { CHANNEL_COLS, FORMAT_COLS, workspace, type Channel, type Format } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";

import { ChannelPicker } from "../../nav";
import { AutoRefresh } from "../../posts/[id]/post-actions";
import { Deck, type IdeaCard } from "../deck";

export const metadata = { title: "Discover · Content Corpus" };

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// One channel's idea cards. The channel comes from the URL, so a link to it always
// shows the same deck whichever channel the rest of the app has open.
export default async function ChannelDeckPage({ params }: { params: Promise<{ channelId: string }> }) {
  const user = await requireUser();
  const { channelId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(channelId)) notFound();
  const { channels } = await workspace(user.id);
  const data = await asUser(user.id, async (db) => {
    const channel = (await db.query(`select ${CHANNEL_COLS} from channels where id = $1`, [channelId]))
      .rows[0] as Channel | undefined;
    if (!channel) return null;
    const formats = (await db.query(
      `select ${FORMAT_COLS} from formats where channel_id = $1 order by is_default desc, name`, [channelId],
    )).rows as Format[];
    const ideas = (await db.query(
      `select i.id, i.title, i.hook, i.brief, i.why_now, i.sources, f.name as format_name
         from ideas i left join formats f on f.id = i.format_id
        where i.channel_id = $1 and i.status = 'new' order by i.created_at, i.id`, [channelId])).rows;
    const looking = (await db.query(
      `select count(*)::int as n from jobs where kind = 'suggest_ideas' and state in ('queued','claimed')
          and not_before <= now() + interval '1 minute'
          and payload->>'format_id' in (select id::text from formats where channel_id = $1)`, [channelId])).rows[0].n;
    // The next free day at the channel's usual time: the schedule sheet's suggestion.
    const next = (await db.query(
      `select to_char(d, 'YYYY-MM-DD') as day from generate_series(
                (now() at time zone $2)::date + 1, (now() at time zone $2)::date + 60, interval '1 day') d
        where not exists (select 1 from posts p where p.channel_id = $1 and p.slot_date = d::date)
        limit 1`, [channelId, channel.timezone])).rows[0]?.day as string | undefined;
    const today = (await db.query("select to_char(now() at time zone $1, 'YYYY-MM-DD') as d",
                                  [channel.timezone])).rows[0].d as string;
    return { channel, formats, ideas, looking, next, today };
  });
  if (!data) notFound();
  const { channel, formats } = data;

  const cards: IdeaCard[] = data.ideas.map((i) => ({
    id: i.id, title: i.title, hook: i.hook, brief: i.brief, whyNow: i.why_now, format: i.format_name ?? "",
    sources: (i.sources as { url: string }[]).map((s) => ({ url: s.url, label: host(s.url) })),
  }));
  const fallbackFormat = formats.find((f) => f.is_default) ?? formats[0];

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-2">
      {data.looking > 0 && <AutoRefresh everyMs={5000} />}
      <Link href="/discover" className="w-fit text-sm text-muted hover:text-foreground">← All channels</Link>
      <Deck
        key={channel.id}
        picker={<ChannelPicker channels={channels.map(({ id, name }) => ({ id, name }))} activeId={channel.id} />}
        cards={cards}
        looking={data.looking > 0}
        channel={{ name: channel.name, timezone: channel.timezone }}
        formats={formats.map((f) => ({ id: f.id, name: f.name }))}
        defaultFormatId={fallbackFormat?.id ?? ""}
        suggestion={{ date: data.next ?? data.today, time: channel.default_publish_time, min: data.today }}
      />
    </div>
  );
}
