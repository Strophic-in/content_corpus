import Link from "next/link";

import { workspace } from "@/lib/channels";
import { overview } from "@/lib/costs";
import { lookName } from "@/lib/looks";
import { progress } from "@/lib/pipeline";
import { libraryPosts } from "@/lib/posts";
import { requireUser } from "@/lib/session";
import { COST_LABEL, KIND_LABEL, ordered, template, templateInfo } from "@/lib/templates";

import { ChannelPicker } from "../nav";
import { AutoRefresh } from "../posts/[id]/post-actions";
import { NewFormatForm } from "./library-forms";
import { OverviewTable, type TableRow } from "./overview-table";
import { chip, DOT, FILTERS, group, GROUP, STEP } from "./stage";

export const metadata = { title: "Library · Content Corpus" };

const AUDIO = { kokoro: "Narrated", ltx_native: "Characters speak", none: "No voice" } as const;

// Pipeline order, so sorting by stage reads from "not started" to "posted".
const STAGE_ORDER = ["draft", "scripting", "awaiting_approval", "needs_review", "approved", "queued_for_render",
  "rendering", "rendered", "post_processing", "ready", "scheduled", "published", "failed", "cancelled"];
const SCRIPT_STATE: Record<string, string> = {
  draft: "draft", awaiting_approval: "to review", approved: "approved", rejected: "rejected", superseded: "replaced",
};

const KIND = { reel: "Reel", longform: "Video", carousel: "Carousel", image: "Picture" } as const;
const PLATFORM = { youtube: "YouTube", instagram: "Instagram" } as const;

export default async function LibraryPage({ searchParams }: { searchParams: Promise<{ view?: string; show?: string }> }) {
  const user = await requireUser();
  const { channels, active, formats } = await workspace(user.id);
  const { view, show } = await searchParams;
  const picker = <ChannelPicker channels={channels.map(({ id, name }) => ({ id, name }))} activeId={active.id} />;
  const tabs = (
    <div className="flex gap-1 rounded-full border border-border bg-surface p-1 text-sm">
      {[{ href: "/library", label: "Posts", on: view !== "formats" && view !== "table" },
        { href: "/library?view=table", label: "Table", on: view === "table" },
        { href: "/library?view=formats", label: "Formats", on: view === "formats" }].map((t) => (
        <Link key={t.href} href={t.href}
              className={`rounded-full px-3 py-1 ${t.on ? "bg-accent text-white" : "text-muted hover:text-foreground"}`}>
          {t.label}
        </Link>
      ))}
    </div>
  );

  if (view === "table") {
    const stamp = new Intl.DateTimeFormat("sv-SE", { timeZone: active.timezone, dateStyle: "short", timeStyle: "short" });
    const rows: TableRow[] = (await overview(user.id, active.id)).map((r) => {
      const g = group(r);
      return {
        id: r.id, title: r.title, topic: r.topic, date: r.slot_date, time: r.publish_time,
        kind: KIND[r.format as keyof typeof KIND] ?? r.format, template: r.template_id ? template(r.template_id).display_name : "",
        stage: chip(r, g), dot: DOT[GROUP[g].tone], stageOrder: STAGE_ORDER.indexOf(r.status), error: r.error,
        status: r.status, goAhead: r.go_ahead,
        script: r.script_version != null ? `v${r.script_version} · ${SCRIPT_STATE[r.script_state ?? ""] ?? r.script_state}` : null,
        scriptScore: r.script_score != null ? Number(r.script_score) : null, versions: r.versions,
        shots: r.shots, shotsDone: r.shots_done, slides: r.slides, seconds: r.seconds != null ? Number(r.seconds) : null,
        look: lookName(r.look_id),
        cost: { writing: r.writing, pictures: r.pictures, voice: r.voice, gpu: r.gpu, idea: r.idea, total: r.total,
                unpriced: r.unpriced },
        gpuMinutes: r.gpu_seconds != null ? Number(r.gpu_seconds) / 60 : null,
        live: r.live, views: r.views, likes: r.likes, comments: r.comments, updated: stamp.format(r.updated_at),
      };
    });
    return (
      <div className="full-bleed flex flex-col gap-5">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
            <p className="mt-1 text-sm text-muted">Every post {picker} has made, one row each. Click a column to sort; tick rows to act on them.</p>
          </div>
          {tabs}
        </div>
        <OverviewTable rows={rows} />
      </div>
    );
  }

  if (view === "formats") {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight">Formats</h1>
            <p className="mt-1 text-sm text-muted">
              The kinds of post {picker} makes — each one a template (a reel, a carousel, a picture card…) with your
              prompts and look. A category picks which of them its ideas may use; the idea agent chooses one per idea.
            </p>
          </div>
          {tabs}
        </div>
        <div className="grid auto-rows-fr gap-3 sm:grid-cols-2">
          {formats.map((f) => {
            const t = template(f.template_id);
            return (
              <Link key={f.id} href={`/library/${f.id}`}
                    className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-4 transition hover:border-accent active:scale-[.99]">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium">{f.name}</span>
                  {f.is_default && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">default</span>}
                  <span className="ml-auto shrink-0 text-xs text-muted">v{f.version}</span>
                </div>
                <p className="text-xs font-medium text-muted">{t.display_name}</p>
                <p className="line-clamp-2 text-sm text-muted">{f.description || t.format}</p>
                <p className="mt-auto text-xs text-muted">
                  {KIND_LABEL[f.content_type]} · {f.content_type === "video" ? `${AUDIO[f.audio_source]} · ${f.target_seconds}s · ` : ""}
                  {COST_LABEL[t.estimated_render_cost]}
                </p>
              </Link>
            );
          })}
        </div>
        <section className="rounded-2xl border border-border bg-surface p-5">
          <h2 className="font-medium">New format</h2>
          <p className="mt-1 text-sm text-muted">Pick a template; it starts with the template&apos;s prompts and look, and you change anything after.</p>
          <div className="mt-4"><NewFormatForm templates={ordered().map(templateInfo)} /></div>
        </section>
      </div>
    );
  }

  const posts = (await libraryPosts(user.id, active.id)).map((p) => ({ ...p, group: group(p) }));
  const busy = posts.some((p) => ["scripting", "queued_for_render", "rendering", "rendered", "post_processing"]
    .includes(p.status));
  const filter = FILTERS.find((f) => f.id === show) ?? FILTERS[0];
  const shown = posts.filter((p) => filter.has(p.group, p.status));
  const date = (d: string) => new Intl.DateTimeFormat("en", { day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(`${d}T00:00:00Z`));

  return (
    <div className="flex flex-col gap-5">
      {busy && <AutoRefresh everyMs={8000} />}
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">Library</h1>
          <p className="mt-1 text-sm text-muted">Everything {picker} has made, newest first. Open one to see it.</p>
        </div>
        {tabs}
      </div>

      <div className="flex flex-wrap gap-2 text-sm">
        {FILTERS.map((f) => {
          const n = posts.filter((p) => f.has(p.group, p.status)).length;
          const on = f.id === filter.id;
          return (
            <Link key={f.id} href={f.id === "all" ? "/library" : `/library?show=${f.id}`}
                  className={`rounded-full border px-3 py-1 ${on ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"}`}>
              {f.label} <span className="tabular-nums opacity-70">{n}</span>
            </Link>
          );
        })}
      </div>

      {shown.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted">
          {posts.length ? "Nothing here." : <>Nothing made yet — accept an idea on <Link href="/discover" className="text-accent">Discover</Link>.</>}
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {shown.map((p) => {
            const g = GROUP[p.group];
            return (
              <Link key={p.id} href={`/posts/${p.id}`}
                    className="group flex flex-col gap-2 rounded-2xl border border-border bg-surface p-2 transition hover:border-accent active:scale-[.99]">
                <div className="relative aspect-[9/16] overflow-hidden rounded-xl bg-background">
                  {p.has_slides ? (
                    // eslint-disable-next-line @next/next/no-img-element -- a signed, redirecting media URL
                    <img src={`/media/post/${p.id}?slide=1`} alt="" loading="lazy" className="size-full object-cover" />
                  ) : p.has_video ? (
                    <video src={`/media/post/${p.id}#t=1`} muted playsInline preload="metadata"
                           className="size-full object-cover" />
                  ) : (
                    <div className={`flex size-full flex-col items-center justify-center gap-3 p-4 text-center ${
                      ["scripting", "queued_for_render", "rendering", "rendered", "post_processing"].includes(p.status)
                        ? "stage-glow" : ""}`}>
                      <StageIcon status={p.status} />
                      <span className="text-xs leading-snug text-muted">{STEP[p.status]?.hint ?? "No video yet"}</span>
                    </div>
                  )}
                  <span className="absolute left-2 top-2 flex items-center gap-1.5 rounded-full bg-black/70 px-2 py-0.5 text-[11px] font-medium text-white backdrop-blur">
                    <span className={`size-1.5 rounded-full ${DOT[g.tone]}`} />
                    {chip(p, p.group)}
                  </span>
                  {p.seconds != null && p.has_video && !p.has_slides && (
                    <span className="absolute bottom-2 right-2 rounded bg-black/60 px-1.5 py-0.5 text-[11px] tabular-nums text-white">
                      0:{String(p.seconds).padStart(2, "0")}
                    </span>
                  )}
                  {/* how far along: a thin bar that moves as the post does */}
                  {p.group !== "posted" && p.group !== "cancelled" && (
                    <span aria-hidden className="absolute inset-x-0 bottom-0 h-1 bg-black/40">
                      <span className={`block h-full transition-all duration-700 ${p.group === "failed" ? "bg-danger"
                        : p.group === "making" ? "bg-accent" : p.group === "review" ? "bg-warn" : "bg-ok"}`}
                            style={{ width: `${Math.round(progress(p.status) * 100)}%` }} />
                    </span>
                  )}
                </div>
                <div className="flex flex-col gap-0.5 px-1 pb-1">
                  <span className="line-clamp-2 text-sm font-medium leading-snug">{p.title}</span>
                  <span className="text-xs text-muted">
                    {date(p.slot_date)} · {KIND[p.format] ?? p.format}
                    {p.live.length > 0 && <> · {p.live.map((l) => PLATFORM[l.platform]).join(", ")}</>}
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}


/** A small picture of the stage a post without a video is at. */
function StageIcon({ status }: { status: string }) {
  const busy = ["scripting", "queued_for_render", "rendering", "rendered", "post_processing"].includes(status);
  const path = status === "draft" ? "M12 5v14M5 12h14"                                   // not started: a plus
    : status === "scripting" ? "M4 20h4L19 9l-4-4L4 16v4ZM14 6l4 4"                   // writing: a pen
    : status === "awaiting_approval" || status === "needs_review" ? "M12 8v5M12 16h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z"
    : status === "failed" ? "M6 6l12 12M18 6 6 18"
    : status === "approved" ? "M5 12.5l4.5 4.5L19 7"
    : "M8 5v14l11-7L8 5Z";                                                               // rendering: play
  const tone = status === "failed" ? "text-danger bg-danger/10" : status === "awaiting_approval" ? "text-warn bg-warn/10"
    : busy ? "text-accent bg-accent/15" : "text-muted bg-border/50";
  return (
    <span className={`relative grid size-12 place-items-center rounded-full ${tone}`}>
      {busy && <span aria-hidden className="absolute inset-0 animate-ping rounded-full bg-accent/20" />}
      <svg viewBox="0 0 24 24" aria-hidden className="relative size-6" fill="none" stroke="currentColor" strokeWidth={2}
           strokeLinecap="round" strokeLinejoin="round"><path d={path} /></svg>
    </span>
  );
}

