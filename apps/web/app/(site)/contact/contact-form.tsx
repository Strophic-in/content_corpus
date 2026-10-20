"use client";

import { AnimatePresence, motion } from "motion/react";
import { useActionState, useState } from "react";

import { sendContact, type ContactState } from "./actions";

const TOPICS = ["Early access / waitlist", "Pricing", "Partnership", "Support", "Privacy or data deletion", "Press",
  "Something else"] as const;
const field = "rounded-md border border-border bg-background px-3 py-2.5 outline-none focus:border-accent";

/** A message to the desk, sent by the site itself (kept for the owner, and emailed when
 *  the server can send mail). No mail app needed on the visitor's side. */
export function ContactForm({ to, topic }: { to: string; topic?: string }) {
  const [state, action, pending] = useActionState<ContactState, FormData>(sendContact, null);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(to);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch { /* the address is on the page */ }
  };
  return (
    <div className="border-2 border-ink bg-surface p-6 shadow-[6px_6px_0_var(--ink)]">
      <p className="kicker border-b border-border pb-3 text-muted">A letter to the desk</p>
      <AnimatePresence mode="wait" initial={false}>
        {state?.ok ? (
          <motion.div key="sent" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                      className="flex flex-col items-start gap-3 py-8">
            <span className="stamp !rotate-[-4deg]">Received</span>
            <p className="font-[family-name:var(--font-display)] text-3xl font-semibold tracking-tight">Thank you.</p>
            <p className="text-muted">Your message is on the desk.{state.to ? <> We&apos;ll reply to <strong className="text-foreground">{state.to}</strong>.</> : null}</p>
          </motion.div>
        ) : (
          <motion.form key="form" action={action} exit={{ opacity: 0, y: -10 }} className="relative mt-4 flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium">Your name</span>
                <input name="name" autoComplete="name" maxLength={120} className={field} />
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium">Your email</span>
                <input name="email" type="email" required autoComplete="email" maxLength={254} className={field} />
              </label>
            </div>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">What it&apos;s about</span>
              <select name="topic" defaultValue={TOPICS.find((t) => t === topic) ?? TOPICS[0]} className={field}>
                {TOPICS.map((t) => <option key={t}>{t}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">Message</span>
              <textarea name="message" rows={5} required maxLength={5000}
                        placeholder="Tell us about your channel and what you'd like to make." className={field} />
            </label>
            {/* Nobody sees this; a bot filling every field gives itself away. */}
            <label aria-hidden className="absolute -left-[9999px] h-px w-px overflow-hidden">
              Website <input name="website" tabIndex={-1} autoComplete="off" />
            </label>
            {state?.error && <p role="alert" className="text-sm text-danger">{state.error}</p>}
            <button type="submit" disabled={pending}
                    className="pressable btn-primary rounded-lg px-5 py-3 font-medium disabled:opacity-70">
              {pending ? "Sending…" : "Send the message"}
            </button>
            <p className="text-center text-xs text-muted">
              Or write to{" "}
              <button type="button" onClick={copy} className="font-medium text-accent hover:underline">
                {copied ? "copied ✓" : to}
              </button>
            </p>
          </motion.form>
        )}
      </AnimatePresence>
    </div>
  );
}
