import Link from "next/link";

import { siteUrl } from "@/lib/site";

export const metadata = {
  title: "Content Corpus — AI short-video studio by Strophic",
  description: "Content Corpus finds fresh video ideas, makes narrated vertical videos with AI, and publishes them to "
    + "YouTube Shorts and Instagram Reels on a schedule.",
};

const STEPS = [
  ["Discover", "Every day it reads public trend feeds — Wikipedia's most-read articles, Google Trends and science "
    + "news — and suggests video ideas. Swipe right to keep one, left to skip it."],
  ["Write", "An AI model writes the script and shot list for a kept idea, following prompts the owner edits in the "
    + "app's prompt library."],
  ["Make", "Each shot is generated as vertical (9:16) video on rented GPUs, then narrated, captioned and joined into "
    + "one finished Short."],
  ["Publish", "At the date and time the owner picks, the finished video is uploaded to their connected YouTube "
    + "channel or Instagram account."],
] as const;

const GOOGLE_ACCESS = [
  ["Sign in with Google", "openid, email, profile",
    "Your name, email address and profile picture, to sign you in. Only the owner's email address is allowed."],
  ["Upload YouTube videos", "youtube.upload",
    "To upload the videos you made and scheduled in Content Corpus to your channel, at the time you chose."],
  ["View your YouTube account", "youtube.readonly",
    "To read your channel's ID, name, handle and picture once, when you connect it, so the app shows which channel "
    + "it will publish to."],
] as const;

// The homepage Google's OAuth verification reviews: public, names the app as the
// consent screen does, says what it is for and why it asks for each permission.
export default function HomePage() {
  const site = siteUrl();
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-16 px-4 pt-10 pb-20">
      <section className="max-w-2xl">
        <p className="text-sm font-medium text-accent">An AI short-video studio by Strophic</p>
        <h1 className="mt-2 text-4xl font-semibold tracking-tight sm:text-5xl">Content Corpus</h1>
        <p className="mt-4 text-lg leading-relaxed">
          Content Corpus finds fresh ideas for short videos, turns them into narrated, captioned vertical videos with
          AI, and publishes them to <strong>YouTube Shorts</strong> and <strong>Instagram Reels</strong> on a schedule.
        </p>
        <p className="mt-4 leading-relaxed text-muted">
          It is a private tool that Strophic builds and runs for its own channels. It is not open to the public: only
          the owner can sign in, and sign-ups are closed.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/login" className="rounded-lg bg-accent px-4 py-2 font-medium text-accent-foreground">Sign in</Link>
          <Link href={`${site}/privacy`} className="rounded-lg border border-border bg-surface px-4 py-2 font-medium">
            Privacy policy
          </Link>
        </div>
      </section>

      <section>
        <h2 className="text-xl font-semibold tracking-tight">How it works</h2>
        <ol className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {STEPS.map(([title, text], i) => (
            <li key={title} className="rounded-2xl border border-border bg-surface p-5">
              <p className="text-sm text-muted">Step {i + 1}</p>
              <h3 className="mt-1 font-medium">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="max-w-3xl">
        <h2 className="text-xl font-semibold tracking-tight">Why it asks for access to your Google account</h2>
        <p className="mt-2 leading-relaxed text-muted">
          Content Corpus uses Google Sign-In and the YouTube Data API (YouTube API Services). It asks only for what
          signing in and publishing need:
        </p>
        <dl className="mt-4 divide-y divide-border rounded-2xl border border-border bg-surface">
          {GOOGLE_ACCESS.map(([what, scope, why]) => (
            <div key={what} className="grid grid-cols-1 gap-1 p-5 sm:grid-cols-[14rem_1fr] sm:gap-6">
              <dt>
                <span className="font-medium">{what}</span>
                <code className="mt-1 block text-xs text-muted">{scope}</code>
              </dt>
              <dd className="text-sm leading-relaxed text-muted">{why}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-sm leading-relaxed text-muted">
          It never reads, changes or deletes your existing videos, comments, playlists or analytics, and it never
          publishes anything you did not schedule. Disconnect your channel at any time in the app, or remove the
          app&apos;s access in your{" "}
          <a className="underline" href="https://security.google.com/settings/security/permissions">Google Account</a>.
        </p>
      </section>

      <section className="max-w-3xl">
        <h2 className="text-xl font-semibold tracking-tight">Instagram</h2>
        <p className="mt-2 leading-relaxed text-muted">
          With Instagram Login, Content Corpus reads your professional account&apos;s ID, username, name and profile
          picture, and publishes the Reels you schedule to it. Nothing else in your account is read or changed.
        </p>
      </section>

      <section className="max-w-3xl rounded-2xl border border-border bg-surface p-6">
        <h2 className="text-xl font-semibold tracking-tight">Your data</h2>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm leading-relaxed text-muted">
          <li>Connection tokens are encrypted before they are stored, and deleted when you disconnect.</li>
          <li>Nothing is sold, shared for advertising, or given to anyone else.</li>
          <li>Data from your Google and Instagram accounts is never sent to AI models or used to train them.</li>
        </ul>
        <p className="mt-4 text-sm">
          The <Link href={`${site}/privacy`} className="underline">privacy policy</Link> explains exactly what is stored, for how
          long, and how to delete it. Use is subject to the <Link href={`${site}/terms`} className="underline">terms of service</Link>.
        </p>
      </section>
    </main>
  );
}
