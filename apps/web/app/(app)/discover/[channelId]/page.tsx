import Link from "next/link";
import { notFound } from "next/navigation";

import { CHANNEL_COLS, workspace, type Channel } from "@/lib/channels";
import { currentFx } from "@/lib/costs";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";
import { KIND_LABEL, template } from "@/lib/templates";

import { ChannelPicker } from "../../nav";
import { AutoRefresh } from "../../posts/[id]/post-actions";
import { DailyIdeasPause } from "../daily-pause";
import { Deck, type CardMedia, type IdeaCard } from "../deck";

export const metadata = { title: "Discover · Content Corpus" };

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

type Row = {
  id: string; title: string; hook: string; brief: string; why_now: string; category_id: string | null;
  media_state: string; created_at: Date; format_id: string | null; format_why: string; cost: number | null;
  media: { type: "image" | "video"; w: number; h: number; seconds?: number; credit?: string; gallery?: boolean;
           poster_key?: string }[];
  items: { url?: string; title?: string; source?: string; subreddit?: string; author?: string; platform?: string }[];
  sources: { url: string }[];
  analysis: { video?: { summary?: string; logos_or_watermarks?: boolean; logo_names?: string[]; graphic?: boolean;
                        identifiable_people?: boolean } } | null;
};

/** Categories take turns (newest first within each), so a busy one can't bury the rest. */
function roundRobin(rows: Row[]): Row[] {
  const groups = new Map<string, Row[]>();
  for (const r of rows) {
    const k = r.category_id ?? "none";
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }
  const lists = [...groups.values()];
  const out: Row[] = [];
  for (let i = 0; out.length < rows.length; i++) for (const l of lists) if (l[i]) out.push(l[i]);
  return out;
}

type FormatOpt = { id: string; name: string; kind: string };

function card(r: Row, cats: Map<string, { id: string; name: string; color: string }>,
              fmts: Map<string, FormatOpt>): IdeaCard {
  const v = r.analysis?.video;
  const flags: string[] = [];
  if (v?.logos_or_watermarks) flags.push(v.logo_names?.length ? `Logo: ${v.logo_names.join(", ")}` : "Watermark or logo");
  if (v?.graphic) flags.push("Graphic content");
  if (v?.identifiable_people) flags.push("Identifiable people");
  const media: CardMedia[] = (r.media ?? []).map((m, n) => ({
    type: m.type, w: m.w, h: m.h, seconds: m.seconds, credit: m.credit, gallery: m.gallery,
    src: `/media/idea/${r.id}/${n}`, poster: m.poster_key ? `/media/idea/${r.id}/${n}?poster=1` : undefined,
  }));
  type Src = Row["items"][number];
  const sources = (r.items?.length ? r.items : r.sources.map((s): Src => ({ url: s.url })))
    .filter((s) => s.url)
    .map((s) => s.subreddit
      ? { url: s.url!, label: `r/${s.subreddit}`, detail: s.author ? `u/${s.author}` : undefined }
      : s.platform && s.source
        ? { url: s.url!, label: s.source, detail: s.author ?? undefined }
        : { url: s.url!, label: host(s.url!), detail: s.title && s.title !== r.title ? s.title : undefined });
  return {
    id: r.id, title: r.title, hook: r.hook, brief: r.brief, whyNow: r.why_now,
    category: r.category_id ? cats.get(r.category_id) ?? null : null,
    format: r.format_id ? fmts.get(r.format_id) ?? null : null, formatWhy: r.format_why ?? "",
    media, mediaPending: r.media_state === "pending", summary: v?.summary ?? null, flags, sources,
    cost: r.cost,
  };
}

// One channel's idea cards, every category mixed. The channel comes from the URL,
// so a link to it always shows the same deck whichever channel the app has open.
export default async function ChannelDeckPage({ params }: { params: Promise<{ channelId: string }> }) {
  const user = await requireUser();
  const { channelId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(channelId)) notFound();
  const { channels } = await workspace(user.id);
  const data = await asUser(user.id, async (db) => {
    const channel = (await db.query(`select ${CHANNEL_COLS} from channels where id = $1`, [channelId]))
      .rows[0] as Channel | undefined;
    if (!channel) return null;
    const categories = (await db.query(
      "select id, name, color from categories where channel_id = $1 and enabled order by created_at", [channelId],
    )).rows as { id: string; name: string; color: string }[];
    // What each idea has cost so far: its share of the batch that wrote it (the agent's
    // call, Jev's ranking), plus the checks on its own media (safety, what a video shows).
    const inr = `case when c.inr_paise is not null then c.inr_paise / 100.0
                      when c.usd_micros is not null then c.usd_micros / 1e6 * coalesce(c.fx_usd_inr, $2) end`;
    const ideas = (await db.query(
      `select i.id, i.title, i.hook, i.brief, i.why_now, i.category_id, i.media_state, i.created_at, i.media, i.items,
              i.sources, i.analysis, i.format_id, i.format_why,
              (coalesce((select sum(${inr}) from costs c where c.job_id = i.batch_job_id), 0)
                 / greatest((select count(*) from ideas x where x.batch_job_id = i.batch_job_id), 1)
               + coalesce((select sum(${inr}) from costs c join jobs j on j.id = c.job_id
                            where j.kind = 'attach_media' and j.payload->>'idea_id' = i.id::text), 0))::float8 as cost
         from ideas i where i.channel_id = $1 and i.status = 'new' order by i.created_at desc, i.id`,
      [channelId, await currentFx(db)])).rows as Row[];
    const formats = (await db.query(
      "select id, name, template_id from formats where channel_id = $1 order by is_default desc, created_at",
      [channelId])).rows as { id: string; name: string; template_id: string }[];
    const accounts = (await db.query(
      "select platform from channel_accounts where channel_id = $1 and status = 'connected' order by platform",
      [channelId])).rows as { platform: "youtube" | "instagram" }[];
    const looking = (await db.query(
      `select count(*)::int as n from jobs where lane = 'ideas' and state in ('queued','claimed')
          and kind in ('suggest_ideas','attach_media') and not_before <= now() + interval '1 minute'
          and (payload->>'channel_id' = $1::text
               or payload->>'category_id' in (select id::text from categories where channel_id = $1::uuid)
               or payload->>'idea_id' in (select id::text from ideas where channel_id = $1::uuid and status = 'new'))`,
      [channelId])).rows[0].n as number;
    // The next free day at the channel's usual time: the schedule sheet's suggestion.
    const next = (await db.query(
      `select to_char(d, 'YYYY-MM-DD') as day from generate_series(
                (now() at time zone $2)::date + 1, (now() at time zone $2)::date + 60, interval '1 day') d
        where not exists (select 1 from posts p where p.channel_id = $1 and p.slot_date = d::date)
        limit 1`, [channelId, channel.timezone])).rows[0]?.day as string | undefined;
    const today = (await db.query("select to_char(now() at time zone $1, 'YYYY-MM-DD') as d",
                                  [channel.timezone])).rows[0].d as string;
    return { channel, categories, ideas, formats, accounts, looking, next, today };
  });
  if (!data) notFound();
  const { channel, categories } = data;
  const cats = new Map(categories.map((c) => [c.id, c]));
  const formats: FormatOpt[] = data.formats.map((f) => ({ id: f.id, name: f.name,
                                                          kind: KIND_LABEL[template(f.template_id).content_type] }));
  const fmts = new Map(formats.map((f) => [f.id, f]));
  const cards = roundRobin(data.ideas).map((r) => card(r, cats, fmts));
  const names = { youtube: "YouTube", instagram: "Instagram" } as const;

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-2">
      {data.looking > 0 && <AutoRefresh everyMs={5000} />}
      <Link href="/discover" className="w-fit text-sm text-muted hover:text-foreground">← All channels</Link>
      <Deck
        key={channel.id}
        picker={<ChannelPicker channels={channels.map(({ id, name }) => ({ id, name }))} activeId={channel.id} />}
        daily={<DailyIdeasPause channelId={channel.id} daily={channel.ideas_daily} at={channel.ideas_daily_at}
                                paused={channel.ideas_paused} />}
        cards={cards}
        looking={data.looking > 0}
        channel={{ id: channel.id, name: channel.name, timezone: channel.timezone }}
        categories={categories}
        formats={formats}
        platforms={data.accounts.map((a) => ({ id: a.platform, label: names[a.platform] }))}
        suggestion={{ date: data.next ?? data.today, time: channel.default_publish_time, min: data.today }}
      />
    </div>
  );
}
