import Link from "next/link";

import { asUser } from "@/lib/db";
import { requireOwner } from "@/lib/session";

export const metadata = { title: "Health · Content Corpus" };

const LANES: Record<string, string> = {
  cpu: "Scripts, voice, footage, assembly", gpu: "GPU rendering", ideas: "Ideas, sources, fetching", publish: "Posting",
};
const KEYS: [string, string][] = [
  ["openai", "OpenAI"], ["pexels_api_key", "Pexels (stock video)"], ["youtube_api_key", "YouTube API (trending, stats)"],
  ["freesound_api_key", "Freesound (music)"],
];

/** Seconds ago (computed by the database: rendering stays pure) → words. */
function ago(s: number | null): string {
  if (s === null) return "never";
  return s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 172800 ? `${Math.round(s / 3600)} h ago`
    : `${Math.round(s / 86400)} days ago`;
}

const dot = (ok: boolean | null) => (
  <span className={`inline-block size-2.5 shrink-0 rounded-full ${ok === null ? "bg-border" : ok ? "bg-ok" : "bg-danger"}`} />
);

// What the app depends on, at a glance: the workers' heartbeats and queues, the
// checks they run each hour (storage, GPUs, disk, ffmpeg), storage use, keys and
// connected accounts.
export default async function HealthPage() {
  const user = await requireOwner();
  const data = await asUser(user.id, async (db) => {
    const q = async <T,>(sql: string): Promise<T[]> => {
      try {
        return (await db.query(sql)).rows as T[];
      } catch {
        return [];
      }
    };
    return {
      workers: await q<{ lane: string; version: string; state: string; age_s: number }>(
        `select distinct on (lane) lane, version, state,
                extract(epoch from now() - last_heartbeat_at)::int as age_s from workers
          order by lane, last_heartbeat_at desc`),
      queues: await q<{ lane: string; state: string; n: number }>(
        `select lane, state, count(*)::int as n from jobs where state in ('queued','claimed','blocked')
          group by lane, state order by lane, state`),
      failures: await q<{ kind: string; lane: string; age_s: number; message: string | null }>(
        `select kind, lane, extract(epoch from now() - finished_at)::int as age_s, error->>'message' as message from jobs
          where state in ('failed','dead') and finished_at > now() - interval '24 hours'
          order by finished_at desc limit 10`),
      checks: await q<{ name: string; ok: boolean; detail: string; age_s: number }>(
        "select name, ok, detail, extract(epoch from now() - checked_at)::int as age_s from health_checks order by name"),
      storage: await q<{ kind: string; bytes: string }>(
        `select kind, sum(bytes)::text as bytes from storage_objects where state = 'stored' group by kind order by 2 desc`),
      cap: (await q<{ cap_bytes: string; idea_media_cap_bytes: string }>(
        "select cap_bytes::text, idea_media_cap_bytes::text from storage_config limit 1"))[0],
      keys: (await q<{ name: string }>("select name from user_keys")).map((k) => k.name),
      accounts: await q<{ platform: string; handle: string | null; status: string; days_left: number | null;
                          channel: string }>(
        `select a.platform, a.handle, a.status, c.name as channel,
                (extract(epoch from a.token_expires_at - now()) / 86400)::float8 as days_left
           from channel_accounts a join channels c on c.id = a.channel_id order by c.name, a.platform`),
    };
  });
  const used = data.storage.reduce((t, r) => t + Number(r.bytes), 0);
  const cap = Number(data.cap?.cap_bytes ?? 0);
  const box = "flex flex-col gap-2 rounded-xl border border-border bg-surface p-5 text-sm";

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <Link href="/settings" className="text-sm text-muted hover:text-foreground">← Settings</Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Health</h1>
        <p className="text-sm text-muted">What the app depends on. The workers check their side every hour.</p>
      </div>

      <section className={box}>
        <h2 className="font-medium">Workers</h2>
        {Object.entries(LANES).map(([lane, what]) => {
          const w = data.workers.find((x) => x.lane === lane);
          const fresh = w ? w.age_s < 15 * 60 : false;
          const queued = data.queues.filter((x) => x.lane === lane);
          return (
            <div key={lane} className="flex items-start gap-3">
              <span className="mt-1.5">{dot(w ? fresh : false)}</span>
              <span className="min-w-0 flex-1">
                <span className="font-medium">{what}</span>
                <span className="block text-xs text-muted">
                  {w ? `${w.state}, last seen ${ago(w.age_s)} · version ${w.version}` : "never seen"}
                  {queued.length > 0 && ` · ${queued.map((x) => `${x.n} ${x.state}`).join(", ")}`}
                </span>
              </span>
            </div>
          );
        })}
      </section>

      <section className={box}>
        <h2 className="font-medium">Checks</h2>
        {data.checks.length === 0 && <p className="text-muted">The workers haven&apos;t reported yet (they do hourly).</p>}
        {data.checks.map((c) => (
          <div key={c.name} className="flex items-start gap-3">
            <span className="mt-1.5">{dot(c.ok)}</span>
            <span className="min-w-0 flex-1">
              <span className="font-medium">{c.name}</span>
              <span className="block text-xs break-words text-muted">{c.detail} · {ago(c.age_s)}</span>
            </span>
          </div>
        ))}
      </section>

      <section className={box}>
        <h2 className="font-medium">Storage · {(used / 1e9).toFixed(2)} of {(cap / 1e9).toFixed(1)} GB</h2>
        <div className="h-2 overflow-hidden rounded-full bg-border" aria-hidden>
          <div className={`h-full rounded-full ${cap && used / cap > 0.9 ? "bg-danger" : "bg-accent"}`}
               style={{ width: `${cap ? Math.min(100, (used / cap) * 100) : 0}%` }} />
        </div>
        <p className="text-xs text-muted">
          {data.storage.map((r) => `${r.kind} ${(Number(r.bytes) / 1e6).toFixed(0)} MB`).join(" · ") || "Nothing stored."}
        </p>
      </section>

      <section className={box}>
        <h2 className="font-medium">Keys and accounts</h2>
        {KEYS.map(([name, label]) => (
          <div key={name} className="flex items-center gap-3">{dot(data.keys.includes(name) ? true : null)}
            <span className="flex-1">{label}</span>
            <span className="text-xs text-muted">{data.keys.includes(name) ? "set" : "not set"}</span>
          </div>
        ))}
        {data.accounts.map((a) => {
          const days = a.days_left;
          return (
            <div key={`${a.channel}-${a.platform}`} className="flex items-center gap-3">
              {dot(a.status === "connected" && (days === null || days > 3))}
              <span className="flex-1">{a.channel} · {a.platform === "youtube" ? "YouTube" : "Instagram"}
                {a.handle ? ` (${a.handle})` : ""}</span>
              <span className="text-xs text-muted">
                {a.status}{days !== null && a.status === "connected" ? `, token ${days > 0 ? `for ${Math.floor(days)} more days` : "expired"}` : ""}
              </span>
            </div>
          );
        })}
      </section>

      <section className={box}>
        <h2 className="font-medium">Failed in the last 24 hours</h2>
        {data.failures.length === 0 ? <p className="text-muted">Nothing.</p> : data.failures.map((f, i) => (
          <div key={i} className="flex items-start gap-3">
            <span className="mt-1.5">{dot(false)}</span>
            <span className="min-w-0 flex-1">
              <span className="font-medium">{f.kind}</span> <span className="text-xs text-muted">({f.lane}, {ago(f.age_s)})</span>
              {f.message && <span className="block text-xs break-words text-muted">{f.message.slice(0, 300)}</span>}
            </span>
          </div>
        ))}
      </section>
    </div>
  );
}
