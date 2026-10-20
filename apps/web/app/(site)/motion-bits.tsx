"use client";

import { AnimatePresence, animate, motion, useInView, useReducedMotion, useScroll, useTransform } from "motion/react";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

const EASE = [0.2, 0.8, 0.2, 1] as const;

/** Rises in once as it scrolls into view. */
export function In({ children, delay = 0, className = "", y = 18 }: {
  children: React.ReactNode; delay?: number; className?: string; y?: number;
}) {
  return (
    <motion.div className={className} initial={{ opacity: 0, y }} whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "0px 0px -10% 0px" }}
                transition={{ duration: 0.7, delay, ease: EASE }}>
      {children}
    </motion.div>
  );
}

/** A headline set word by word, each rising from under a baseline (a printing press,
 *  not a fade). `accent` words are set in the signal red, italic. */
export function Headline({ words, accent = [], className = "" }: {
  words: string[]; accent?: number[]; className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <h1 className={className}>
      {words.map((w, i) => (
        <span key={i} className="inline-block overflow-hidden pb-[0.08em] align-bottom">
          <motion.span className={`inline-block ${accent.includes(i) ? "text-accent italic" : ""}`}
                       initial={reduce ? false : { y: "105%" }} animate={{ y: "0%" }}
                       transition={{ duration: 0.8, delay: 0.15 + i * 0.07, ease: EASE }}>
            {w}
          </motion.span>
          {i < words.length - 1 && " "}
        </span>
      ))}
    </h1>
  );
}

/** The broadcast clock: hours, minutes, seconds and frames (25 a second), Indian time. */
export function Timecode({ className = "" }: { className?: string }) {
  const [t, setT] = useState("--:--:--:--");
  useEffect(() => {
    const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit",
                                                   second: "2-digit", hour12: false });
    let raf = 0;
    const tick = () => {
      const now = new Date();
      const frame = String(Math.floor(now.getMilliseconds() / 40)).padStart(2, "0");
      setT(`${fmt.format(now)}:${frame}`);
      raf = window.setTimeout(tick, 80) as unknown as number;
    };
    tick();
    return () => clearTimeout(raf);
  }, []);
  return <span className={`tabular-nums ${className}`} suppressHydrationWarning>{t}</span>;
}

/** A number that counts up the first time it is seen. */
export function CountUp({ to, className = "" }: { to: number; className?: string }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const seen = useInView(ref, { once: true, margin: "0px 0px -15% 0px" });
  const reduce = useReducedMotion();
  useEffect(() => {
    if (!seen || !ref.current) return;
    if (reduce) { ref.current.textContent = String(to); return; }
    const c = animate(0, to, { duration: 1.4, ease: EASE, onUpdate: (v) => {
      if (ref.current) ref.current.textContent = String(Math.round(v));
    } });
    return () => c.stop();
  }, [seen, to, reduce]);
  return <span ref={ref} className={`tabular-nums ${className}`}>0</span>;
}

/** A phone on the monitor wall, cycling through screens of the app. */
export function Monitor({ shots, every = 3800, className = "" }: {
  shots: { src: string; label: string }[]; every?: number; className?: string;
}) {
  const [at, setAt] = useState(0);
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce) return;
    const id = setInterval(() => setAt((n) => (n + 1) % shots.length), every);
    return () => clearInterval(id);
  }, [shots.length, every, reduce]);
  const s = shots[at];
  return (
    <div className={`monitor ${className}`}>
      <div className="relative overflow-hidden rounded-[1.5rem] bg-black">
        {/* Every screen stacked (the first sets the height); the live one fades and
            settles in over the last, so two never show half-and-half. */}
        {shots.map((sh, i) => (
          <motion.div key={sh.src} className={i === 0 ? "relative" : "absolute inset-0"}
                      initial={false} animate={{ opacity: i === at ? 1 : 0, scale: i === at ? 1 : 1.04,
                                                 zIndex: i === at ? 2 : 1 }}
                      transition={{ opacity: { duration: 0.7, ease: EASE }, scale: { duration: 1.2, ease: EASE } }}>
            <Image src={sh.src} alt={sh.label} width={780} height={1688} priority={i === 0}
                   className="h-auto w-full" sizes="(min-width: 1024px) 320px, 70vw" />
          </motion.div>
        ))}
        <div className="pointer-events-none absolute inset-x-0 top-0 flex items-center justify-between px-3 pt-2.5 font-mono text-[10px] text-white/90 [text-shadow:0_1px_2px_rgb(0_0_0/.6)]">
          <span className="flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-[#ff3b30]" /> REC</span>
          <Timecode />
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between font-mono text-[11px] uppercase tracking-widest text-muted">
        <span>CAM {at + 1}</span>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span key={s.label} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
                       transition={{ duration: 0.3 }}>{s.label}</motion.span>
        </AnimatePresence>
      </div>
    </div>
  );
}

/** The running order: steps down a timeline, and a red playhead that runs down it as
 *  the page scrolls. */
export function Rundown({ steps }: { steps: { slug: string; title: string; text: string; time: string }[] }) {
  const ref = useRef<HTMLOListElement | null>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 75%", "end 45%"] });
  const scaleY = useTransform(scrollYProgress, [0, 1], [0, 1]);
  return (
    <ol ref={ref} className="relative mt-12 flex flex-col">
      <span aria-hidden className="absolute top-0 bottom-0 left-[4.6rem] w-px bg-border sm:left-[6.2rem]" />
      <motion.span aria-hidden style={{ scaleY }}
                   className="absolute top-0 bottom-0 left-[4.6rem] w-[3px] origin-top -translate-x-px bg-accent sm:left-[6.2rem]" />
      {steps.map((s, i) => (
        <li key={s.slug} className="relative grid grid-cols-[4.6rem_1fr] gap-6 py-6 sm:grid-cols-[6.2rem_1fr] sm:gap-10">
          <span className="pt-1 font-mono text-xs text-muted tabular-nums">{s.time}</span>
          <In delay={i * 0.05}>
            <span aria-hidden className="absolute top-[1.85rem] left-[4.6rem] size-3 -translate-x-1/2 rounded-full border-2 border-accent bg-background sm:left-[6.2rem]" />
            <p className="kicker text-accent">{s.slug}</p>
            <h3 className="mt-1 font-[family-name:var(--font-display)] text-2xl font-semibold tracking-tight sm:text-3xl">{s.title}</h3>
            <p className="mt-2 max-w-2xl leading-relaxed text-muted">{s.text}</p>
          </In>
        </li>
      ))}
    </ol>
  );
}

/** One question that opens smoothly. */
export function Faq({ q, a, i }: { q: string; a: string; i: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-border">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
              className="flex w-full items-start gap-5 py-5 text-left">
        <span className="kicker pt-1.5 text-muted">{String(i + 1).padStart(2, "0")}</span>
        <span className="flex-1 font-[family-name:var(--font-display)] text-xl font-medium tracking-tight sm:text-2xl">{q}</span>
        <motion.span aria-hidden animate={{ rotate: open ? 45 : 0 }} transition={{ duration: 0.25 }}
                     className="mt-1 grid size-7 shrink-0 place-items-center rounded-full border border-border text-lg leading-none">+</motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div key="a" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.35, ease: EASE }} className="overflow-hidden">
            <p className="pb-6 pl-11 leading-relaxed text-muted sm:pr-12">{a}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
