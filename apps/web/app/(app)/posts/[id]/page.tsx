import Link from "next/link";
import { notFound } from "next/navigation";

import { workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { postDetail, type PostRow, type ScriptRow, type ShotRow } from "@/lib/posts";
import { signedUrl } from "@/lib/r2";
import { requireUser } from "@/lib/session";
import { IN_FLIGHT, statusBadge } from "@/lib/status";

import { PostForm } from "../post-form";
import { AutoRefresh, DeletePostButton, GenerateButton, RenderButton, ReviewActions } from "./post-actions";

export const metadata = { title: "Post · Content Corpus" };

const EDITABLE = new Set(["draft", "awaiting_approval", "failed"]);

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

  if (post.status === "ready" || post.status === "scheduled" || post.status === "published") {
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
