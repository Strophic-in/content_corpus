import Link from "next/link";

import { workspace } from "@/lib/channels";
import { libraryPosts, type LibraryPost } from "@/lib/posts";
import { requireUser } from "@/lib/session";
import { TONE_CLASS } from "@/lib/status";
import { COST_LABEL, KIND_LABEL, ordered, template, templateInfo } from "@/lib/templates";

import { ChannelPicker } from "../nav";
import { NewFormatForm } from "./library-forms";

export const metadata = { title: "Library · Content Corpus" };

const AUDIO = { kokoro: "Narrated", ltx_native: "Characters speak", none: "No voice" } as const;

// The Library's plain-words status: has it gone out, is it waiting to, or did it stop.
type Group = "posted" | "scheduled" | "ready" | "review" | "making" | "failed" | "cancelled";
const GROUP: Record<Group, { label: string; tone: keyof typeof TONE_CLASS }> = {
  posted: { label: "Posted", tone: "good" },
  scheduled: { label: "Scheduled", tone: "good" },
  ready: { label: "Ready to post", tone: "busy" },
  review: { label: "Needs review", tone: "attention" },
  making: { label: "In progress", tone: "neutral" },
  failed: { label: "Failed", tone: "bad" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

function group(p: LibraryPost): Group {
  if (p.status === "published" || p.live.length) return "posted";
  if (p.status === "scheduled" || p.scheduled) return "scheduled";
  if (p.status === "ready" || p.status === "rendered") return "ready";
  if (p.status === "awaiting_approval" || p.status === "needs_review") return "review";
  if (p.status === "failed") return "failed";
  if (p.status === "cancelled") return "cancelled";
  return "making";
}

// The step a post is at, named exactly: a draft has not even a script yet, and
// "being made" for it would be wrong. (hint: what the card's empty frame says.)
const STEP: Record<string, { label: string; hint: string }> = {
  draft: { label: "Not started", hint: "Script not written yet" },
  scripting: { label: "Writing script", hint: "Writing the script…" },
  awaiting_approval: { label: "Script to review", hint: "Script written — waiting for your OK" },
  needs_review: { label: "Needs attention", hint: "Stopped — open it to see why" },
  approved: { label: "Not rendered yet", hint: "Script approved — not rendered yet" },
  queued_for_render: { label: "Queued to render", hint: "Waiting for a GPU" },
  rendering: { label: "Rendering", hint: "Rendering…" },
  post_processing: { label: "Assembling", hint: "Putting it together…" },
  failed: { label: "Failed", hint: "Failed — open it to see why" },
  cancelled: { label: "Cancelled", hint: "Cancelled" },
};

function chip(p: LibraryPost, g: Group) {
  return g === "making" || g === "review" || g === "failed" ? STEP[p.status]?.label ?? GROUP[g].label : GROUP[g].label;
}

// The filter chips: "Not posted yet" is everything still on its way out.
const FILTERS: { id: string; label: string; has: (g: Group, status: string) => boolean }[] = [
  { id: "all", label: "All", has: () => true },
  { id: "posted", label: "Posted", has: (g: Group) => g === "posted" },
  { id: "waiting", label: "Not posted yet", has: (g: Group) => ["scheduled", "ready", "review", "making"].includes(g) },
  { id: "notstarted", label: "Not started", has: (_g, s) => s === "draft" },
  { id: "stopped", label: "Failed or cancelled", has: (g: Group) => g === "failed" || g === "cancelled" },
];

const DOT: Record<keyof typeof TONE_CLASS, string> = {
  neutral: "bg-white/60", busy: "bg-accent", attention: "bg-warn", good: "bg-ok", bad: "bg-danger",
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
      {[{ href: "/library", label: "Posts", on: view !== "formats" },
        { href: "/library?view=formats", label: "Formats", on: view === "formats" }].map((t) => (
        <Link key={t.href} href={t.href}
              className={`rounded-full px-3 py-1 ${t.on ? "bg-accent text-white" : "text-muted hover:text-foreground"}`}>
          {t.label}
        </Link>
      ))}
    </div>
  );

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
  const filter = FILTERS.find((f) => f.id === show) ?? FILTERS[0];
  const shown = posts.filter((p) => filter.has(p.group, p.status));
  const date = (d: string) => new Intl.DateTimeFormat("en", { day: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(`${d}T00:00:00Z`));

  return (
    <div className="flex flex-col gap-5">
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
                    <div className="flex size-full items-center justify-center p-4 text-center text-xs text-muted">
                      {STEP[p.status]?.hint ?? "No video yet"}
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
