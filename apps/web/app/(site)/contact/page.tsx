import type { Metadata } from "next";

import { CONTACT_EMAIL } from "@/lib/site";

import { Headline, In } from "../motion-bits";
import { ContactForm } from "./contact-form";

export const metadata: Metadata = {
  title: "Contact",
  description: "Write to the Content Corpus team about early access, pricing, partnerships, support or privacy.",
  alternates: { canonical: "/contact" },
};

const WAYS = [
  ["Early access", "Join the waitlist for the private beta, or ask about Base, Pro and Elite.", "Content Corpus waitlist"],
  ["Partnerships", "Newsrooms, agencies and creators who want to make Shorts and Reels at scale.", "Partnership"],
  ["Privacy & data", "Questions about your data, or a request to delete it.", "Privacy or data deletion"],
] as const;

export default function ContactPage() {
  const to = CONTACT_EMAIL;
  return (
    <main className="overflow-x-clip">
      <div className="border-y border-ink/80">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
          <span className="flex items-center gap-2 text-accent"><span className="on-air-dot" /> The newsdesk</span>
          <span className="ml-auto">Letters · Tips · Partnerships</span>
        </div>
      </div>
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-14 px-4 pt-14 pb-24 lg:grid-cols-[1fr_28rem]">
        <div>
          <In><p className="kicker text-accent">Contact</p></In>
          <Headline words={["Write", "to", "the", "desk."]} accent={[3]}
                    className="mt-3 text-5xl leading-[1] font-semibold tracking-tight sm:text-7xl" />
          <In delay={0.4}>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted">
              Questions about Content Corpus, early access, pricing or a partnership — a person who builds the product
              reads every message and answers.
            </p>
            <a href={`mailto:${to}`} className="group mt-8 inline-flex items-baseline gap-3 border-b-2 border-ink pb-1">
              <span className="kicker text-muted">Email</span>
              <span className="font-[family-name:var(--font-display)] text-2xl font-semibold tracking-tight transition-colors group-hover:text-accent sm:text-3xl">{to}</span>
            </a>
          </In>
          <ul className="mt-12 grid grid-cols-1 border-t-2 border-ink sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
            {WAYS.map(([title, text, subject], i) => (
              <li key={title} className={`border-border ${i ? "border-t sm:border-t-0 sm:border-l lg:border-t lg:border-l-0 xl:border-t-0 xl:border-l" : ""}`}>
                <In delay={0.1 + i * 0.08}>
                  <a href={`mailto:${to}?subject=${encodeURIComponent(subject)}`}
                     className="group block h-full p-5 transition-colors hover:bg-surface">
                    <span className="kicker text-muted">0{i + 1}</span>
                    <span className="mt-1 block font-[family-name:var(--font-display)] text-xl font-semibold">{title}</span>
                    <span className="mt-1 block text-sm text-muted">{text}</span>
                    <span className="mt-3 inline-block text-sm text-accent transition-transform group-hover:translate-x-1">Write →</span>
                  </a>
                </In>
              </li>
            ))}
          </ul>
          <p className="kicker mt-10 text-muted">Strophic · Content Corpus · India</p>
        </div>
        <In delay={0.2}><ContactForm to={to} /></In>
      </div>
    </main>
  );
}
