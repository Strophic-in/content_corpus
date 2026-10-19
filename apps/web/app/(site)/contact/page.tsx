import type { Metadata } from "next";

import { CONTACT_EMAIL } from "@/lib/site";

import { Reveal } from "../reveal";
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
    <main className="relative overflow-x-clip">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="blob absolute -top-24 -right-24 size-[24rem] rounded-full bg-accent/20 blur-3xl" />
      </div>
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-12 px-4 pt-12 pb-20 lg:grid-cols-[1fr_28rem]">
        <Reveal>
          <p className="text-sm font-medium text-accent">Contact</p>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight sm:text-5xl">Let&apos;s talk.</h1>
          <p className="mt-4 max-w-xl text-lg leading-relaxed text-muted">
            Questions about Content Corpus, early access, pricing or a partnership — write to us and a person who
            builds the product will answer.
          </p>
          <a href={`mailto:${to}`}
             className="mt-8 inline-flex items-center gap-3 rounded-2xl border border-border bg-surface px-5 py-4 shadow-[var(--shadow)] transition hover:border-accent">
            <span className="grid size-10 place-items-center rounded-xl bg-accent/10 text-accent">
              <svg viewBox="0 0 24 24" aria-hidden className="size-5" fill="none" stroke="currentColor" strokeWidth={1.8}
                   strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></svg>
            </span>
            <span>
              <span className="block text-xs text-muted">Email</span>
              <span className="block font-medium">{to}</span>
            </span>
          </a>
          <ul className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
            {WAYS.map(([title, text, subject], i) => (
              <Reveal as="li" key={title} delay={i * 80}>
                <a href={`mailto:${to}?subject=${encodeURIComponent(subject)}`}
                   className="block h-full rounded-2xl border border-border bg-surface p-4 transition hover:-translate-y-0.5 hover:border-accent/50">
                  <span className="font-medium">{title}</span>
                  <span className="mt-1 block text-sm text-muted">{text}</span>
                </a>
              </Reveal>
            ))}
          </ul>
          <p className="mt-10 text-sm text-muted">Strophic · Content Corpus · India</p>
        </Reveal>
        <Reveal delay={120}>
          <ContactForm to={to} />
        </Reveal>
      </div>
    </main>
  );
}
