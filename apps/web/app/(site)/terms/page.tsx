import Link from "next/link";

import { contactEmail, POLICIES_UPDATED } from "@/lib/site";

export const metadata = { title: "Terms of service · Content Corpus" };

// Linked from the Google and Meta consent screens. YouTube's API policies require
// the YouTube Terms of Service to be named here.
export default function TermsPage() {
  const contact = contactEmail();
  return (
    <main className="mx-auto w-full max-w-2xl px-4 pt-6 pb-16 text-sm leading-relaxed [&_h2]:mt-10 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_li]:mt-1 [&_p]:mt-3 [&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-5 [&_a]:underline">
      <h1 className="text-2xl font-semibold tracking-tight">Terms of service</h1>
      <p className="text-muted">Content Corpus · last updated {POLICIES_UPDATED}</p>

      <p>
        Content Corpus (<Link href="/">content-corpus.strophic.in</Link>) is an AI short-video studio built and run by
        Strophic. It is a private tool: only its owner can sign in. These terms apply to anyone who uses it.
      </p>

      <h2>1. What the service does</h2>
      <p>
        It suggests video ideas, writes scripts, generates short vertical videos, and publishes them to the YouTube
        channel and Instagram account you connect, at the times you schedule. It publishes only what you scheduled.
      </p>

      <h2>2. YouTube and Instagram</h2>
      <ul>
        <li>
          Content Corpus uses YouTube API Services. By connecting a YouTube channel, you agree to be bound by the{" "}
          <a href="https://www.youtube.com/t/terms">YouTube Terms of Service</a>, and Google&apos;s handling of your data
          is covered by the <a href="https://policies.google.com/privacy">Google Privacy Policy</a>.
        </li>
        <li>
          By connecting an Instagram account, you agree to Instagram&apos;s{" "}
          <a href="https://help.instagram.com/581066165581870">Terms of Use</a>.
        </li>
        <li>
          You can disconnect an account at any time from its channel page; the app then stops publishing to it and
          deletes its stored token.
        </li>
      </ul>

      <h2>3. Your content</h2>
      <ul>
        <li>You own the videos you make and publish, and you are responsible for them.</li>
        <li>
          Videos are generated with AI. Check each one before it is published, and follow YouTube&apos;s and
          Instagram&apos;s rules, including their rules on disclosing AI-generated or altered content.
        </li>
        <li>Do not use the service for anything unlawful, misleading, or that infringes anyone else&apos;s rights.</li>
      </ul>

      <h2>4. Privacy</h2>
      <p>
        The <Link href="/privacy">privacy policy</Link> explains what data the service collects, how it is used, and how
        to have it deleted.
      </p>

      <h2>5. No warranty</h2>
      <p>
        The service is provided &ldquo;as is&rdquo;, without warranties of any kind. We are not liable for losses
        caused by using it, by a video that fails to publish, or by changes to YouTube or Instagram.
      </p>

      <h2>6. Changes and ending use</h2>
      <p>
        We may change these terms; the date at the top shows the latest version. You can stop using the service at any
        time by disconnecting your accounts and asking us to delete your data.
      </p>

      {contact && (
        <>
          <h2>7. Contact</h2>
          <p><a href={`mailto:${contact}`}>{contact}</a></p>
        </>
      )}
    </main>
  );
}
