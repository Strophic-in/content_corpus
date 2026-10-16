import Link from "next/link";

import { monthUsage, priceTable, rupees } from "@/lib/costs";
import { requireUser } from "@/lib/session";
import { userSettings } from "@/lib/posts";

import { SignOutButton } from "../sign-out-button";
import { KeyForm, PricesForm, RedditKeysForm, SettingsForm } from "./settings-forms";

export const metadata = { title: "Settings · Content Corpus" };

const KINDS: Record<string, string> = {
  llm: "Writing (OpenAI)", vision: "Reading videos (OpenAI)", image: "Images (OpenAI)", moderation: "Moderation",
  tts: "Voice", gpu: "GPU rendering", pod_storage: "Keeping GPUs parked",
};
const inr = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: n < 10 ? 2 : 0 })}`;

export default async function SettingsPage() {
  const user = await requireUser();
  const [{ settings, keys }, usage, prices] = await Promise.all([
    userSettings(user.id), monthUsage(user.id), priceTable(user.id)]);
  const openai = keys.find((k) => k.name === "openai");
  const reddit = keys.some((k) => k.name === "reddit_client_id");
  const byChannel = new Map<string, { kind: string; amount: number | null; unpriced: number }[]>();
  for (const r of usage.rows)
    byChannel.set(r.channel, [...(byChannel.get(r.channel) ?? []),
                              { kind: r.kind, amount: rupees(r, usage.fx), unpriced: r.unpriced }]);
  const total = usage.rows.reduce((t, r) => t + (rupees(r, usage.fx) ?? 0), 0);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>

      <section className="rounded-xl border border-border bg-surface p-5">
        <h2 className="font-medium">OpenAI API key</h2>
        <p className="mt-1 text-sm text-muted">
          Used by the worker to write scripts. Stored encrypted; it can be replaced but never shown again.
        </p>
        <p className="mt-3 text-sm">
          {openai ? (
            <>Saved · last changed {new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeZone: settings.timezone }).format(openai.updated_at)}</>
          ) : (
            <span className="text-warn">Not set — scripts can’t be written until it is.</span>
          )}
        </p>
        <div className="mt-3"><KeyForm hasKey={Boolean(openai)} /></div>
      </section>

      <SettingsForm settings={settings} />

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5">
        <div className="flex items-baseline gap-2">
          <h2 className="font-medium">This month</h2>
          <span className="ml-auto text-lg font-semibold tabular-nums">{inr(total)}</span>
        </div>
        {byChannel.size === 0 ? <p className="text-sm text-muted">Nothing spent yet this month.</p> : (
          <div className="flex flex-col gap-3 text-sm">
            {[...byChannel].map(([channel, rows]) => (
              <div key={channel}>
                <p className="font-medium">{channel}</p>
                <ul className="mt-1 flex flex-col gap-0.5 text-muted">
                  {rows.map((r) => (
                    <li key={r.kind} className="flex gap-2">
                      <span>{KINDS[r.kind] ?? r.kind}</span>
                      <span className="ml-auto tabular-nums">{r.amount != null ? inr(r.amount) : "—"}</span>
                      {r.unpriced > 0 && <span className="text-xs text-warn">{r.unpriced} unpriced</span>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
        <p className="text-xs text-muted">Each reel&apos;s own breakdown is on its post page.</p>
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5">
        <div>
          <h2 className="font-medium">Model prices</h2>
          <p className="mt-1 text-sm text-muted">What OpenAI charges, so every reel&apos;s cost is exact.</p>
        </div>
        <PricesForm rows={prices.rows} fx={prices.fx}
                    override={settings.usd_inr_override ?? null} />
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5">
        <div>
          <h2 className="font-medium">Reddit API (optional)</h2>
          <p className="mt-1 text-sm text-muted">
            Without keys, communities are read through Reddit&apos;s public feeds — about one request a minute, which is
            enough for daily ideas. Keys add vote counts and NSFW flags, but Reddit now approves every app by hand
            (weeks, often refused) and wants written permission for commercial use.
          </p>
          <p className="mt-2 text-sm">{reddit ? "Saved — the ideas worker uses the API." : "Not set — using public feeds."}</p>
        </div>
        <RedditKeysForm saved={reddit} />
      </section>

      <section className="flex items-center gap-3 rounded-xl border border-border bg-surface p-5">
        <div className="min-w-0 flex-1">
          <h2 className="font-medium">Account</h2>
          <p className="truncate text-sm text-muted">{user.email}</p>
        </div>
        <SignOutButton />
      </section>

      <Link href="/dashboard" className="rounded-xl border border-border bg-surface p-5 transition hover:border-accent">
        <h2 className="font-medium">System status →</h2>
        <p className="mt-1 text-sm text-muted">Workers, storage used against the 9 GB cap, and posts by status.</p>
      </Link>
    </div>
  );
}
