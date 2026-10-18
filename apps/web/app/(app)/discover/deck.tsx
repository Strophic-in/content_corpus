"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";

import { decideIdea, requestIdeas } from "./actions";

export type CardMedia = {
  type: "image" | "video"; src: string; poster?: string; w: number; h: number; seconds?: number;
  credit?: string; gallery?: boolean;
};

export type IdeaCard = {
  id: string; title: string; hook: string; brief: string; whyNow: string;
  category: { id: string; name: string; color: string } | null;
  format: { id: string; name: string; kind: string } | null;   // the agent's pick
  formatWhy: string;
  media: CardMedia[];
  mediaPending: boolean;
  summary: string | null;      // what the video shows (vision model)
  flags: string[];             // rights and content warnings
  sources: { url: string; label: string; detail?: string }[];
};

type Props = {
  picker?: React.ReactNode;
  daily?: React.ReactNode;           // the morning batch: on, or paused for a while
  cards: IdeaCard[];
  looking: boolean;
  channel: { id: string; name: string; timezone: string };
  categories: { id: string; name: string; color: string }[];
  formats: { id: string; name: string; kind: string }[];
  platforms: { id: "youtube" | "instagram"; label: string }[];
  suggestion: { date: string; time: string; min: string };
};

// What each kind of format makes, at a glance on the card.
const KIND_ICON: Record<string, string> = { "Reel / Short": "🎬", Carousel: "🖼️", "Picture post": "📰" };

const THRESHOLD = 110;          // px of drag that counts as a decision
const REASONS = ["Done before", "Boring", "Not our topic", "Weak source", "Not accurate", "Too sensitive"];

function addDay(ymd: string) {
  const d = new Date(`${ymd}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

function when(date: string, time: string) {
  const d = new Date(`${date}T${time}:00Z`);
  return new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })
    .format(d) + ", " + new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "UTC" }).format(d);
}

/** The card's picture or video. Only the top card plays; the ones behind show a poster. */
function Media({ m, active, muted }: { m: CardMedia; active: boolean; muted: boolean }) {
  const ratio = m.w && m.h ? Math.min(m.h / m.w, 1.25) : 0.75;      // tall videos are capped at 4:5
  const box = "relative w-full overflow-hidden rounded-2xl bg-black";
  if (m.type === "image")
    return (
      <div className={box} style={{ aspectRatio: `1 / ${ratio}` }}>
        {/* eslint-disable-next-line @next/next/no-img-element -- a signed, redirecting media URL */}
        <img src={m.src} alt="" draggable={false} className="size-full object-contain" />
        {m.gallery && <span className="absolute right-2 bottom-2 rounded-full bg-black/60 px-2 py-0.5 text-xs text-white">Gallery · 1st image</span>}
      </div>
    );
  return (
    <div className={box} style={{ aspectRatio: `1 / ${ratio}` }}>
      {active ? (
        <video src={m.src} poster={m.poster} muted={muted} autoPlay loop playsInline preload="metadata"
               className="size-full object-contain" />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- poster only for the cards behind
        m.poster ? <img src={m.poster} alt="" draggable={false} className="size-full object-contain" /> : null
      )}
      {active && (
        <span className="absolute right-2 bottom-2 rounded-full bg-black/60 px-2 py-0.5 text-xs text-white">
          {muted ? "🔇 Tap for sound" : "🔊 Sound on"}{m.seconds ? ` · ${Math.round(m.seconds)}s` : ""}
        </span>
      )}
    </div>
  );
}

/** What a card shows: the deck's top card, the ones behind it, and a card flying off.
 *  stamp: the MAKE IT / SKIP stamp, -1…1 (how far the card is dragged). */
function CardBody({ card, active, muted, stamp }: { card: IdeaCard; active: boolean; muted: boolean; stamp: number }) {
  return (
    <>
      {stamp !== 0 && (
        <>
          <span aria-hidden style={{ opacity: Math.max(0, Math.min(1, stamp)) }}
                className="absolute top-5 left-5 z-10 -rotate-12 rounded-lg border-2 border-ok bg-surface/80 px-2 py-0.5 text-sm font-bold tracking-wider text-ok">MAKE IT</span>
          <span aria-hidden style={{ opacity: Math.max(0, Math.min(1, -stamp)) }}
                className="absolute top-5 right-5 z-10 rotate-12 rounded-lg border-2 border-danger bg-surface/80 px-2 py-0.5 text-sm font-bold tracking-wider text-danger">SKIP</span>
        </>
      )}
      <div className="flex flex-wrap gap-1.5 text-xs">
        {card.category && (
          <span className="rounded-full px-2 py-0.5 font-medium text-white" style={{ background: card.category.color }}>
            {card.category.name}
          </span>
        )}
        {card.whyNow && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-accent">{card.whyNow}</span>}
      </div>
      {card.media[0] && (
        <div data-media>
          <Media m={card.media[0]} active={active} muted={muted} />
        </div>
      )}
      {!card.media.length && card.mediaPending && (
        <div className="flex aspect-video w-full animate-pulse items-center justify-center rounded-2xl bg-background text-xs text-muted">
          Fetching the picture…
        </div>
      )}
      {card.format && (
        <div className="flex items-center gap-2 rounded-xl border border-accent/40 bg-accent/10 px-3 py-2 text-sm">
          <span aria-hidden className="text-base">{KIND_ICON[card.format.kind] ?? "🎬"}</span>
          <span className="min-w-0">
            <span className="block font-semibold text-foreground">
              Will be made as: {card.format.name} <span className="font-normal text-muted">· {card.format.kind}</span>
            </span>
            {card.formatWhy && <span className="block truncate text-xs text-muted">{card.formatWhy}</span>}
          </span>
        </div>
      )}
      <h2 className="text-2xl leading-tight font-semibold">{card.title}</h2>
      {card.hook && <p className="text-base text-muted italic">“{card.hook}”</p>}
      <p className="text-sm leading-relaxed">{card.brief}</p>
      {card.summary && (
        <p className="rounded-xl bg-background px-3 py-2 text-xs leading-relaxed text-muted">
          <span className="font-medium text-foreground">In the video: </span>{card.summary}
        </p>
      )}
      {card.flags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {card.flags.map((f) => <span key={f} className="rounded-full bg-warn/15 px-2 py-0.5 text-warn">⚠ {f}</span>)}
        </div>
      )}
      {card.sources.length > 0 && (
        <div className="mt-auto flex flex-col gap-1.5 border-t border-border pt-3 text-xs">
          {card.sources.map((s) => (
            <a key={s.url} href={s.url} target="_blank" rel="noreferrer" onPointerDown={(e) => e.stopPropagation()}
               className="flex min-w-0 items-center gap-2 text-muted hover:text-foreground">
              <span className="shrink-0 font-medium text-foreground">{s.label}</span>
              {s.detail && <span className="truncate">{s.detail}</span>}
              <span className="ml-auto shrink-0">↗</span>
            </a>
          ))}
        </div>
      )}
    </>
  );
}

export function Deck({ picker, daily, cards, looking, channel, categories, formats, platforms, suggestion }: Props) {
  const router = useRouter();
  // The deck is the server's cards minus the ones decided here; cards put back
  // (Undo, Back) go to the front. Derived, so fresh server data (a new batch,
  // media that arrived) shows at once without copying cards into state.
  const [gone, setGone] = useState<Set<string>>(() => new Set());
  const [front, setFront] = useState<string[]>([]);
  const queue = useMemo(() => {
    const live = cards.filter((c) => !gone.has(c.id));
    const first = front.map((id) => live.find((c) => c.id === id)).filter((c): c is IdeaCard => !!c);
    return [...first, ...live.filter((c) => !front.includes(c.id))];
  }, [cards, gone, front]);
  const remove = (id: string) => setGone((g) => new Set(g).add(id));
  const putBack = (id: string) => {
    setGone((g) => { const n = new Set(g); n.delete(id); return n; });
    setFront((f) => [id, ...f.filter((x) => x !== id)]);
  };
  const [filter, setFilter] = useState<string | null>(null);
  const [drag, setDrag] = useState({ x: 0, y: 0, active: false });
  // Cards on their way off screen: copies, already out of the deck, so the next card is
  // live at once and nothing waits on the animation (a frozen fly-out, live 2026-10-18).
  const [flying, setFlying] = useState<{ key: number; card: IdeaCard; dir: 1 | -1; x: number; y: number }[]>([]);
  const flyKey = useRef(0);
  const [sheet, setSheet] = useState<IdeaCard | null>(null);
  const [slot, setSlot] = useState({ date: suggestion.date, time: suggestion.time });
  const [chosen, setChosen] = useState<string[]>(platforms.map((p) => p.id));
  const [media, setMedia] = useState<"none" | "original" | "ai">("none");
  const [formatId, setFormatId] = useState<string>("");
  const [skip, setSkip] = useState<{ card: IdeaCard; timer: ReturnType<typeof setTimeout> } | null>(null);
  const skipRef = useRef<typeof skip>(null);       // the same, for handlers (no side effects in updaters)
  const [notice, setNotice] = useState<{ text: string; href?: string; error?: boolean } | null>(null);
  const [target, setTarget] = useState("all");
  const [muted, setMuted] = useState(true);
  const [pending, start] = useTransition();
  const startRef = useRef({ x: 0, y: 0, t: 0, onMedia: false });

  const shown = useMemo(() => (filter ? queue.filter((c) => c.category?.id === filter) : queue), [queue, filter]);
  const top = shown[0];

  const commitSkip = useCallback((card: IdeaCard, reason: string | null) => {
    start(async () => {
      const r = await decideIdea(card.id, false, null, null, reason, null);
      if (!r.ok) setNotice({ text: r.error ?? "Couldn't skip that idea.", error: true });
    });
  }, []);

  const setSkipBoth = useCallback((next: typeof skip) => {
    skipRef.current = next;
    setSkip(next);
  }, []);

  const decide = useCallback((card: IdeaCard, dir: 1 | -1, from = { x: 0, y: 0 }) => {
    navigator.vibrate?.(12);
    const key = ++flyKey.current;
    setFlying((f) => [...f, { key, card, dir, x: from.x, y: from.y * 0.25 }]);
    setTimeout(() => setFlying((f) => f.filter((c) => c.key !== key)), 700);   // in case the animation never ends
    setDrag({ x: 0, y: 0, active: false });
    remove(card.id);
    if (dir === 1) {
      setSheet(card);
      setFormatId(card.format?.id ?? formats[0]?.id ?? "");
      return;
    }
    // One skip waits for its reason at a time: a second skip sends the first as it is.
    const prev = skipRef.current;
    if (prev) { clearTimeout(prev.timer); commitSkip(prev.card, null); }
    const timer = setTimeout(() => {
      if (skipRef.current?.card.id === card.id) setSkipBoth(null);
      commitSkip(card, null);
    }, 5000);
    setSkipBoth({ card, timer });
  }, [commitSkip, formats, setSkipBoth]);

  // ← / → on a keyboard.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!top || sheet || (e.target as HTMLElement)?.closest("input,select,textarea")) return;
      if (e.key === "ArrowRight") decide(top, 1);
      if (e.key === "ArrowLeft") decide(top, -1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [top, sheet, decide]);

  function onPointerDown(e: React.PointerEvent) {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    startRef.current = { x: e.clientX, y: e.clientY, t: performance.now(),
                         onMedia: !!(e.target as HTMLElement).closest("[data-media]") };
    setDrag({ x: 0, y: 0, active: true });
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!drag.active) return;
    setDrag({ x: e.clientX - startRef.current.x, y: e.clientY - startRef.current.y, active: true });
  }
  function onPointerUp() {
    if (!drag.active || !top) return;
    const dt = performance.now() - startRef.current.t;
    // A short, still tap on the video toggles its sound; anything else is a swipe.
    if (startRef.current.onMedia && Math.abs(drag.x) < 6 && Math.abs(drag.y) < 6 && dt < 300) {
      setMuted((m) => !m);
      setDrag({ x: 0, y: 0, active: false });
      return;
    }
    const speed = Math.abs(drag.x) / Math.max(1, dt);   // px/ms
    if (Math.abs(drag.x) > THRESHOLD || (speed > 0.6 && Math.abs(drag.x) > 40)) decide(top, drag.x > 0 ? 1 : -1, drag);
    else setDrag({ x: 0, y: 0, active: false });                                         // spring back
  }

  function schedule() {
    if (!sheet) return;
    const card = sheet;
    start(async () => {
      const r = await decideIdea(card.id, true, slot.date, slot.time, null, chosen, media, formatId || null);
      if (!r.ok) {
        setNotice({ text: r.error ?? "Couldn't schedule it.", error: true });
        return;
      }
      setSheet(null);
      setMedia("none");
      setNotice({ text: `Scheduled · ${when(slot.date, slot.time)}`, href: r.postId ? `/posts/${r.postId}` : undefined });
      setSlot((s) => ({ ...s, date: addDay(s.date) }));
      setTimeout(() => setNotice(null), 4000);
    });
  }

  function cancelSheet() {
    if (sheet) putBack(sheet.id);
    setSheet(null);
    setMedia("none");
  }

  function undoSkip() {
    if (!skip) return;
    clearTimeout(skip.timer);
    putBack(skip.card.id);
    setSkipBoth(null);
  }

  function findIdeas() {
    start(async () => {
      const r = await requestIdeas(target === "all" ? { channelId: channel.id } : { categoryId: target });
      if (!r?.ok) setNotice({ text: r?.error ?? "Couldn't start the agent.", error: true });
      router.refresh();
    });
  }

  const x = drag.x;
  const y = drag.y * 0.25;
  const counts = useMemo(() => {
    const n = new Map<string, number>();
    for (const c of queue) if (c.category) n.set(c.category.id, (n.get(c.category.id) ?? 0) + 1);
    return n;
  }, [queue]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">Discover</h1>
          <p className="flex items-center gap-1 text-sm text-muted">
            {shown.length ? `${shown.length} idea${shown.length === 1 ? "" : "s"} for` : "For"} {picker ?? channel.name}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {categories.length > 1 && (
            <select aria-label="Find ideas for" value={target} onChange={(e) => setTarget(e.target.value)}
                    className="max-w-32 rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none">
              <option value="all">All categories</option>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <button onClick={findIdeas} disabled={pending || looking}
                  className="shrink-0 rounded-full border border-border px-3 py-1.5 text-sm font-medium hover:border-accent disabled:opacity-50">
            {looking ? "Looking…" : "More ideas"}
          </button>
        </div>
      </div>

      {daily}

      {categories.length > 1 && queue.length > 0 && (
        <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 text-xs">
          <button onClick={() => setFilter(null)}
                  className={`shrink-0 rounded-full border px-3 py-1 ${filter === null ? "border-accent text-accent" : "border-border text-muted"}`}>
            All · {queue.length}
          </button>
          {categories.filter((c) => counts.get(c.id)).map((c) => (
            <button key={c.id} onClick={() => setFilter(filter === c.id ? null : c.id)}
                    className={`shrink-0 rounded-full border px-3 py-1 ${filter === c.id ? "text-foreground" : "text-muted"}`}
                    style={{ borderColor: filter === c.id ? c.color : undefined }}>
              <span className="mr-1 inline-block size-2 rounded-full" style={{ background: c.color }} />
              {c.name} · {counts.get(c.id)}
            </button>
          ))}
        </div>
      )}

      {/* The top card is in the flow and as tall as its content (the page scrolls if it
          is long); the cards peeking behind it fill the same box. */}
      <div className="relative select-none">
        {shown.slice(0, 3).reverse().map((card, revIdx, arr) => {
          const depth = arr.length - 1 - revIdx;          // 0 = top
          const isTop = depth === 0;
          const style: React.CSSProperties = isTop
            ? { transform: `translate(${x}px, ${y}px) rotate(${x / 18}deg)`,
                transition: drag.active ? "none" : "transform 260ms cubic-bezier(.2,.9,.3,1.25)",
                touchAction: "pan-y" }
            : { transform: `translateY(${depth * 12}px) scale(${1 - depth * 0.05})`, transition: "transform 300ms ease" };
          return (
            <article key={card.id} style={style}
                     onPointerDown={isTop ? onPointerDown : undefined} onPointerMove={isTop ? onPointerMove : undefined}
                     onPointerUp={isTop ? onPointerUp : undefined} onPointerCancel={isTop ? onPointerUp : undefined}
                     className={`flex flex-col gap-3 overflow-hidden rounded-3xl border border-border bg-surface p-5 shadow-xl ${isTop ? "relative min-h-[min(58vh,520px)] cursor-grab active:cursor-grabbing" : "pointer-events-none absolute inset-0"}`}>
              <CardBody card={card} active={isTop} muted={muted} stamp={isTop ? x / THRESHOLD : 0} />
            </article>
          );
        })}

        {flying.map((f) => (
          <article key={f.key} aria-hidden
                   ref={(el) => {
                     if (!el || el.dataset.flown) return;
                     el.dataset.flown = "1";
                     const to = f.dir * 700;
                     el.animate(
                       [{ transform: `translate(${f.x}px, ${f.y}px) rotate(${f.x / 18}deg)`, opacity: 1 },
                        { transform: `translate(${to}px, ${f.y}px) rotate(${to / 18}deg)`, opacity: 0 }],
                       { duration: 260, easing: "cubic-bezier(.4,0,1,1)", fill: "forwards" },
                     ).onfinish = () => setFlying((all) => all.filter((c) => c.key !== f.key));
                   }}
                   className="pointer-events-none absolute inset-x-0 top-0 z-30 flex min-h-[min(58vh,520px)] flex-col gap-3 overflow-hidden rounded-3xl border border-border bg-surface p-5 shadow-xl">
            <CardBody card={f.card} active={false} muted stamp={f.dir} />
          </article>
        ))}

        {!shown.length && (
          <div className="flex min-h-[min(58vh,520px)] flex-col items-center justify-center gap-4 rounded-3xl border border-dashed border-border p-8 text-center">
            {looking ? (
              <>
                <div className="flex gap-1.5" aria-hidden>
                  {[0, 1, 2].map((i) => <span key={i} className="size-2.5 animate-bounce rounded-full bg-accent" style={{ animationDelay: `${i * 150}ms` }} />)}
                </div>
                <p className="font-medium">The agent is reading today&apos;s sources…</p>
                <p className="text-sm text-muted">Reddit allows about one request a minute, so a few categories take a few minutes.</p>
              </>
            ) : (
              <>
                <p className="text-lg font-medium">{filter ? "Nothing left in this category" : "You're all caught up"}</p>
                <p className="text-sm text-muted">New ideas arrive every morning, or ask for some now.</p>
                <button onClick={findIdeas} disabled={pending}
                        className="rounded-full bg-accent px-5 py-2.5 text-sm font-medium text-accent-foreground disabled:opacity-60">
                  Find ideas
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Pinned just above the tab bar, so they stay in reach while a long card scrolls. */}
      {top && (
        <div className="sticky bottom-[calc(env(safe-area-inset-bottom)+5rem)] z-20 flex items-center justify-center gap-8 md:bottom-4">
          <button aria-label="Skip" onClick={() => decide(top, -1)}
                  className="grid size-16 place-items-center rounded-full border border-border bg-surface text-2xl text-danger shadow-md transition active:scale-90">✕</button>
          <button aria-label="Make it" onClick={() => decide(top, 1)}
                  className="grid size-16 place-items-center rounded-full border border-border bg-surface text-2xl text-ok shadow-md transition active:scale-90">✓</button>
        </div>
      )}

      {skip && (
        <div className="anim-toast fixed inset-x-3 bottom-24 z-50 mx-auto max-w-md rounded-2xl border border-border bg-surface p-3 shadow-2xl md:bottom-6">
          <div className="flex items-center gap-3 text-sm">
            <span className="flex-1 truncate">Skipped — why?</span>
            <button onClick={undoSkip} className="font-medium text-accent">Undo</button>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {REASONS.map((r) => (
              <button key={r} onClick={() => { clearTimeout(skip.timer); commitSkip(skip.card, r); setSkipBoth(null); }}
                      className="rounded-full border border-border px-2.5 py-1 text-xs hover:border-accent">{r}</button>
            ))}
          </div>
        </div>
      )}

      {notice && !skip && (
        <div role={notice.error ? "alert" : "status"}
             className={`anim-toast fixed inset-x-3 bottom-24 z-50 mx-auto flex max-w-md items-center gap-3 rounded-2xl border p-3 text-sm shadow-2xl md:bottom-6 ${notice.error ? "border-danger bg-danger-surface text-danger" : "border-border bg-surface"}`}>
          <span className="flex-1">{notice.text}</span>
          {notice.href && <Link href={notice.href} className="font-medium text-accent">Open</Link>}
          <button aria-label="Dismiss" onClick={() => setNotice(null)} className="text-muted">✕</button>
        </div>
      )}

      {sheet && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 md:items-center" onClick={cancelSheet}>
          <div onClick={(e) => e.stopPropagation()}
               className="anim-sheet w-full max-w-md rounded-t-3xl border border-border bg-surface p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-2xl md:rounded-3xl">
            <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-border md:hidden" />
            <p className="text-xs font-medium tracking-wide text-ok uppercase">Make it</p>
            <h3 className="mt-1 text-lg leading-snug font-semibold">{sheet.title}</h3>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1 text-sm">Day
                <input type="date" value={slot.date} min={suggestion.min}
                       onChange={(e) => setSlot((s) => ({ ...s, date: e.target.value }))}
                       className="rounded-xl border border-border bg-background px-3 py-2.5 outline-none focus:border-accent" />
              </label>
              <label className="flex flex-col gap-1 text-sm">Time
                <input type="time" step={60} value={slot.time.slice(0, 5)} onChange={(e) => setSlot((s) => ({ ...s, time: e.target.value }))}
                       className="rounded-xl border border-border bg-background px-3 py-2.5 outline-none focus:border-accent" />
              </label>
            </div>
            {formats.length > 1 && (
              <label className="mt-3 flex flex-col gap-1 text-sm">Make it as
                <select value={formatId} onChange={(e) => setFormatId(e.target.value)}
                        className="rounded-xl border border-border bg-background px-3 py-2.5 outline-none focus:border-accent">
                  {formats.map((f) => <option key={f.id} value={f.id}>{f.name} · {f.kind}</option>)}
                </select>
                {sheet.formatWhy && formatId === sheet.format?.id &&
                  <span className="text-xs text-muted">The agent&apos;s pick: {sheet.formatWhy}</span>}
              </label>
            )}
            {platforms.length > 0 && (
              <fieldset className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm">
                <legend className="mb-1 text-muted">Post to</legend>
                {platforms.map((p) => (
                  <label key={p.id} className="flex items-center gap-2">
                    <input type="checkbox" checked={chosen.includes(p.id)} className="size-4 accent-accent"
                           onChange={() => setChosen((c) => (c.includes(p.id) ? c.filter((x) => x !== p.id) : [...c, p.id]))} />
                    {p.label}
                  </label>
                ))}
              </fieldset>
            )}
            {sheet.media.length > 0 && (() => {
              const what = sheet.media[0].type === "video" ? "video" : "picture";
              const options: { id: "none" | "original" | "ai"; title: string; note: string }[] = [
                { id: "none", title: `Don't use its ${what}`, note: "The reel is made from scratch." },
                { id: "original", title: `Use the ${what}`,
                  note: `Shown with credit${sheet.media[0].credit ? ` (${sheet.media[0].credit})` : ""}. It belongs to `
                    + "whoever made it — only if you're comfortable publishing it." },
                { id: "ai", title: "Make an AI version",
                  note: what === "picture"
                    ? "A new picture of the same scene, drawn by OpenAI in your channel's look (about ₹3.5 with gpt-image-2). The original is never shown."
                    : "Its moments recreated on the GPU, labelled “AI reconstruction”. The original is never shown." },
              ];
              return (
                <fieldset className="mt-4 flex flex-col gap-2 text-sm">
                  <legend className="mb-1 text-muted">Its {what}</legend>
                  {options.map((o) => (
                    <label key={o.id} className={`flex items-start gap-3 rounded-xl border p-3 ${media === o.id
                      ? "border-accent bg-background" : "border-border"}`}>
                      <input type="radio" name="media" checked={media === o.id} onChange={() => setMedia(o.id)}
                             className="mt-0.5 size-4 shrink-0 accent-accent" />
                      <span>
                        <span className="font-medium">{o.title}</span>
                        <span className="block text-xs text-muted">{o.note}</span>
                      </span>
                    </label>
                  ))}
                  {media === "original" && sheet.flags.length > 0 &&
                    <p className="text-xs text-warn">{sheet.flags.join(" · ")}.</p>}
                </fieldset>
              );
            })()}
            <p className="mt-2 text-xs text-muted">Times are in {channel.timezone}.</p>
            <div className="mt-5 flex gap-3">
              <button onClick={cancelSheet} className="flex-1 rounded-xl border border-border py-3 text-sm font-medium">Back</button>
              <button onClick={schedule} disabled={pending}
                      className="flex-1 rounded-xl bg-accent py-3 text-sm font-semibold text-accent-foreground disabled:opacity-60">
                {pending ? "Scheduling…" : "Schedule"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
