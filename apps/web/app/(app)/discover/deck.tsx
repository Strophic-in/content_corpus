"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";

import { decideIdea, requestIdeas } from "./actions";

export type IdeaCard = {
  id: string; title: string; hook: string; brief: string; whyNow: string; format: string;
  sources: { url: string; label: string }[];
};

type Props = {
  picker?: React.ReactNode;
  cards: IdeaCard[];
  looking: boolean;
  channel: { name: string; timezone: string };
  formats: { id: string; name: string }[];
  defaultFormatId: string;
  suggestion: { date: string; time: string; min: string };
};

const THRESHOLD = 110;          // px of drag that counts as a decision
const REASONS = ["Done before", "Boring", "Too complex to animate", "Off-topic", "Not accurate"];

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

export function Deck({ picker, cards, looking, channel, formats, defaultFormatId, suggestion }: Props) {
  const router = useRouter();
  const [queue, setQueue] = useState(cards);
  const [drag, setDrag] = useState({ x: 0, y: 0, active: false });
  const [leaving, setLeaving] = useState<{ id: string; dir: 1 | -1 } | null>(null);
  const [sheet, setSheet] = useState<IdeaCard | null>(null);
  const [slot, setSlot] = useState({ date: suggestion.date, time: suggestion.time });
  const [skip, setSkip] = useState<{ card: IdeaCard; timer: ReturnType<typeof setTimeout> } | null>(null);
  const [notice, setNotice] = useState<{ text: string; href?: string; error?: boolean } | null>(null);
  const [formatId, setFormatId] = useState(defaultFormatId);
  const [pending, start] = useTransition();
  const startRef = useRef({ x: 0, y: 0, t: 0 });

  // New cards from the server (a finished batch) join the end of the deck.
  useEffect(() => {
    setQueue((q) => [...q, ...cards.filter((c) => !q.some((k) => k.id === c.id))]);
  }, [cards]);

  const top = queue[0];

  const commitSkip = useCallback((card: IdeaCard, reason: string | null) => {
    start(async () => {
      const r = await decideIdea(card.id, false, null, null, reason);
      if (!r.ok) setNotice({ text: r.error ?? "Couldn't skip that idea.", error: true });
    });
  }, []);

  const decide = useCallback((card: IdeaCard, dir: 1 | -1) => {
    navigator.vibrate?.(12);
    setLeaving({ id: card.id, dir });
    setTimeout(() => {
      setLeaving(null);
      setDrag({ x: 0, y: 0, active: false });
      setQueue((q) => q.filter((c) => c.id !== card.id));
      if (dir === 1) {
        setSheet(card);
      } else {
        setSkip((prev) => {
          if (prev) { clearTimeout(prev.timer); commitSkip(prev.card, null); }
          return { card, timer: setTimeout(() => { setSkip(null); commitSkip(card, null); }, 5000) };
        });
      }
    }, 240);
  }, [commitSkip]);

  // ← / → on a keyboard.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!top || sheet || leaving || (e.target as HTMLElement)?.closest("input,select,textarea")) return;
      if (e.key === "ArrowRight") decide(top, 1);
      if (e.key === "ArrowLeft") decide(top, -1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [top, sheet, leaving, decide]);

  function onPointerDown(e: React.PointerEvent) {
    if (leaving) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    startRef.current = { x: e.clientX, y: e.clientY, t: performance.now() };
    setDrag({ x: 0, y: 0, active: true });
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!drag.active) return;
    setDrag({ x: e.clientX - startRef.current.x, y: e.clientY - startRef.current.y, active: true });
  }
  function onPointerUp() {
    if (!drag.active || !top) return;
    const speed = Math.abs(drag.x) / Math.max(1, performance.now() - startRef.current.t);   // px/ms
    if (Math.abs(drag.x) > THRESHOLD || (speed > 0.6 && Math.abs(drag.x) > 40)) decide(top, drag.x > 0 ? 1 : -1);
    else setDrag({ x: 0, y: 0, active: false });                                         // spring back
  }

  function schedule() {
    if (!sheet) return;
    const card = sheet;
    start(async () => {
      const r = await decideIdea(card.id, true, slot.date, slot.time, null);
      if (!r.ok) {
        setNotice({ text: r.error ?? "Couldn't schedule it.", error: true });
        return;
      }
      setSheet(null);
      setNotice({ text: `Scheduled · ${when(slot.date, slot.time)}`, href: r.postId ? `/posts/${r.postId}` : undefined });
      setSlot((s) => ({ ...s, date: addDay(s.date) }));
      setTimeout(() => setNotice(null), 4000);
    });
  }

  function cancelSheet() {
    if (sheet) setQueue((q) => [sheet, ...q]);
    setSheet(null);
  }

  function undoSkip() {
    if (!skip) return;
    clearTimeout(skip.timer);
    setQueue((q) => [skip.card, ...q]);
    setSkip(null);
  }

  function findIdeas() {
    start(async () => {
      const r = await requestIdeas(formatId);
      if (!r?.ok) setNotice({ text: r?.error ?? "Couldn't start the agent.", error: true });
      router.refresh();
    });
  }

  const x = leaving ? leaving.dir * 700 : drag.x;
  const y = leaving ? drag.y : drag.y * 0.25;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Discover</h1>
          <p className="flex items-center gap-1 text-sm text-muted">
            {queue.length ? `${queue.length} idea${queue.length === 1 ? "" : "s"} for` : "For"} {picker ?? channel.name}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {formats.length > 1 && (
            <select aria-label="Format" value={formatId} onChange={(e) => setFormatId(e.target.value)}
                    className="max-w-32 rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none">
              {formats.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          )}
          <button onClick={findIdeas} disabled={pending || looking}
                  className="rounded-full border border-border px-3 py-1.5 text-sm font-medium hover:border-accent disabled:opacity-50">
            {looking ? "Looking…" : "More ideas"}
          </button>
        </div>
      </div>

      {/* The top card is in the flow and as tall as its text (the page scrolls if it
          is long); the cards peeking behind it fill the same box. */}
      <div className="relative select-none">
        {queue.slice(0, 3).reverse().map((card, revIdx, arr) => {
          const depth = arr.length - 1 - revIdx;          // 0 = top
          const isTop = depth === 0;
          const style: React.CSSProperties = isTop
            ? { transform: `translate(${x}px, ${y}px) rotate(${x / 18}deg)`,
                transition: drag.active && !leaving ? "none" : "transform 260ms cubic-bezier(.2,.9,.3,1.25)",
                touchAction: "pan-y" }
            : { transform: `translateY(${depth * 12}px) scale(${1 - depth * 0.05})`, transition: "transform 300ms ease" };
          return (
            <article key={card.id} style={style}
                     onPointerDown={isTop ? onPointerDown : undefined} onPointerMove={isTop ? onPointerMove : undefined}
                     onPointerUp={isTop ? onPointerUp : undefined} onPointerCancel={isTop ? onPointerUp : undefined}
                     className={`flex flex-col gap-3 overflow-hidden rounded-3xl border border-border bg-surface p-6 shadow-xl ${isTop ? "relative min-h-[min(58vh,520px)] cursor-grab active:cursor-grabbing" : "pointer-events-none absolute inset-0"}`}>
              {isTop && (
                <>
                  <span aria-hidden style={{ opacity: Math.max(0, Math.min(1, x / THRESHOLD)) }}
                        className="absolute top-5 left-5 -rotate-12 rounded-lg border-2 border-ok px-2 py-0.5 text-sm font-bold tracking-wider text-ok">MAKE IT</span>
                  <span aria-hidden style={{ opacity: Math.max(0, Math.min(1, -x / THRESHOLD)) }}
                        className="absolute top-5 right-5 rotate-12 rounded-lg border-2 border-danger px-2 py-0.5 text-sm font-bold tracking-wider text-danger">SKIP</span>
                </>
              )}
              <div className="mt-6 flex flex-wrap gap-1.5 text-xs">
                {card.format && <span className="rounded-full bg-background px-2 py-0.5 text-muted">{card.format}</span>}
                {card.whyNow && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-accent">{card.whyNow}</span>}
              </div>
              <h2 className="text-2xl leading-tight font-semibold">{card.title}</h2>
              {card.hook && <p className="text-base text-muted italic">“{card.hook}”</p>}
              <p className="text-sm leading-relaxed">{card.brief}</p>
              {card.sources.length > 0 && (
                <div className="mt-auto flex flex-wrap gap-2 pt-2 text-xs">
                  {card.sources.map((s) => (
                    <a key={s.url} href={s.url} target="_blank" rel="noreferrer" onPointerDown={(e) => e.stopPropagation()}
                       className="max-w-full truncate rounded-full border border-border px-2 py-0.5 text-muted hover:text-foreground">{s.label} ↗</a>
                  ))}
                </div>
              )}
            </article>
          );
        })}

        {!queue.length && (
          <div className="flex min-h-[min(58vh,520px)] flex-col items-center justify-center gap-4 rounded-3xl border border-dashed border-border p-8 text-center">
            {looking ? (
              <>
                <div className="flex gap-1.5" aria-hidden>
                  {[0, 1, 2].map((i) => <span key={i} className="size-2.5 animate-bounce rounded-full bg-accent" style={{ animationDelay: `${i * 150}ms` }} />)}
                </div>
                <p className="font-medium">The agent is reading today&apos;s trends…</p>
                <p className="text-sm text-muted">New ideas appear here in a minute or two.</p>
              </>
            ) : (
              <>
                <p className="text-lg font-medium">You&apos;re all caught up</p>
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
          <button aria-label="Skip" onClick={() => decide(top, -1)} disabled={!!leaving}
                  className="grid size-16 place-items-center rounded-full border border-border bg-surface text-2xl text-danger shadow-md transition active:scale-90">✕</button>
          <button aria-label="Make it" onClick={() => decide(top, 1)} disabled={!!leaving}
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
              <button key={r} onClick={() => { clearTimeout(skip.timer); commitSkip(skip.card, r); setSkip(null); }}
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
