import Link from "next/link";

import { monthUsage, priceTable, rupees } from "@/lib/costs";
import { imageModels, textModels } from "@/lib/models";
import { requireUser } from "@/lib/session";
import { userSettings } from "@/lib/posts";

import { SignOutButton } from "../sign-out-button";
import { KeyForm, PricesForm, RedditKeysForm, ServiceKeyForm, SettingsForm } from "./settings-forms";

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
  const youtube = keys.some((k) => k.name === "youtube_api_key");
  const pexels = keys.some((k) => k.name === "pexels_api_key");
  const freesound = keys.some((k) => k.name === "freesound_api_key");
  const byChannel = new Map<string, { kind: string; amount: number | null; unpriced: number }[]>();
  for (const r of usage.rows)
    byChannel.set(r.channel, [...(byChannel.get(r.channel) ?? []),
                              { kind: r.kind, amount: rupees(r, usage.fx), unpriced: r.unpriced }]);
  const total = usage.rows.reduce((t, r) => t + (rupees(r, usage.fx) ?? 0), 0);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        {user.role === "owner" && (
          <span className="flex gap-4 text-sm">
            <Link href="/admin" className="text-accent hover:underline">Members →</Link>
            <Link href="/health" className="text-accent hover:underline">System health →</Link>
          </span>
        )}
      </div>

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

      <SettingsForm settings={{ ...settings, openai_models: textModels(settings.openai_models ?? []),
                                image_models: imageModels(settings.openai_models ?? []) }} />

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
          <h2 className="font-medium">YouTube API key (for trending sources)</h2>
          <p className="mt-1 text-sm text-muted">
            Lets a category follow YouTube&apos;s most-popular chart. Free: in Google Cloud Console (the project you use for
            sign-in), open APIs &amp; Services → Credentials → Create credentials → API key, and restrict it to the
            YouTube Data API v3. It reads public charts only — never your channel — and uses 1 of the 10,000 daily
            quota units per read. Stored encrypted.
          </p>
          <p className="mt-2 text-sm">{youtube ? "Saved." : "Not set — YouTube trending sources wait for it."}</p>
        </div>
        <ServiceKeyForm service="youtube" saved={youtube} placeholder="AIza…" />
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5">
        <div>
          <h2 className="font-medium">Pexels API key (for stock video)</h2>
          <p className="mt-1 text-sm text-muted">
            Lets scripts use free stock video for shots that show a setting or a subject in general — a city at night,
            a hospital corridor — instead of rendering them on the GPU. Free at pexels.com/api (200 searches an hour).
            Every stock clip is credited on screen and in the description. Stored encrypted.
          </p>
          <p className="mt-2 text-sm">{pexels ? "Saved — new scripts may use stock video." : "Not set — no stock video."}</p>
        </div>
        <ServiceKeyForm service="pexels" saved={pexels} placeholder="Your Pexels API key" />
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5">
        <div>
          <h2 className="font-medium">Freesound API key (for background music)</h2>
          <p className="mt-1 text-sm text-muted">
            With it, each script picks a mood (tense, somber, uplifting…) and the reel gets a matching track from
            Freesound — Creative Commons 0 only, so free to use without a licence — quietly under the voice, never one
            of your last 20. Free at freesound.org/apiv2/apply. Stored encrypted.
          </p>
          <p className="mt-2 text-sm">{freesound ? "Saved — reels get background music." : "Not set — no music."}</p>
        </div>
        <ServiceKeyForm service="freesound" saved={freesound} placeholder="Your Freesound API key" />
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5">
        <div>
          <h2 className="font-medium">Reddit API (optional)</h2>
          <p className="mt-1 text-sm text-muted">
            Without keys, communities are read through Reddit&apos;s public feeds — about one request a minute, which is
            enough for daily ideas. Reddit ends those feeds on 13 Nov 2026 and stops taking new API requests on
            31 Oct 2026; its public API closes in March 2027. Follow topics on Bluesky, Mastodon or Lemmy as well.
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
