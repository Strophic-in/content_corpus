import "server-only";

import "./env";

/**
 * Nudge the sleeping cpu worker after enqueueing work. The worker sleeps between
 * jobs rather than polling; without this, a click could wait up to its idle
 * interval. Best effort: if the worker is unreachable the job simply
 * waits for its next scheduled check, and the UI shows it as queued.
 */
export async function wakeWorker(): Promise<void> {
  // Comma-separated: one wake URL per worker process (cpu, gpu and publish lanes).
  const urls = (process.env.CORPUS_WAKE_URL ?? "").split(",").map((u) => u.trim()).filter(Boolean);
  const token = process.env.CORPUS_WAKE_TOKEN;
  if (!urls.length || !token) return;
  await Promise.all(
    urls.map((url) =>
      fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(2000),
      }).catch(() => {
        // Unreachable worker: the job stays queued; nothing to surface here.
      }),
    ),
  );
}
