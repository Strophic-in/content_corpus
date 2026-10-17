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
