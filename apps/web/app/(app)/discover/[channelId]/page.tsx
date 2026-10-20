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
import { Deck, type Ask, type CardMedia, type IdeaCard } from "../deck";

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
  asked: boolean;
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
    cost: r.cost, asked: r.asked,
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
              exists (select 1 from jobs j where j.id = i.batch_job_id
                         and j.kind in ('idea_from_topic', 'idea_from_video')) as asked,
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
    // What the owner asked for (Your idea; Explore's Make an idea): still being written,
    // or failed lately, and why.
    const asks = (await db.query(
      `select j.id, j.kind, j.state, j.error->>'message' as error,
              coalesce(nullif(j.payload->>'topic', ''), j.payload->'video'->>'title', '') as what
         from jobs j
        where j.lane = 'ideas' and j.kind in ('idea_from_topic', 'idea_from_video')
          and j.payload->>'category_id' in (select id::text from categories where channel_id = $1::uuid)
          and (j.state in ('queued', 'claimed')
               or (j.state in ('failed', 'dead') and j.finished_at > now() - interval '12 hours'))
        order by j.created_at desc limit 5`, [channelId])).rows as
      { id: string; kind: string; state: string; error: string | null; what: string }[];
    // An idea picked today goes out today (owner, 2026-10-19): at the channel's usual
    // time, or two hours from now when that is under 90 minutes away or past (then
    // tomorrow at the usual time, if two hours from now is already tomorrow).
    const slot = (await db.query(
      `with t as (select now() at time zone $1 as now_local, ($1)::text as tz)
       select case when (now_local::date + $2::time) - now_local >= interval '90 minutes'
                   then to_char(now_local, 'YYYY-MM-DD')
                   when (now_local + interval '2 hours')::date = now_local::date then to_char(now_local, 'YYYY-MM-DD')
                   else to_char(now_local + interval '1 day', 'YYYY-MM-DD') end as day,
              case when (now_local::date + $2::time) - now_local >= interval '90 minutes' then to_char($2::time, 'HH24:MI')
                   when (now_local + interval '2 hours')::date = now_local::date
                     then to_char(date_trunc('hour', now_local + interval '2 hours 59 minutes'), 'HH24:MI')
                   else to_char($2::time, 'HH24:MI') end as time
         from t`, [channel.timezone, channel.default_publish_time])).rows[0] as { day: string; time: string };
    const today = (await db.query("select to_char(now() at time zone $1, 'YYYY-MM-DD') as d",
                                  [channel.timezone])).rows[0].d as string;
    return { channel, categories, ideas, formats, accounts, looking, asks, slot, today };
  });
  if (!data) notFound();
  const { channel, categories } = data;
  const cats = new Map(categories.map((c) => [c.id, c]));
  const formats: FormatOpt[] = data.formats.map((f) => ({ id: f.id, name: f.name,
                                                          kind: KIND_LABEL[template(f.template_id).content_type] }));
  const fmts = new Map(formats.map((f) => [f.id, f]));
  // What the owner asked for comes first.
  const cards = [...data.ideas.filter((r) => r.asked), ...roundRobin(data.ideas.filter((r) => !r.asked))]
    .map((r) => card(r, cats, fmts));
  const asks: Ask[] = data.asks.map((a) => ({
    id: a.id, video: a.kind === "idea_from_video", what: a.what,
    failed: a.state === "failed" || a.state === "dead", error: a.error,
  }));
  const writing = asks.some((a) => !a.failed);
  const names = { youtube: "YouTube", instagram: "Instagram" } as const;

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-2">
      {(data.looking > 0 || writing) && <AutoRefresh everyMs={5000} />}
      <Link href="/discover" className="w-fit text-sm text-muted hover:text-foreground">← All channels</Link>
      <Deck
        key={channel.id}
        picker={<ChannelPicker channels={channels.map(({ id, name }) => ({ id, name }))} activeId={channel.id} />}
        daily={<DailyIdeasPause channelId={channel.id} daily={channel.ideas_daily} at={channel.ideas_daily_at}
                                paused={channel.ideas_paused} />}
        cards={cards}
        looking={data.looking > 0}
        asks={asks}
        channel={{ id: channel.id, name: channel.name, timezone: channel.timezone }}
        categories={categories}
        formats={formats}
        platforms={data.accounts.map((a) => ({ id: a.platform, label: names[a.platform] }))}
        suggestion={{ date: data.slot.day, time: data.slot.time, min: data.today }}
      />
    </div>
  );
}
