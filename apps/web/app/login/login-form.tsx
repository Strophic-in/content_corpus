"use client";

import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { authClient } from "@/lib/auth-client";

import { Spinner } from "../spinner";

type Mode = "signin" | "signup";
const field = "rounded-md border border-border bg-background px-3 py-2.5 outline-none focus:border-accent";

/** Sign in, or ask for an account: a new account waits for the owner's approval
 *  (/pending): by email and password or with Google alike. */
export function LoginForm({ googleEnabled, initialMode = "signin" }: { googleEnabled: boolean; initialMode?: Mode }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"form" | "google" | null>(null);
  const signup = mode === "signup";

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy("form");
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email")).trim();
    const password = String(form.get("password"));
    const name = String(form.get("name") ?? "").trim() || email.split("@")[0];
    const { error } = signup
      ? await authClient.signUp.email({ email, password, name })
      : await authClient.signIn.email({ email, password });
    if (error) {
      setBusy(null);
      setError(error.message ?? "Something went wrong.");
      return;
    }
    router.replace(signup ? "/pending" : "/discover");
    router.refresh();
  }

  async function onGoogle() {
    setError(null);
    setBusy("google");
    const { error } = await authClient.signIn.social({ provider: "google", callbackURL: "/discover" });
    if (error) {
      setBusy(null);
      setError(error.message ?? "Google sign-in failed.");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 border-b border-border text-sm">
        {(["signin", "signup"] as const).map((m) => (
          <button key={m} type="button" onClick={() => { setMode(m); setError(null); }}
                  className={`relative pb-2.5 font-medium transition-colors ${mode === m ? "text-foreground" : "text-muted hover:text-foreground"}`}>
            {m === "signin" ? "Sign in" : "Request access"}
            {mode === m && <motion.span layoutId="auth-tab" className="absolute inset-x-0 -bottom-px h-[2px] bg-accent" />}
          </button>
        ))}
      </div>

      <AnimatePresence initial={false}>
        {signup && (
          <motion.p key="note" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }} className="overflow-hidden text-sm text-muted">
            New accounts are let in by hand. Ask now and we&apos;ll email you when yours is approved.
          </motion.p>
        )}
      </AnimatePresence>

      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <AnimatePresence initial={false}>
          {signup && (
            <motion.label key="name" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }} className="flex flex-col gap-1 overflow-hidden text-sm">
              Your name
              <input name="name" required autoComplete="name" maxLength={80} className={field} />
            </motion.label>
          )}
        </AnimatePresence>
        <label className="flex flex-col gap-1 text-sm">
          Email
          <input name="email" type="email" required autoComplete="email" className={field} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Password
          <input name="password" type="password" required minLength={12}
                 autoComplete={signup ? "new-password" : "current-password"} className={field} />
          {signup && <span className="text-xs text-muted">At least 12 characters.</span>}
        </label>
        {error && (
          <p role="alert" className="rounded-md bg-danger-surface px-3 py-2 text-sm text-danger">{error}</p>
        )}
        <button type="submit" disabled={busy !== null}
                className="btn-primary pressable mt-1 flex items-center justify-center gap-2 rounded-md px-3 py-2.5 text-sm font-medium disabled:opacity-70">
          {busy === "form" && <Spinner />}
          {busy === "form" ? (signup ? "Sending your request…" : "Signing in…") : signup ? "Request access" : "Sign in"}
        </button>
      </form>

      {googleEnabled && (
        <>
          <div className="flex items-center gap-3 text-xs text-muted">
            <span className="h-px flex-1 bg-border" />or<span className="h-px flex-1 bg-border" />
          </div>
          <button type="button" onClick={onGoogle} disabled={busy !== null}
                  className="pressable flex items-center justify-center gap-2.5 rounded-md border border-border bg-background px-3 py-2.5 text-sm font-medium hover:border-ink/40 disabled:opacity-70">
            {busy === "google" ? <Spinner /> : (
              <svg viewBox="0 0 24 24" aria-hidden className="size-4">
                <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.7Z" />
                <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24Z" />
                <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8l4-3.1Z" />
                <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9Z" />
              </svg>
            )}
            {busy === "google" ? "Opening Google…" : signup ? "Request access with Google" : "Continue with Google"}
          </button>
        </>
      )}
    </div>
  );
}
