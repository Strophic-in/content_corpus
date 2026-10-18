import "server-only";

import { asUser } from "./db";

// USD per 1M tokens: [input, cached input, output]. Mirrors DEFAULT_PRICES in
// worker/corpus/costs.py (published list prices); the owner's own prices win.
// OpenAI's replies carry token counts, not prices, so this list is what prices a call.
export const DEFAULT_PRICES: Record<string, [number, number, number]> = {
  "gpt-6-luna": [0.1, 0.01, 0.5], "gpt-5.6-luna": [0.2, 0.02, 1.2],
  "gpt-image-1-mini": [2, 0.2, 8], "gpt-image-2": [5, 1.25, 30],
  "gpt-4o-mini": [0.15, 0.075, 0.6], "gpt-4o": [2.5, 1.25, 10], "gpt-4.1-nano": [0.1, 0.025, 0.4],
  "gpt-4.1-mini": [0.4, 0.1, 1.6], "gpt-4.1": [2, 0.5, 8], "gpt-5-nano": [0.05, 0.005, 0.4],
  "gpt-5-mini": [0.25, 0.025, 2], "gpt-5": [1.25, 0.125, 10],
};

/** A list price applies to that model and its dated snapshots, never to a model that
 *  merely shares a prefix ("gpt-5.6-luna" is not "gpt-5"). */
export function defaultPrice(model: string): [number, number, number] | null {
  return DEFAULT_PRICES[model.replace(/-\d{4}-\d{2}-\d{2}$/, "")] ?? null;
}

export type CostRow = {
  kind: string; provider: string; model: string | null; note: string | null; created_at: Date;
  quantity: Record<string, number | string | boolean>; usd_micros: string | null; inr_paise: string | null;
  fx_usd_inr: string | null;
};

/** ₹ for a row: rupee charges as they are, dollar charges at the rate frozen on the row. */
export function rupees(r: Pick<CostRow, "usd_micros" | "inr_paise" | "fx_usd_inr">, fx: number | null): number | null {
  if (r.inr_paise != null) return Number(r.inr_paise) / 100;
  if (r.usd_micros == null) return null;
  const rate = r.fx_usd_inr != null ? Number(r.fx_usd_inr) : fx;
  return rate ? (Number(r.usd_micros) / 1e6) * rate : null;
}

async function currentFx(db: { query: (q: string, p?: unknown[]) => Promise<{ rows: Record<string, unknown>[] }> }) {
  const o = (await db.query("select usd_inr_override as r from app_settings")).rows[0]?.r;
  if (o) return Number(o);
  const r = (await db.query("select usd_inr from fx_rates order by day desc limit 1")).rows[0]?.usd_inr;
  return r ? Number(r) : null;
}

/** A reel's own charges, plus its share of the idea batch that found it. */
export async function postCosts(userId: string, postId: string) {
  return asUser(userId, async (db) => {
    const rows = (await db.query(
      `select kind, provider, model, note, created_at, quantity, usd_micros::text, inr_paise::text, fx_usd_inr::text
         from costs where post_id = $1 order by created_at`, [postId])).rows as CostRow[];
    const share = (await db.query(
      `select coalesce(sum(c.usd_micros), 0)::text as usd_micros, max(c.fx_usd_inr)::text as fx_usd_inr,
              (select count(*) from ideas x where x.batch_job_id = i.batch_job_id)::int as batch
         from ideas i join costs c on c.job_id = i.batch_job_id
        where i.post_id = $1 group by i.batch_job_id`, [postId])).rows[0] as
      { usd_micros: string; fx_usd_inr: string | null; batch: number } | undefined;
    return { rows, share, fx: await currentFx(db) };
  });
}

/** This month, by channel and kind (plus parked pods, which belong to no channel). */
export async function monthUsage(userId: string) {
  return asUser(userId, async (db) => {
    const rows = (await db.query(
      `select coalesce(ch.name, case when c.kind = 'pod_storage' then 'Parked GPUs' else 'Other' end) as channel,
              c.kind, sum(c.usd_micros)::text as usd_micros, sum(c.inr_paise)::text as inr_paise,
              avg(c.fx_usd_inr)::text as fx_usd_inr, count(*) filter (where c.usd_micros is null and c.inr_paise is null)::int as unpriced
         from costs c left join channels ch on ch.id = c.channel_id
        where c.created_at >= date_trunc('month', now())
        group by 1, 2 order by 1, 2`)).rows as
      { channel: string; kind: string; usd_micros: string | null; inr_paise: string | null; fx_usd_inr: string | null;
        unpriced: number }[];
    return { rows, fx: await currentFx(db) };
  });
}

/** Models worth pricing: the owner's priced ones, the models in use, and any seen unpriced. */
export async function priceTable(userId: string) {
  return asUser(userId, async (db) => {
    const own = (await db.query(
      `select model, input_per_m::float8, cached_input_per_m::float8, output_per_m::float8, per_image::float8
         from prices order by model`)).rows as
      { model: string; input_per_m: number | null; cached_input_per_m: number | null; output_per_m: number | null;
        per_image: number | null }[];
    const seen = (await db.query(
      `select distinct model from costs where provider = 'openai' and model is not null
       union select script_model from app_settings where script_model is not null
       union select vision_model from app_settings where vision_model is not null`)).rows.map((r) => r.model as string);
    const fx = (await db.query("select day::text, usd_inr::float8, source from fx_rates order by day desc limit 1")).rows[0] as
      { day: string; usd_inr: number; source: string } | undefined;
    const models = [...new Set([...own.map((p) => p.model), ...seen])].sort();
    return {
      fx,
      rows: models.map((m) => {
        const p = own.find((x) => x.model === m);
        const d = defaultPrice(m);
        return { model: m, own: p ?? null, defaults: d };
      }),
    };
  });
}

/** One row per post of a channel, for the Library's table: how far it got, what it
 *  cost (₹, by kind, plus its share of the idea batch that found it) and how it did. */
export type OverviewRow = {
  id: string; title: string; topic: string; slot_date: string; publish_time: string | null; status: string;
  format: string; template_id: string | null; look_id: string | null; created_at: Date; updated_at: Date;
  error: string | null; go_ahead: boolean;
  script_version: number | null; script_state: string | null; script_score: string | null; versions: number;
  shots: number; shots_done: number; gpu_seconds: string | null; seconds: string | null; slides: number;
  writing: number; pictures: number; voice: number; gpu: number; idea: number; total: number; unpriced: number;
  live: { platform: "youtube" | "instagram"; url: string | null }[]; scheduled: boolean;
  views: number | null; likes: number | null; comments: number | null;
};

export async function overview(userId: string, channelId: string, limit = 500): Promise<OverviewRow[]> {
  return asUser(userId, async (db) => {
    const fx = await currentFx(db);
    const inr = `case when c.inr_paise is not null then c.inr_paise / 100.0
                      when c.usd_micros is not null then c.usd_micros / 1e6 * coalesce(c.fx_usd_inr, $2) end`;
    const r = await db.query(
      `with ps as (select * from posts where channel_id = $1 order by slot_date desc, created_at desc limit $3),
            spent as (
              select c.post_id,
                     coalesce(sum(${inr}) filter (where c.kind in ('llm','vision','moderation')), 0)::float8 as writing,
                     coalesce(sum(${inr}) filter (where c.kind = 'image'), 0)::float8 as pictures,
                     coalesce(sum(${inr}) filter (where c.kind = 'tts'), 0)::float8 as voice,
                     coalesce(sum(${inr}) filter (where c.kind = 'gpu'), 0)::float8 as gpu,
                     count(*) filter (where c.usd_micros is null and c.inr_paise is null)::int as unpriced
                from costs c where c.post_id in (select id from ps) group by c.post_id),
            idea as (
              select i.post_id,
                     sum(${inr})::float8 / nullif((select count(*) from ideas x where x.batch_job_id = i.batch_job_id), 0) as idea
                from ideas i join costs c on c.job_id = i.batch_job_id
               where i.post_id in (select id from ps) group by i.post_id, i.batch_job_id)
       select p.id, p.topic, p.status, p.format, p.look_id, p.created_at, p.updated_at, p.go_ahead,
              to_char(p.slot_date, 'YYYY-MM-DD') as slot_date,
              to_char(p.publish_at at time zone p.publish_tz, 'HH24:MI') as publish_time,
              p.error->>'message' as error,
              (select f.template_id from formats f where f.id = p.format_id) as template_id,
              coalesce(s.title, p.topic) as title, s.version as script_version, s.state as script_state,
              s.review->>'score' as script_score,
              (select count(*) from scripts x where x.post_id = p.id)::int as versions,
              coalesce(sh.n, 0) as shots, coalesce(sh.done, 0) as shots_done, sh.gpu_seconds::text,
              p.final_duration_s::text as seconds, coalesce(jsonb_array_length(p.slides), 0) as slides,
              coalesce(sp.writing, 0) as writing, coalesce(sp.pictures, 0) as pictures, coalesce(sp.voice, 0) as voice,
              coalesce(sp.gpu, 0) as gpu, coalesce(ia.idea, 0) as idea,
              coalesce(sp.writing + sp.pictures + sp.voice + sp.gpu, 0) + coalesce(ia.idea, 0) as total,
              coalesce(sp.unpriced, 0) as unpriced,
              coalesce((select jsonb_agg(jsonb_build_object('platform', a.platform, 'url', a.remote_url) order by a.platform)
                          from publish_attempts a where a.post_id = p.id and a.state = 'live'), '[]') as live,
              exists (select 1 from publish_attempts a where a.post_id = p.id and a.state = 'scheduled') as scheduled,
              st.views, st.likes, st.comments
         from ps p
         left join lateral (select x.title, x.version, x.state, x.review from scripts x where x.post_id = p.id
                             order by (x.id = p.approved_script_id) desc, x.version desc limit 1) s on true
         left join lateral (select count(*)::int as n, count(*) filter (where x.state = 'uploaded')::int as done,
                                   sum(x.gpu_seconds) as gpu_seconds
                              from shots x where x.script_id = p.approved_script_id) sh on true
         left join spent sp on sp.post_id = p.id
         left join (select post_id, sum(idea) as idea from idea group by post_id) ia on ia.post_id = p.id
         left join lateral (select sum(x.views)::int as views, sum(x.likes)::int as likes, sum(x.comments)::int as comments
                              from post_stats x where x.post_id = p.id) st on true
        order by p.slot_date desc, p.created_at desc`,
      [channelId, fx, limit],
    );
    return r.rows;
  });
}
