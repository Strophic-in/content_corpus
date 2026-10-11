"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { authClient } from "@/lib/auth-client";

type Mode = "signin" | "signup";

export function LoginForm({ googleEnabled }: { googleEnabled: boolean }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email"));
    const password = String(form.get("password"));
    const { error } =
      mode === "signin"
        ? await authClient.signIn.email({ email, password })
        : await authClient.signUp.email({ email, password, name: email.split("@")[0] });
    setBusy(false);
    if (error) {
      setError(error.message ?? "Something went wrong.");
      return;
    }
    router.replace("/dashboard");
    router.refresh();
  }

  async function onGoogle() {
    setError(null);
    setBusy(true);
    const { error } = await authClient.signIn.social({ provider: "google", callbackURL: "/dashboard" });
    if (error) {
      setBusy(false);
      setError(error.message ?? "Google sign-in failed.");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Email
          <input
            name="email"
            type="email"
            required
            autoComplete="email"
            className="rounded-md border border-border bg-background px-3 py-2 outline-none focus:border-accent"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Password
          <input
            name="password"
            type="password"
            required
            minLength={12}
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            className="rounded-md border border-border bg-background px-3 py-2 outline-none focus:border-accent"
          />
        </label>
        {error && (
          <p role="alert" className="rounded-md bg-danger-surface px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="mt-1 rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-foreground disabled:opacity-60"
        >
          {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}
        </button>
      </form>

      {googleEnabled && (
        <>
          <div className="flex items-center gap-3 text-xs text-muted">
            <span className="h-px flex-1 bg-border" />
            or
            <span className="h-px flex-1 bg-border" />
          </div>
          <button
            type="button"
            onClick={onGoogle}
            disabled={busy}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium disabled:opacity-60"
          >
            Continue with Google
          </button>
        </>
      )}

      <button
        type="button"
        onClick={() => {
          setMode(mode === "signin" ? "signup" : "signin");
          setError(null);
        }}
        className="text-sm text-muted underline-offset-4 hover:underline"
      >
        {mode === "signin" ? "First time here? Create the owner account" : "Have an account? Sign in"}
      </button>
    </div>
  );
}
