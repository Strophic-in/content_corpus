import { headers } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { auth } from "@/lib/auth";
import { membership } from "@/lib/session";

import { SignOutButton } from "../(app)/sign-out-button";

export const metadata = { title: "Waiting for approval · Content Corpus" };

// Where an account that isn't active lands: signed in, but not let in yet. Outside
// the (app) layout, whose requireUser() would send it straight back here.
export default async function PendingPage() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/login");
  const m = await membership(session.user.id);
  if (m?.status === "active") redirect("/discover");
  const suspended = m?.status === "suspended";
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-md">
        <p className="kicker flex items-center gap-2 border-y border-ink/80 py-1.5 text-accent">
          <span className="on-air-dot" /> {suspended ? "Off air" : "Stand by"}
          <span className="ml-auto text-muted">Content Corpus</span>
        </p>
        <h1 className="mt-6 text-4xl font-semibold tracking-tight">
          {suspended ? "This account is paused." : "You're on the list."}
        </h1>
        <p className="mt-3 leading-relaxed text-muted">
          {suspended
            ? "It can't make or post videos right now. If you think this is a mistake, write to us."
            : "New accounts are let in by hand. We've been told about your request, and we'll email you the moment "
              + "yours is approved. Then this page lets you straight in."}
        </p>
        <div className="mt-6 border-t border-border pt-4 text-sm text-muted">
          <p>Signed in as <span className="font-medium text-foreground">{session.user.email}</span>.</p>
          <div className="mt-4 flex items-center gap-5">
            <SignOutButton />
            <Link href="/contact" className="text-accent hover:underline">Write to us</Link>
            <Link href="/" className="hover:text-foreground">About Content Corpus</Link>
          </div>
        </div>
      </div>
    </main>
  );
}
