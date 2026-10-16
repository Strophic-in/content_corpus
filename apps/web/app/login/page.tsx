import Link from "next/link";
import { connection } from "next/server";

import "@/lib/env";

import { LoginForm } from "./login-form";

export const metadata = { title: "Sign in · Content Corpus" };

export default async function LoginPage() {
  // Per request: the Docker build has no .env, so a prerendered page would always
  // hide the Google button.
  await connection();
  const googleEnabled = Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold tracking-tight">Content Corpus</h1>
        <p className="mt-1 text-sm text-muted">Plan, render and publish short-form video.</p>
        <div className="mt-8 rounded-xl border border-border bg-surface p-6 shadow-sm">
          <LoginForm googleEnabled={googleEnabled} />
        </div>
        <p className="mt-6 flex justify-center gap-4 text-sm text-muted">
          <Link href="/" className="hover:text-foreground">About</Link>
          <Link href="/privacy" className="hover:text-foreground">Privacy</Link>
          <Link href="/terms" className="hover:text-foreground">Terms</Link>
        </p>
      </div>
    </main>
  );
}
