import "server-only";

import { asUser } from "./db";

export type WorkerRow = {
  id: string;
  lane: "cpu" | "gpu" | "publish";
  version: string;
  state: string;
  last_heartbeat_at: Date;
  online: boolean;
};

export type Dashboard = {
  storage: { usedBytes: number; capBytes: number; fullSince: Date | null };
  workers: WorkerRow[];
  postCounts: Record<string, number>;
};

// A worker is online if it heartbeat within the lease window. There is no stored
// 'offline' state on purpose: a paused GPU pod cannot write one.
const ONLINE_WINDOW_SECONDS = 120;

export async function getDashboard(userId: string): Promise<Dashboard> {
  return asUser(userId, async (db) => {
    await db.query("select api.ensure_settings()");
    const storage = await db.query(
      "select used_bytes::float8 as used, cap_bytes::float8 as cap, full_since from api.storage_status()",
    );
    const workers = await db.query(
      `select id, lane, version, state, last_heartbeat_at,
              last_heartbeat_at > now() - make_interval(secs => $1) as online
         from workers order by lane, id`,
      [ONLINE_WINDOW_SECONDS],
    );
    const counts = await db.query("select status, count(*)::int as n from posts group by status");
    const s = storage.rows[0];
    return {
      storage: { usedBytes: s.used, capBytes: s.cap, fullSince: s.full_since },
      workers: workers.rows,
      postCounts: Object.fromEntries(counts.rows.map((r) => [r.status, r.n])),
    };
  });
}
