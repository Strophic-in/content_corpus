import { getSessionCookie } from "better-auth/cookies";
import type { Metadata } from "next";
import { headers } from "next/headers";
import Link from "next/link";

import { contactEmail, siteUrl } from "@/lib/site";

// The public face: homepage, privacy policy and terms, readable without signing in
// (Google's verification rejects a homepage behind a login). Rendered per request
// so the contact address comes from the server's environment, not the build's.

export async function generateMetadata(): Promise<Metadata> {
  const site = siteUrl();
  return {
    ...(site ? { metadataBase: new URL(site) } : {}),
    title: { default: "Content Corpus", template: "%s · Content Corpus" },
    robots: { index: true, follow: true },
  };
}

const SECTIONS = [["#rundown", "How it works"], ["#features", "Features"], ["#pricing", "Pricing"], ["#faq", "FAQ"]] as const;
const SECTION_HREF = (h: string) => `/${h}`;

export default async function SiteLayout({ children }: LayoutProps<"/">) {
  const signedIn = Boolean(getSessionCookie(await headers()));
  const contact = contactEmail();
  const site = siteUrl();
  return (
    <div className="flex flex-1 flex-col pt-[env(safe-area-inset-top)]">
      <header className="sticky top-0 z-30 border-b border-transparent bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3">
          <Link href="/" className="flex items-center gap-2.5">
            {/* eslint-disable-next-line @next/next/no-img-element -- drawn by /icons, already sized */}
            <img src="/icons/192" alt="" width={28} height={28} className="rounded-md" />
            <span className="font-[family-name:var(--font-display)] text-xl font-semibold tracking-tight">Content Corpus</span>
          </Link>
          <nav aria-label="Sections" className="ml-6 hidden items-center gap-5 text-sm text-muted md:flex">
            {SECTIONS.map(([href, label]) => (
              <Link key={href} href={SECTION_HREF(href)} className="hover:text-foreground">{label}</Link>
            ))}
            <Link href="/contact" className="hover:text-foreground">Contact</Link>
          </nav>
          <nav className="ml-auto flex items-center gap-3 text-sm">
            <Link href="/contact" className="text-muted hover:text-foreground md:hidden">Contact</Link>
            <Link href={signedIn ? "/discover" : "/login"}
                  className="pressable btn-primary rounded-md px-3.5 py-1.5 font-medium">
              {signedIn ? "Open app" : "Sign in"}
            </Link>
          </nav>
        </div>
      </header>
      <div className="flex-1">{children}</div>
      <footer className="border-t-2 border-ink pb-[env(safe-area-inset-bottom)]">
        <div className="mx-auto grid w-full max-w-6xl grid-cols-2 gap-8 px-4 py-10 text-sm sm:grid-cols-4">
          <div className="col-span-2">
            <p className="font-[family-name:var(--font-display)] text-3xl font-semibold tracking-tight">Content Corpus</p>
            <p className="mt-2 max-w-sm text-muted">The AI studio that turns today&apos;s news into finished YouTube Shorts
              and Instagram Reels. Built by Strophic.</p>
          </div>
          <div className="flex flex-col gap-2 text-muted">
            <p className="font-medium text-foreground">Product</p>
            {SECTIONS.map(([href, label]) => <Link key={href} href={SECTION_HREF(href)} className="hover:text-foreground">{label}</Link>)}
          </div>
          <div className="flex flex-col gap-2 text-muted">
            <p className="font-medium text-foreground">Company</p>
            <Link href="/contact" className="hover:text-foreground">Contact</Link>
            <Link href={`${site}/privacy`} className="hover:text-foreground">Privacy policy</Link>
            <Link href={`${site}/terms`} className="hover:text-foreground">Terms of service</Link>
            <a href={`mailto:${contact}`} className="break-all hover:text-foreground">{contact}</a>
          </div>
        </div>
        <p className="mx-auto w-full max-w-6xl px-4 pb-8 text-xs text-muted">© 2026 Strophic · Content Corpus</p>
      </footer>
    </div>
  );
}
