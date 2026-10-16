import Link from "next/link";
import { notFound } from "next/navigation";

import { workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { postDetail, type PostRow, type ScriptRow, type ShotRow } from "@/lib/posts";
import { postCosts, rupees } from "@/lib/costs";
import { PLATFORM_NAMES, publishInfo, type PublishTarget } from "@/lib/publish";
import { signedUrl } from "@/lib/r2";
import { requireUser } from "@/lib/session";
import { IN_FLIGHT, statusBadge } from "@/lib/status";

import { PostForm } from "../post-form";
import {
  AutoRefresh, CancelPublishButton, DeletePostButton, GenerateButton, PublishForm, RenderButton, ReviewActions,
} from "./post-actions";

export const metadata = { title: "Post · Content Corpus" };

const EDITABLE = new Set(["draft", "awaiting_approval", "failed"]);
// A finished reel: playable, and postable.
const FINISHED = new Set(["ready", "scheduled", "published", "needs_review"]);

function fmt(d: Date) {
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(d);
}

export default async function PostPage({ params }: { params: Promise<{ id: string }> }) {
  const user = await requireUser();
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const detail = await postDetail(user.id, id);
  if (!detail) notFound();
  const { post, scripts, shots, events } = detail;
  const formats = post.channel_id
    ? await asUser(user.id, async (db) => (await db.query(
        "select id, name, is_default from formats where channel_id = $1 order by is_default desc, name",
        [post.channel_id])).rows as { id: string; name: string; is_default: boolean }[])
    : (await workspace(user.id)).formats;
  const live = scripts.find((s) => ["awaiting_approval", "approved", "draft"].includes(s.state));
  const older = scripts.filter((s) => s !== live);
  const badge = statusBadge(post.status);
  // After a failed final join the paid-for shots are all stored: the way forward is
  // Retry assembly (in the render panel), not a new script that would leave them behind.
  const canGenerate = ["draft", "awaiting_approval", "failed"].includes(post.status) &&
    post.error?.stage !== "assemble";

  return (
    <div className="flex flex-col gap-6">
      {(IN_FLIGHT.has(post.status) || post.status === "rendered" ||
        (post.status === "approved" && (shots.length === 0 ||
          (post.audio_source === "kokoro" && shots.some((s) => !s.voiced))))) && <AutoRefresh everyMs={4000} />}
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <Link href={`/calendar?m=${post.slot_date.slice(0, 7)}`} className="text-sm text-muted hover:text-foreground">
            ← {post.slot_date}
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{post.topic}</h1>
          {post.brief && <p className="mt-1 max-w-3xl text-sm whitespace-pre-line text-muted">{post.brief}</p>}
        </div>
        <span className={`rounded-md px-2 py-1 text-sm font-medium ${badge.className}`}>{badge.label}</span>
      </div>

      {post.status === "failed" && post.error?.message && (
        <div role="alert" className="rounded-xl border border-danger bg-danger-surface px-4 py-3 text-sm text-danger">
          {post.error.message}
          {post.error.stage === "config" && (
            <> — <Link href="/settings" className="font-medium underline">open Settings</Link></>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {canGenerate && <GenerateButton postId={post.id} regenerate={Boolean(live)} />}
        {post.status === "scripting" && (
          <p className="text-sm text-muted">Writing the script — this page updates by itself.</p>
        )}
      </div>

      {live ? <ScriptCard script={live} narrated={post.audio_source === "kokoro"} /> : post.status === "draft" && (
        <p className="text-sm text-muted">No script yet. Press “Write script” to draft one from the topic and brief.</p>
      )}

      {live?.state === "awaiting_approval" && <ReviewActions scriptId={live.id} />}

      {post.approved_script_id && <RenderPanel post={post} shots={shots} />}

      {post.final_key && FINISHED.has(post.status) && <PublishPanel post={post} userId={user.id} />}

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

async function RenderPanel({ post, shots }: { post: PostRow; shots: ShotRow[] }) {
  const narrated = post.audio_source === "kokoro";
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
        <h2 className="font-medium">Rendering on the GPU · shot {Math.min(rendered + 1, shots.length)} of {shots.length}</h2>
        <div className="h-2 overflow-hidden rounded-full bg-border" aria-hidden>
          <div className="h-full rounded-full bg-accent" style={{ width: `${(rendered / shots.length) * 100}%` }} />
        </div>
        <p className="text-muted">Each shot takes about a minute; the GPU is paused the moment the last one is done.</p>
      </section>
    );
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
          Usually 5–10 minutes on the GPU.
        </p>
        <RenderButton postId={post.id} retry={post.status === "failed"} />
      </section>
    );
  }
  return null;
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

function ScriptCard({ script, narrated }: { script: ScriptRow; narrated: boolean }) {
  const total = script.shot_plan.reduce((t, s) => t + s.seconds, 0);
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-lg font-semibold">{script.title}</h2>
        <span className="text-xs text-muted">
          v{script.version} · {script.model} · {total}s · {narrated ? "narrated voice-over" : "characters speak"}
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
            <div className="text-xs font-medium text-muted">Shot {i + 1} · {s.seconds}s</div>
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
