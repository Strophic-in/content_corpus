import { getSessionCookie } from "better-auth/cookies";
import { headers } from "next/headers";
import Link from "next/link";

import { contactEmail } from "@/lib/site";

// The public face: homepage, privacy policy and terms, readable without signing in
// (Google's verification rejects a homepage behind a login). Rendered per request
// so the contact address comes from the server's environment, not the build's.
export default async function SiteLayout({ children }: LayoutProps<"/">) {
  const signedIn = Boolean(getSessionCookie(await headers()));
  const contact = contactEmail();
  return (
    <div className="flex flex-1 flex-col pt-[env(safe-area-inset-top)]">
      <header className="mx-auto flex w-full max-w-4xl items-center gap-3 px-4 py-4">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          {/* eslint-disable-next-line @next/next/no-img-element -- drawn by /icons, already sized */}
          <img src="/icons/192" alt="" width={28} height={28} className="rounded-lg" />
          Content Corpus
        </Link>
        <nav className="ml-auto flex items-center gap-4 text-sm">
          <Link href="/privacy" className="hidden text-muted hover:text-foreground sm:inline">Privacy</Link>
          <Link href="/terms" className="hidden text-muted hover:text-foreground sm:inline">Terms</Link>
          <Link href={signedIn ? "/discover" : "/login"}
                className="rounded-lg bg-accent px-3 py-1.5 font-medium text-accent-foreground">
            {signedIn ? "Open app" : "Sign in"}
          </Link>
        </nav>
      </header>
      <div className="flex-1">{children}</div>
      <footer className="border-t border-border pb-[env(safe-area-inset-bottom)]">
        <div className="mx-auto flex w-full max-w-4xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-6 text-sm text-muted">
          <span>© 2026 Strophic · Content Corpus</span>
          <Link href="/privacy" className="hover:text-foreground">Privacy policy</Link>
          <Link href="/terms" className="hover:text-foreground">Terms of service</Link>
          {contact && <a href={`mailto:${contact}`} className="hover:text-foreground">{contact}</a>}
        </div>
      </footer>
    </div>
  );
}
