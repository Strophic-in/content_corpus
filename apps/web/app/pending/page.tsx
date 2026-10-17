import { headers } from "next/headers";
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
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface p-6 text-sm shadow-sm">
        <h1 className="text-xl font-semibold tracking-tight">
          {suspended ? "This account is suspended" : "Thanks for signing up"}
        </h1>
        <p className="mt-2 text-muted">
          {suspended
            ? "It can't make or post videos right now. Contact the owner if you think this is a mistake."
            : "Content Corpus lets new accounts in by hand. The owner has been told — you'll get an email when " +
              "yours is approved, and this page will let you in."}
        </p>
        <p className="mt-4 text-muted">Signed in as {session.user.email}.</p>
        <div className="mt-4"><SignOutButton /></div>
      </div>
    </main>
  );
}
