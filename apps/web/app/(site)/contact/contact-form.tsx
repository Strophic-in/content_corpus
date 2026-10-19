"use client";

import { useState } from "react";

const TOPICS = ["Early access / waitlist", "Pricing", "Partnership", "Support", "Privacy or data deletion", "Press",
  "Something else"] as const;

/** Writes the message into the visitor's own email app (nothing is sent from here). */
export function ContactForm({ to }: { to: string }) {
  const [name, setName] = useState("");
  const [topic, setTopic] = useState<(typeof TOPICS)[number]>(TOPICS[0]);
  const [message, setMessage] = useState("");
  const [copied, setCopied] = useState(false);
  const href = `mailto:${to}?subject=${encodeURIComponent(`${topic}${name ? ` — ${name}` : ""}`)}`
    + `&body=${encodeURIComponent(message)}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(to);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch { /* the address is on the page */ }
  };
  return (
    <form className="flex flex-col gap-4 rounded-3xl border border-border bg-surface p-6 shadow-[var(--shadow)]"
          onSubmit={(e) => { e.preventDefault(); window.location.href = href; }}>
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="font-medium">Your name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name"
               className="rounded-xl border border-border bg-background px-3 py-2.5 outline-none focus:border-accent" />
      </label>
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="font-medium">What it&apos;s about</span>
        <select value={topic} onChange={(e) => setTopic(e.target.value as typeof topic)}
                className="rounded-xl border border-border bg-background px-3 py-2.5 outline-none focus:border-accent">
          {TOPICS.map((t) => <option key={t}>{t}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="font-medium">Message</span>
        <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5} required
                  placeholder="Tell us about your channel and what you'd like to make."
                  className="rounded-xl border border-border bg-background px-3 py-2.5 outline-none focus:border-accent" />
      </label>
      <button type="submit" className="pressable rounded-xl bg-accent px-5 py-3 font-medium text-accent-foreground">
        Write the email
      </button>
      <p className="text-center text-xs text-muted">
        Opens your email app with the message ready. Or write to{" "}
        <button type="button" onClick={copy} className="font-medium text-accent hover:underline">
          {copied ? "copied ✓" : to}
        </button>
      </p>
    </form>
  );
}
