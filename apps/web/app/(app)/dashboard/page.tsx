import { getDashboard, type WorkerRow } from "@/lib/dashboard";
import { requireUser } from "@/lib/session";

export const metadata = { title: "Dashboard · Content Corpus" };

const GB = 1e9;

const LANES: { lane: WorkerRow["lane"]; label: string; idle: string }[] = [
  { lane: "cpu", label: "Script & assembly worker", idle: "Sleeps until there is work" },
  { lane: "gpu", label: "GPU renderer", idle: "Paused — starts for render batches" },
  { lane: "publish", label: "Publisher", idle: "Sleeps until a post is due" },
];

export default async function DashboardPage() {
  const user = await requireUser();
  const { storage, workers, postCounts } = await getDashboard(user.id);
  const pct = Math.min(100, (storage.usedBytes / storage.capBytes) * 100);
  const totalPosts = Object.values(postCounts).reduce((a, b) => a + b, 0);

  return (
    <div className="flex flex-col gap-6">
      {storage.fullSince && (
        <div role="alert" className="rounded-xl border border-danger bg-danger-surface px-4 py-3 text-sm text-danger">
          <strong className="font-semibold">Storage full.</strong> An upload was refused because it would
          take media storage past the {(storage.capBytes / GB).toFixed(0)} GB limit. Renders and uploads that
          need space will fail until some is freed.
        </div>
      )}

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-muted">
          {totalPosts === 0 ? "No posts yet." : `${totalPosts} post${totalPosts === 1 ? "" : "s"} in the corpus.`}
        </p>
      </div>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-5">
          <h2 className="text-sm font-medium text-muted">Media storage (Cloudflare R2)</h2>
          <p className="mt-2 text-2xl font-semibold tabular-nums">
            {(storage.usedBytes / GB).toFixed(2)} <span className="text-base font-normal text-muted">/ {(storage.capBytes / GB).toFixed(0)} GB</span>
          </p>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-border" aria-hidden>
            <div
              className={`h-full rounded-full ${pct >= 95 ? "bg-danger" : pct >= 80 ? "bg-warn" : "bg-accent"}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-muted">Hard limit — uploads past it are refused, never billed.</p>
        </div>

        <div className="rounded-xl border border-border bg-surface p-5">
          <h2 className="text-sm font-medium text-muted">Workers</h2>
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            {LANES.map(({ lane, label, idle }) => {
              const live = workers.filter((w) => w.lane === lane && w.online);
              return (
                <li key={lane} className="flex flex-wrap items-center gap-x-2">
                  <span className={`h-2 w-2 rounded-full ${live.length ? "bg-ok" : "bg-border"}`} aria-hidden />
                  <span className="font-medium">{label}</span>
                  <span className="w-full pl-4 text-muted sm:ml-auto sm:w-auto sm:pl-0">
                    {live.length ? `online · ${live[0].state}` : idle}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      </section>
    </div>
  );
}
