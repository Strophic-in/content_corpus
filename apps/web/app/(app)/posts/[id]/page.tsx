import Link from "next/link";
import { notFound } from "next/navigation";

import { workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import {
  postDetail, type AssetRow, type PostRow, type ResearchInfo, type ScriptRow, type ShotRow, type StatRow,
} from "@/lib/posts";
import { postCosts, rupees } from "@/lib/costs";
import { PLATFORM_NAMES, publishInfo, type PublishTarget } from "@/lib/publish";
import { signedUrl } from "@/lib/r2";
import { requireUser } from "@/lib/session";
import { IN_FLIGHT, statusBadge } from "@/lib/status";
import { lookName } from "@/lib/looks";
import { styleName } from "@/lib/styles";
import { voiceLabel } from "@/lib/voices";
import { pipeline } from "@/lib/pipeline";
import { template } from "@/lib/templates";

import { PostForm } from "../post-form";
import {
  AssetRightsButton, AutoRefresh, CancelPublishButton, DeletePostButton, GenerateButton, PublishForm, RenderButton,
  RepackageButton,
  ReviewActions,
} from "./post-actions";
import { NextStep } from "./next-step";
import { Tracker } from "./tracker";
import { DeleteUploadButton, UploadFootage } from "./upload";

export const metadata = { title: "Post · Content Corpus" };

const EDITABLE = new Set(["draft", "awaiting_approval", "failed"]);
// A finished reel: playable, and postable.
const FINISHED = new Set(["ready", "scheduled", "published", "needs_review"]);
// Footage can be added while the script can still be (re)written.
const UPLOADABLE = new Set(["draft", "awaiting_approval", "approved", "failed"]);

function fmt(d: Date) {
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(d);
}

export default async function PostPage({ params }: { params: Promise<{ id: string }> }) {
  const user = await requireUser();
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const detail = await postDetail(user.id, id);
  if (!detail) notFound();
  const { post, scripts, shots, events, assets, stats, research } = detail;
  const formats = post.channel_id
    ? await asUser(user.id, async (db) => (await db.query(
        "select id, name, is_default from formats where channel_id = $1 order by is_default desc, name",
        [post.channel_id])).rows as { id: string; name: string; is_default: boolean }[])
    : (await workspace(user.id)).formats;
  const liveOn = (await asUser(user.id, async (db) => (await db.query(
    "select platform from publish_attempts where post_id = $1 and state = 'live' order by platform", [post.id])).rows))
    .map((r) => (r.platform === "youtube" ? "YouTube" : "Instagram"));
  const live = scripts.find((s) => ["awaiting_approval", "approved", "draft"].includes(s.state));
  const older = scripts.filter((s) => s !== live);
  const badge = statusBadge(post.status);
  const t = template(post.template_id);
  const slides = post.format === "carousel" || post.format === "image";
  // After a failed final join the paid-for shots are all stored: the way forward is
  // Retry assembly (in the render panel), not a new script that would leave them behind.
  const canGenerate = ["draft", "awaiting_approval", "failed"].includes(post.status) &&
    post.error?.stage !== "assemble";

  return (
    <div className="flex flex-col gap-6">
      {(IN_FLIGHT.has(post.status) || post.status === "rendered" ||
        (post.status === "approved" && !slides && (shots.length === 0 ||
          (post.audio_source === "kokoro" && shots.some((s) => !s.voiced)))) ||
        assets.some((a) => a.state === "pending") ||
        // just finished: its caption and cover are on the way
        post.packaging)
        && <AutoRefresh everyMs={4000} />}
      <header className="flex flex-col gap-2">
        <Link href="/library" className="w-fit text-sm text-muted hover:text-foreground">← Library</Link>
        <div className="flex flex-wrap items-start gap-3">
          <h1 className="min-w-0 flex-1 text-2xl leading-tight font-semibold tracking-tight sm:text-3xl">{post.topic}</h1>
          <span className={`shrink-0 rounded-full px-3 py-1 text-sm font-medium ${badge.className}`}>{badge.label}</span>
        </div>
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
          <span>{new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })
            .format(new Date(`${post.slot_date}T00:00:00Z`))}{post.publish_time ? ` · ${post.publish_time}` : ""}</span>
          {post.template_id && <span>{t.display_name}</span>}
          {lookName(post.look_id) && <span title={post.look_why ?? undefined}>Look: {lookName(post.look_id)}</span>}
          {voiceLabel(post.voice_id) &&
            <span title={[post.voice_why, post.voice_style].filter(Boolean).join(" — ") || undefined}>
              Voice: {voiceLabel(post.voice_id)}</span>}
          {styleName("caption", post.caption_preset) && <span>Captions: {styleName("caption", post.caption_preset)}</span>}
          {styleName("thumb", (post.package as { thumb_style?: string } | null)?.thumb_style) &&
            <span>Cover: {styleName("thumb", (post.package as { thumb_style?: string } | null)?.thumb_style)}</span>}
          {post.final_duration_s && <span>{Math.round(Number(post.final_duration_s))} s</span>}
        </p>
      </header>

      {post.status === "failed" && post.error?.message && (
        <div role="alert" className="rounded-xl border border-danger bg-danger-surface px-4 py-3 text-sm text-danger">
          {post.error.message}
          {post.error.stage === "config" && (
            <> — <Link href="/settings" className="font-medium underline">open Settings</Link></>
          )}
        </div>
      )}

      <section className="grid gap-5 md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)] lg:grid-cols-[minmax(0,19rem)_minmax(0,1fr)]">
        <Preview post={post} />
        <div className="flex min-w-0 flex-col gap-4">
          <NextStep postId={post.id} status={post.status} autopilot={post.autopilot || post.go_ahead}
                    scriptId={live?.state === "awaiting_approval" ? live.id : null} publishTime={post.publish_time}
                    failedAtAssembly={post.error?.stage === "assemble"} />
          <div className="rounded-2xl border border-border bg-surface p-4">
            <h2 className="mb-3 text-sm font-semibold">Progress</h2>
            <Tracker steps={pipeline({
              status: post.status, research_state: post.research_state, slides,
              narrated: post.audio_source === "kokoro",
              shots: { total: shots.length, uploaded: shots.filter((x) => x.rendered).length,
                       voiced: shots.filter((x) => x.voiced).length },
              packaged: Boolean(post.package), go_ahead: post.go_ahead, error_stage: post.error?.stage ?? null,
              live_on: liveOn, publish_time: post.publish_time,
            })} />
          </div>
          {canGenerate && live && (
            <div className="flex items-center gap-3 text-sm text-muted">
              Not right? <GenerateButton postId={post.id} regenerate subtle />
            </div>
          )}
        </div>
      </section>

      {live && (slides ? <SlidesCard script={live} /> : <ScriptCard script={live} audio={post.audio_source} />)}

      {live?.state === "awaiting_approval" && <ReviewActions scriptId={live.id} />}

      {post.research_state && <SourcesPanel state={post.research_state} research={research} />}

      {(assets.length > 0 || UPLOADABLE.has(post.status)) &&
        <FootagePanel postId={post.id} assets={assets} uploads={UPLOADABLE.has(post.status)} />}

      {post.approved_script_id && (slides ? <SlidesPanel post={post} /> : <RenderPanel post={post} shots={shots} />)}

      {post.final_key && FINISHED.has(post.status) && <PackagePanel post={post} />}

      {post.final_key && FINISHED.has(post.status) && <PublishPanel post={post} userId={user.id} />}

      {stats.length > 0 && <StatsPanel stats={stats} />}

      {EDITABLE.has(post.status) && (
        <details className="rounded-xl border border-border bg-surface p-5">
          <summary className="cursor-pointer text-sm font-medium">Edit post</summary>
          <div className="mt-4">
            <PostForm postId={post.id} defaults={post} formats={formats} />
          </div>
          <div className="mt-6 border-t border-border pt-4">
            <DeletePostButton postId={post.id} />
          </div>
        </details>
      )}

      {older.length > 0 && (
        <details className="rounded-xl border border-border bg-surface p-5">
          <summary className="cursor-pointer text-sm font-medium">Earlier versions ({older.length})</summary>
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            {older.map((s) => (
              <li key={s.id}>
                <span className="font-medium">v{s.version}</span> · {s.state} · {s.title}
                {s.rejection_note && <span className="text-muted"> — “{s.rejection_note}”</span>}
              </li>
            ))}
          </ul>
        </details>
      )}

      <CostPanel postId={post.id} userId={user.id} />

      {events.length > 0 && (
        <section className="text-sm">
          <h2 className="font-medium">Activity</h2>
          <ul className="mt-2 flex flex-col gap-1 text-muted">
            {events.map((e) => (
              <li key={e.id}>
                <span className="tabular-nums">{fmt(e.at)}</span> · {e.reason ?? e.to_state}
                {e.actor.startsWith("user:") ? " · you" : e.actor.startsWith("system:auto") ? " · auto-approve" : ""}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function SourcesPanel({ state, research }: { state: "pending" | "ready" | "none"; research: ResearchInfo }) {
  const articles = research?.articles ?? [];
  return (
    <section className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-5 text-sm">
      <h2 className="font-medium">Sources</h2>
      {state === "pending" ? <p className="text-muted">Reading the story&apos;s sources in full — the script waits for them.</p>
        : articles.length === 0 ? <p className="text-muted">None could be read; the script works from the idea&apos;s summary.</p>
        : (
          <ul className="flex flex-col gap-1">
            {articles.map((a) => (
              <li key={a.url} className="min-w-0 truncate">
                <a href={a.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">{a.site}</a>
                <span className="text-muted"> — {a.title || a.url}{a.from_idea ? "" : " · another report"}</span>
              </li>
            ))}
          </ul>
        )}
    </section>
  );
}

function StatsPanel({ stats }: { stats: StatRow[] }) {
  const n = (v: number | null) => (v === null ? "—" : Number(v).toLocaleString("en-IN"));
  return (
    <section className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-5 text-sm">
      <h2 className="font-medium">How it&apos;s doing</h2>
      {stats.map((s) => (
        <p key={s.platform}>
          <span className="font-medium">{s.platform === "youtube" ? "YouTube" : "Instagram"}</span>
          <span className="text-muted"> · {n(s.views)} views · {n(s.likes)} likes · {n(s.comments)} comments
            · {fmt(new Date(s.fetched_at))}</span>
        </p>
      ))}
      <p className="text-xs text-muted">Read a few times a day for a month after posting; the idea agent sees them.</p>
    </section>
  );
}

function FootagePanel({ postId, assets, uploads }: { postId: string; assets: AssetRow[]; uploads: boolean }) {
  const twinOf = (a: AssetRow) => assets.find((x) => x.id === a.made_from);
  const status = (a: AssetRow) => a.state === "uploading" ? "uploading…"
    : a.state === "pending"
      ? (a.made_from ? "being drawn…" : a.origin === "upload" ? "checking and watching it…" : "fetching and watching it…")
    : a.state === "failed" ? `couldn't be ${a.made_from ? "drawn" : "fetched"}${a.error ? ` — ${a.error}` : ""}`
    : a.rights === "needs_review" ? "only informs the script — you chose an AI version, so it is never shown"
    : `${a.kind === "video" ? `${Number(a.seconds ?? 0).toFixed(0)} s, ` : ""}${a.w}×${a.h}`;
  return (
    <section id="publish" className="flex scroll-mt-6 flex-col gap-3 rounded-xl border border-border bg-surface p-5 text-sm">
      <div>
        <h2 className="font-medium">Footage</h2>
        <p className="text-muted">The idea&apos;s own picture or video, as you chose — shown with credit, or an AI version
          made from it — and anything you upload. The script waits until it is ready.</p>
      </div>
      <ul className="flex flex-col divide-y divide-border">
        {assets.map((a) => (
          <li key={a.id} className="flex items-start gap-3 py-2">
            {a.has_file && (a.kind === "image"
              // eslint-disable-next-line @next/next/no-img-element -- a private, signed media link
              ? <img src={`/media/asset/${a.id}`} alt="" className="h-24 w-16 shrink-0 rounded-md bg-background object-cover" />
              : <video src={`/media/asset/${a.id}`} muted playsInline preload="metadata" controls
                       className="h-24 w-16 shrink-0 rounded-md bg-black object-cover" />)}
            <span className="min-w-0 flex-1">
              <span className={`font-medium ${a.rights === "rejected" ? "text-muted line-through" : ""}`}>
                #{a.n} · {a.made_from ? `AI version of #${twinOf(a)?.n ?? "?"}` : a.kind === "video" ? "Video" : "Picture"}
                {" · "}{a.origin === "upload" ? `your upload${a.file_name ? ` (${a.file_name})` : ""}` : a.credit || a.origin}
              </span>
              <span className="block text-xs text-muted">{status(a)}</span>
              {a.summary && <span className="block text-xs text-muted">{a.summary}</span>}
            </span>
            {a.origin === "upload" ? (a.state !== "uploading" && <DeleteUploadButton assetId={a.id} />)
              : a.state !== "pending" && <AssetRightsButton assetId={a.id} allowed={a.rights === "approved"} />}
          </li>
        ))}
      </ul>
      {uploads && <UploadFootage postId={postId} />}
    </section>
  );
}

async function RenderPanel({ post, shots }: { post: PostRow; shots: ShotRow[] }) {
  const narrated = post.audio_source === "kokoro";
  const gpuShots = shots.filter((s) => s.source === "generate").length;
  const voiced = shots.filter((s) => s.voiced).length;
  const rendered = shots.filter((s) => s.rendered).length;
  const seconds = shots.reduce((t, s) => t + (s.num_frames - 1) / s.fps, 0);
  const box = "flex flex-col gap-2 rounded-xl border border-border bg-surface p-5 text-sm";

  if (FINISHED.has(post.status)) {
    const [play, download] = post.final_key
      ? await Promise.all([signedUrl(post.final_key), signedUrl(post.final_key, 3600, `${post.slot_date}.mp4`)])
      : [null, null];
    return (
      <section className={box}>
        <h2 className="font-medium">Your reel{post.final_duration_s ? ` · ${Number(post.final_duration_s).toFixed(1)} s` : ""}</h2>
        {play ? (
          <>
            <video src={play} controls playsInline className="aspect-[9/16] w-full max-w-xs rounded-lg bg-black" />
            {download && <a href={download} className="w-fit text-accent underline-offset-4 hover:underline">Download MP4</a>}
            {post.music && (
              <p className="text-xs text-muted">
                Music: <a href={post.music.page} target="_blank" rel="noreferrer" className="underline">“{post.music.name}”</a>{" "}
                by {post.music.author} · {post.music.mood} · CC0
              </p>
            )}
          </>
        ) : (
          <p className="text-muted">Stored in R2 — add the R2 keys to the web app&apos;s environment to play it here.</p>
        )}
      </section>
    );
  }
  if (post.status === "rendered" || post.status === "post_processing")
    return <section className={box}><h2 className="font-medium">Assembling the reel…</h2>
      <p className="text-muted">Stitching {shots.length} shots, mixing the narration and adding captions.</p></section>;
  if (post.status === "rendering")
    return (
      <section className={box}>
        <h2 className="font-medium">
          {gpuShots === shots.length ? `Rendering on the GPU · shot ${Math.min(rendered + 1, shots.length)} of ${shots.length}`
            : `Making the shots · ${rendered} of ${shots.length} done`}
        </h2>
        <div className="h-2 overflow-hidden rounded-full bg-border" aria-hidden>
          <div className="h-full rounded-full bg-accent" style={{ width: `${(rendered / shots.length) * 100}%` }} />
        </div>
        <p className="text-muted">
          {gpuShots === 0 ? "Cutting the footage on the server — no GPU needed."
            : gpuShots < shots.length ? `${gpuShots} on the GPU (about a minute each; it is paused the moment they are done), `
              + "the footage shots on the server meanwhile."
            : "Each shot takes about a minute; the GPU is paused the moment the last one is done."}
        </p>
      </section>
    );
  if (post.status === "queued_for_render" && gpuShots === 0)
    return <section className={box}><h2 className="font-medium">Preparing the footage…</h2>
      <p className="text-muted">Cutting the clips and pictures on the server — no GPU needed.</p></section>;
  if (post.status === "queued_for_render")
    return (
      <section className={box}>
        <h2 className="font-medium">{post.error?.stage === "no_gpu" ? "Waiting for a free GPU" : "Starting a GPU…"}</h2>
        <p className="text-muted">
          {post.error?.stage === "no_gpu"
            ? "Every GPU is busy or out of space right now. It retries every 10 minutes on its own — nothing is charged while it waits."
            : "Finding the cheapest available GPU (one with the models already downloaded, if possible)."}
        </p>
      </section>
    );
  if (post.status === "approved" || post.status === "failed") {
    if (!shots.length) return <section className={box}><p className="text-muted">Planning shots…</p></section>;
    if (narrated && voiced < shots.length)
      return <section className={box}><h2 className="font-medium">Recording narration · {voiced} of {shots.length}</h2>
        <p className="text-muted">Each shot&apos;s length is set by its narration line.</p></section>;
    if (post.status === "failed" && rendered === shots.length)
      return (
        <section className={box}>
          <h2 className="font-medium">All {shots.length} shots are rendered — only the final join failed</h2>
          <p className="text-muted">They are stored safely. Retrying only re-joins them on the server: no GPU, no cost.</p>
          <RenderButton postId={post.id} retry label="Retry assembly (no GPU)" />
        </section>
      );
    return (
      <section className={box}>
        <h2 className="font-medium">Ready to render</h2>
        <p className="text-muted">
          {shots.length} shot{shots.length === 1 ? "" : "s"}, {seconds.toFixed(1)} s{narrated ? ", narration recorded" : ""}.
          {gpuShots === 0 ? " All footage: a minute or two on the server, no GPU."
            : gpuShots < shots.length ? ` ${gpuShots} generated on the GPU (a few minutes), the rest from footage.`
            : " Usually 5–10 minutes on the GPU."}
        </p>
        <RenderButton postId={post.id} retry={post.status === "failed"} />
      </section>
    );
  }
  return null;
}

/** What it goes out with: the cover, title, caption (with its sources), hashtags and
 *  first comment — written by the worker once the reel is finished. */
function PackagePanel({ post }: { post: PostRow }) {
  const p = post.package;
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-medium">Caption &amp; cover</h2>
        <span className="text-xs text-muted">{p ? "used when it's posted" : "being written…"}</span>
        <span className="ml-auto"><RepackageButton postId={post.id} /></span>
      </div>
      {p && (
        <div className="grid gap-5 sm:grid-cols-[11rem_minmax(0,1fr)]">
          {/* eslint-disable-next-line @next/next/no-img-element -- a signed, redirecting media URL */}
          <img src={`/media/post/${post.id}?cover=1&v=${encodeURIComponent(p.made_at)}`} alt="The cover"
               className="aspect-[9/16] w-44 rounded-lg border border-border object-cover" />
          <div className="flex min-w-0 flex-col gap-3 text-sm">
            <div><p className="text-xs text-muted">Title</p><p className="font-semibold">{p.title}</p></div>
            <div>
              <p className="text-xs text-muted">Caption</p>
              <p className="font-medium">{p.hook_line}</p>
              <p className="whitespace-pre-line text-muted">{p.caption}</p>
            </div>
            {p.sources.length > 0 && (
              <div>
                <p className="text-xs text-muted">Sources (in the caption; links in YouTube&apos;s, and Instagram&apos;s first comment)</p>
                <ul className="flex flex-col gap-0.5">
                  {p.sources.map((s) => (
                    <li key={s.url} className="truncate"><a href={s.url} target="_blank" rel="noreferrer"
                      className="text-accent hover:underline">{s.site}</a> <span className="text-muted">— {s.title}</span></li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-accent">{p.hashtags.join(" ")}</p>
            <div><p className="text-xs text-muted">First comment</p><p>{p.first_comment}</p></div>
          </div>
        </div>
      )}
    </section>
  );
}

async function PublishPanel({ post, userId }: { post: PostRow; userId: string }) {
  const info = await publishInfo(userId, post.id, post.channel_id);
  const pending = (t: PublishTarget) => t.job?.state === "queued" || t.job?.state === "claimed";
  const busy = info.targets.some((t) => t.job?.state === "claimed" || (t.job?.state === "queued" && t.job.due));
  const open = info.targets.filter((t) => t.account?.status === "connected" && t.attempt?.state !== "live" && !pending(t));
  const when = (d: Date) => new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: info.tz })
    .format(new Date(d));
  const channelPage = post.channel_id ? `/channels/${post.channel_id}` : "/channels";

  function state(t: PublishTarget) {
    const name = PLATFORM_NAMES[t.platform];
    if (t.attempt?.state === "live")
      return (
        <span>
          <span className="text-ok">Posted</span>
          {t.attempt.privacy && t.attempt.privacy !== "public" && <span className="text-muted"> · {t.attempt.privacy}</span>}
          {t.attempt.remote_url && (
            <> · <a href={t.attempt.remote_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              View on {name} ↗</a></>
          )}
        </span>
      );
    if (t.job?.state === "claimed") return <span className="text-accent">Posting now…</span>;
    if (t.job?.state === "queued")
      return t.job.due ? (
        <span className="text-accent">{t.job.error ? "Retrying shortly…" : "Starting…"}</span>
      ) : (
        <span className="flex flex-wrap items-center gap-2">
          <span>Scheduled for {when(t.job.not_before)}{t.job.privacy ? ` · ${t.job.privacy}` : ""}</span>
          <CancelPublishButton postId={post.id} platform={t.platform} />
        </span>
      );
    if (!t.account) return <span className="text-muted">Not connected · <Link href={channelPage} className="text-accent hover:underline">connect</Link></span>;
    if (t.account.status !== "connected")
      return <span className="text-warn">Access expired · <Link href={channelPage} className="hover:underline">reconnect</Link></span>;
    if (t.job?.state === "needs_review")
      return <span className="text-warn">Not sure it went out — check {name}. Posting again checks first, so it won&apos;t post twice.</span>;
    if (t.job && ["failed", "dead"].includes(t.job.state) && t.job.error?.message)
      return <span className="text-danger">{t.job.error.message}</span>;
    if (t.job?.state === "cancelled") return <span className="text-muted">Cancelled</span>;
    return <span className="text-muted">Not posted</span>;
  }

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5 text-sm">
      {busy && <AutoRefresh everyMs={4000} />}
      <h2 className="font-medium">Post it</h2>
      <ul className="flex flex-col divide-y divide-border">
        {info.targets.map((t) => (
          <li key={t.platform} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
            <span className="w-24 shrink-0 font-medium">{PLATFORM_NAMES[t.platform]}</span>
            {t.account?.handle && <span className="text-muted">{t.account.handle}</span>}
            <span className="min-w-0 basis-full sm:basis-auto">{state(t)}</span>
          </li>
        ))}
      </ul>
      {open.length > 0 && (
        <PublishForm postId={post.id} platforms={open.map((t) => t.platform)} youtubePrivacy={info.youtubePrivacy}
                     plannedLocal={info.plannedLocal} tz={info.tz} />
      )}
    </section>
  );
}

const COST_LABEL: Record<string, string> = {
  llm: "Writing", vision: "Reading the video", moderation: "Moderation", image: "Image", gpu: "GPU", tts: "Voice",
};

async function CostPanel({ postId, userId }: { postId: string; userId: string }) {
  const { rows, share, fx } = await postCosts(userId, postId);
  const shareInr = share && share.batch ? (rupees({ ...share, inr_paise: null }, fx) ?? 0) / share.batch : 0;
  if (!rows.length && !shareInr) return null;
  const inr = (n: number) => `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const total = rows.reduce((t, r) => t + (rupees(r, fx) ?? 0), 0) + shareInr;
  const unpriced = rows.filter((r) => rupees(r, fx) == null).length;
  return (
    <details className="rounded-xl border border-border bg-surface p-5 text-sm">
      <summary className="flex cursor-pointer items-baseline gap-2">
        <span className="font-medium">Cost</span>
        <span className="ml-auto font-semibold tabular-nums">{inr(total)}</span>
      </summary>
      <ul className="mt-3 flex flex-col gap-1.5">
        {shareInr > 0 && (
          <li className="flex gap-2 text-muted">
            <span>Finding the idea <span className="text-xs">(share of a batch of {share!.batch})</span></span>
            <span className="ml-auto tabular-nums">{inr(shareInr)}</span>
          </li>
        )}
        {rows.map((r, i) => {
          const q = r.quantity;
          const what = r.kind === "gpu"
            ? `${r.model ?? "GPU"} · pod ${q.pod} · ${(Number(q.seconds) / 60).toFixed(1)} min` +
              (q.rate_paise_h ? ` at ₹${(Number(q.rate_paise_h) / 100).toFixed(0)}/h` : "")
            : `${r.model} · ${Number(q.input ?? 0).toLocaleString("en-IN")} in / ${Number(q.output ?? 0).toLocaleString("en-IN")} out`;
          const amount = rupees(r, fx);
          return (
            <li key={i} className="flex flex-wrap gap-x-2 text-muted">
              <span className="text-foreground">{COST_LABEL[r.kind] ?? r.kind}{r.note ? ` · ${r.note}` : ""}</span>
              <span className="text-xs">{what}</span>
              <span className="ml-auto tabular-nums">
                {amount != null ? inr(amount) : "price unknown"}
                {r.usd_micros != null && <span className="ml-1 text-xs">(${(Number(r.usd_micros) / 1e6).toFixed(4)})</span>}
              </span>
            </li>
          );
        })}
      </ul>
      {unpriced > 0 && (
        <p className="mt-2 text-xs text-warn">
          {unpriced} charge{unpriced === 1 ? " has" : "s have"} no price yet — <Link href="/settings" className="underline">set the model&apos;s price</Link>.
        </p>
      )}
    </details>
  );
}

function clock(t = 0) {
  return `${Math.floor(t / 60)}:${(t % 60).toFixed(0).padStart(2, "0")}`;
}

function sourceLabel(s: ScriptRow["shot_plan"][number]) {
  switch (s.source) {
    case "clip": return `🎞 clip from footage #${s.asset}, ${clock(s.start)}–${clock(s.end)}${s.keep_audio ? ", its own sound" : ""}`;
    case "image": return `🖼 picture #${s.asset}`;
    case "stock": return `📦 stock video: “${s.stock_query}”`;
    case "chart": return `📊 ${s.chart?.kind ?? "bar"} chart: ${s.chart?.title ?? ""}`;
    case "plain": return "▭ plain background";
    default: return "✨ generated";
  }
}

const AUDIO_LABEL = { kokoro: "narrated voice-over", ltx_native: "characters speak", none: "no voice" } as const;

function SlidesCard({ script }: { script: ScriptRow }) {
  const visual = (v: NonNullable<ScriptRow["slides"]>[number]["visual"]) =>
    v.source === "asset" ? `🖼 picture #${v.asset}` : v.source === "ai_image" ? `✨ AI picture: ${v.prompt}`
      : v.source === "chart" ? `📊 ${v.chart.kind} chart: ${v.chart.title}` : "▭ background colour";
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-lg font-semibold">{script.title}</h2>
        <span className="text-xs text-muted">v{script.version} · {script.model} · {script.slides?.length ?? 0} slides</span>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-[8rem_1fr]">
        <dt className="text-muted">Cover line</dt><dd>{script.hook}</dd>
        <dt className="text-muted">Caption</dt><dd className="whitespace-pre-line">{script.description}</dd>
        <dt className="text-muted">Hashtags</dt><dd>{script.hashtags.join(" ")}</dd>
      </dl>
      <ol className="flex flex-col gap-3">
        {(script.slides ?? []).map((s, i) => (
          <li key={i} className="rounded-lg border border-border p-3 text-sm">
            <div className="text-xs font-medium text-muted">Slide {i + 1}{s.role ? ` · ${s.role.replaceAll("_", " ")}` : ""} · {visual(s.visual)}</div>
            {s.heading && <p className="mt-1 font-semibold">{s.heading}</p>}
            {s.body && <p className="mt-1 text-muted">{s.body}</p>}
          </li>
        ))}
      </ol>
      {script.review && (
        <div className="rounded-lg bg-background p-3 text-sm">
          <div className="font-medium">AI self-review · {script.review.score}/10 <span className="font-normal text-muted">(advice only)</span></div>
          {script.review.risks.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-muted">{script.review.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
          )}
        </div>
      )}
    </section>
  );
}

async function SlidesPanel({ post }: { post: PostRow }) {
  const box = "flex flex-col gap-3 rounded-xl border border-border bg-surface p-5 text-sm";
  if (FINISHED.has(post.status) && post.slides?.length) {
    const urls = await Promise.all(post.slides.map((s) => signedUrl(s.key)));
    const play = post.final_key ? await signedUrl(post.final_key) : null;
    return (
      <section className={box}>
        <h2 className="font-medium">{post.slides.length === 1 ? "Your picture post" : `Your carousel · ${post.slides.length} slides`}</h2>
        <div className="-mx-1 flex snap-x gap-2 overflow-x-auto px-1 pb-1">
          {urls.map((u, i) => u && (
            // eslint-disable-next-line @next/next/no-img-element -- a private, signed link
            <img key={i} src={u} alt={`Slide ${i + 1}`} className="h-72 w-auto shrink-0 snap-start rounded-lg bg-black" />
          ))}
        </div>
        <p className="text-xs text-muted">Instagram gets these as {post.slides.length === 1 ? "a picture post" : "a carousel"};
          YouTube gets the slideshow below.</p>
        {play && <video src={play} controls playsInline className="aspect-[9/16] w-full max-w-[220px] rounded-lg bg-black" />}
        {post.music && (
          <p className="text-xs text-muted">
            Music: <a href={post.music.page} target="_blank" rel="noreferrer" className="underline">“{post.music.name}”</a>{" "}
            by {post.music.author} · {post.music.mood} · CC0
          </p>
        )}
      </section>
    );
  }
  if (post.status === "queued_for_render" || post.status === "rendering")
    return <section className={box}><h2 className="font-medium">Drawing the slides…</h2>
      <p className="text-muted">Then the slideshow for YouTube — a minute or two on the server, no GPU.</p></section>;
  if (post.status === "approved" || post.status === "failed")
    return (
      <section className={box}>
        <h2 className="font-medium">Ready to make the slides</h2>
        <p className="text-muted">The slides for Instagram and a slideshow Short for YouTube — on the server, no GPU
          (an AI picture, if the script asks for one, costs what your image model charges — about ₹3.5 with gpt-image-2).</p>
        <RenderButton postId={post.id} retry={post.status === "failed"} label={post.status === "failed" ? "Try again" : "Make the slides"} />
      </section>
    );
  return null;
}

function ScriptCard({ script, audio }: { script: ScriptRow; audio: PostRow["audio_source"] }) {
  const total = script.shot_plan.reduce((t, s) => t + s.seconds, 0);
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-lg font-semibold">{script.title}</h2>
        <span className="text-xs text-muted">
          v{script.version} · {script.model} · {total}s · {AUDIO_LABEL[audio]}
        </span>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-[8rem_1fr]">
        <dt className="text-muted">Hook</dt><dd>{script.hook}</dd>
        <dt className="text-muted">Description</dt><dd className="whitespace-pre-line">{script.description}</dd>
        <dt className="text-muted">Hashtags</dt><dd>{script.hashtags.join(" ")}</dd>
        <dt className="text-muted">Look</dt><dd>{script.style_prompt}</dd>
      </dl>
      <ol className="flex flex-col gap-3">
        {script.shot_plan.map((s, i) => (
          <li key={i} className="rounded-lg border border-border p-3 text-sm">
            <div className="text-xs font-medium text-muted">Shot {i + 1}{s.role ? ` · ${s.role.replaceAll("_", " ")}` : ""} · {s.seconds}s · {sourceLabel(s)}
              {s.layout === "split" ? " · split screen" : ""}{s.transition ? ` · ${s.transition} in` : ""}</div>
            {(s.label || s.text) && (
              <p className="mt-1 flex flex-wrap items-center gap-2">
                {s.label && <span className="rounded bg-accent/15 px-1.5 py-0.5 text-xs font-semibold text-accent uppercase">{s.label}</span>}
                {s.text && <span className="font-semibold">“{s.text}”</span>}
              </p>
            )}
            {s.narration && <p className="mt-1 font-medium">🎙 “{s.narration}”</p>}
            <p className="mt-1">{s.visual}</p>
            <p className="mt-1 text-muted">🔊 {s.audio}</p>
          </li>
        ))}
      </ol>
      {script.review && (
        <div className="rounded-lg bg-background p-3 text-sm">
          <div className="font-medium">AI self-review · {script.review.score}/10 <span className="font-normal text-muted">(advice only)</span></div>
          {script.review.risks.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-muted">{script.review.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
          )}
          {script.review.notes && <p className="mt-1 text-muted">{script.review.notes}</p>}
        </div>
      )}
    </section>
  );
}


const MAKING: Record<string, string> = {
  draft: "Not started", scripting: "Writing the script…", awaiting_approval: "Script ready for you",
  approved: "Approved", queued_for_render: "Waiting for a GPU…", rendering: "Rendering…", rendered: "Putting it together…",
  post_processing: "Putting it together…", failed: "Stopped", cancelled: "Cancelled",
};

function Preview({ post }: { post: PostRow }) {
  const busy = IN_FLIGHT.has(post.status) || post.status === "rendered";
  if (post.final_key)
    return (
      <video src={`/media/post/${post.id}`} poster={post.package ? `/media/post/${post.id}?cover=1` : undefined}
             controls playsInline preload="metadata"
             className="aspect-[9/16] w-full max-w-xs justify-self-center rounded-2xl border border-border bg-black object-cover md:max-w-none" />
    );
  return (
    <div className={`relative grid aspect-[9/16] w-full max-w-xs place-items-center justify-self-center overflow-hidden rounded-2xl border border-border md:max-w-none ${
      busy ? "skeleton" : "bg-surface"}`}>
      <div className="flex flex-col items-center gap-2 p-6 text-center">
        {busy && <span aria-hidden className="size-3 animate-ping rounded-full bg-accent" />}
        <p className="text-sm font-medium">{MAKING[post.status] ?? "In progress"}</p>
        <p className="text-xs text-muted">The reel appears here when it&apos;s made.</p>
      </div>
    </div>
  );
}

