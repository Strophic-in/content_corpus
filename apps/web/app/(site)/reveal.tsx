"use client";

import { useEffect, useRef, useState } from "react";

/** Fades and lifts its children in the first time they scroll into view (instantly
 *  with reduced motion — the CSS turns the transition off). */
export function Reveal({ children, delay = 0, className = "", as: Tag = "div" }: {
  children: React.ReactNode; delay?: number; className?: string; as?: "div" | "li" | "section";
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { setShown(true); io.disconnect(); }
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <Tag ref={ref as never} style={{ transitionDelay: `${delay}ms` }}
         className={`reveal ${shown ? "reveal-in" : ""} ${className}`}>
      {children}
    </Tag>
  );
}
