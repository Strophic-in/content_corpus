import "./env";

import { Pool, type PoolClient } from "pg";

// The web app connects as `corpus_web`: row-level security scopes it to the signed-in
// user, and column grants keep it off every lifecycle column (posts.status,
// jobs.state, ...). Lifecycle changes go through SECURITY DEFINER functions in the
// `api` schema, so the approval gate lives in the database, not in this process.
const globalForPool = globalThis as unknown as { corpusPool?: Pool };

export const pool =
  globalForPool.corpusPool ??
  new Pool({
    connectionString: process.env.WEB_DATABASE_URL,
    max: 5,
    idleTimeoutMillis: 10_000,
  });

if (process.env.NODE_ENV !== "production") globalForPool.corpusPool = pool;

/**
 * Run `fn` in a transaction with `app.user_id` set, which is what the RLS policies
 * read. `set_config(..., true)` is transaction-local, so it is safe behind
 * PgBouncer's transaction pooling (VibeDB port 6432): the setting cannot leak to
 * another request's queries.
 */
export async function asUser<T>(userId: string, fn: (db: PoolClient) => Promise<T>): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query("begin");
    await client.query("select set_config('app.user_id', $1, true)", [userId]);
    const out = await fn(client);
    await client.query("commit");
    return out;
  } catch (err) {
    await client.query("rollback").catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}
