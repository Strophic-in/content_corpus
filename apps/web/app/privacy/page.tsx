import Link from "next/link";

import "@/lib/env";

export const metadata = { title: "Privacy policy · Content Corpus" };

// Public (no sign-in): Google and Meta link to this page from their consent screens.
export default function PrivacyPage() {
  const contact = process.env.PRIVACY_CONTACT_EMAIL;
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-12 text-sm leading-relaxed [&_h2]:mt-8 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_li]:mt-1 [&_ul]:list-disc [&_ul]:pl-5">
      <h1 className="text-2xl font-semibold tracking-tight">Privacy policy</h1>
      <p className="mt-1 text-muted">Content Corpus · last updated 16 October 2026</p>

      <p className="mt-6">
        Content Corpus is a private tool its owner uses to plan, make and publish short videos to their own YouTube
        and Instagram accounts. It is not offered to the public; only the owner can sign in.
      </p>

      <h2>What we access</h2>
      <ul>
        <li>Your sign-in email address, to identify the owner's account.</li>
        <li>
          When you connect YouTube: your channel's ID, name and picture, and permission to upload videos
          (<code>youtube.upload</code>) and read your channel (<code>youtube.readonly</code>).
        </li>
        <li>
          When you connect Instagram: your professional account's ID, username and picture, and permission to publish
          media to it.
        </li>
      </ul>

      <h2>How it is used</h2>
      <ul>
        <li>Only to upload and publish the videos you create and schedule in Content Corpus, to the accounts you connected.</li>
        <li>We do not read, analyse or modify any other content in your accounts.</li>
        <li>We do not sell, share or transfer your data to anyone, and do not use it for advertising or to train AI models.</li>
      </ul>
      <p className="mt-3">
        Content Corpus's use of information received from Google APIs adheres to the{" "}
        <a className="underline" href="https://developers.google.com/terms/api-services-user-data-policy">
          Google API Services User Data Policy
        </a>
        , including the Limited Use requirements.
      </p>

      <h2>Storage and security</h2>
      <ul>
        <li>Access tokens are encrypted (AES-256-GCM) before they are stored, and are only decrypted to publish.</li>
        <li>Data is kept in the owner's own database and storage (Oracle Cloud and Cloudflare R2).</li>
      </ul>

      <h2>Your control</h2>
      <ul>
        <li>Disconnect an account at any time from its channel page; its stored token is deleted.</li>
        <li>
          You can also revoke access from your{" "}
          <a className="underline" href="https://myaccount.google.com/permissions">Google account permissions</a> or
          Instagram's Apps and websites settings.
        </li>
        {contact && <li>To ask about or delete your data, email <a className="underline" href={`mailto:${contact}`}>{contact}</a>.</li>}
      </ul>

      <p className="mt-10 text-muted"><Link href="/terms" className="underline">Terms of service</Link></p>
    </main>
  );
}
