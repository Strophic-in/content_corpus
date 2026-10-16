import Link from "next/link";

export const metadata = { title: "Terms of service · Content Corpus" };

// Public (no sign-in): linked from the Google and Meta consent screens.
export default function TermsPage() {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-12 text-sm leading-relaxed [&_li]:mt-1 [&_ul]:mt-4 [&_ul]:list-disc [&_ul]:pl-5">
      <h1 className="text-2xl font-semibold tracking-tight">Terms of service</h1>
      <p className="mt-1 text-muted">Content Corpus · last updated 16 October 2026</p>
      <p className="mt-6">
        Content Corpus is a private tool for its owner. By connecting an account you allow it to publish the videos
        you create and schedule here to that account, and nothing else.
      </p>
      <ul>
        <li>You are responsible for the content you publish and for following YouTube's and Instagram's rules.</li>
        <li>You can disconnect your accounts at any time; the tool then stops publishing to them.</li>
        <li>The tool is provided as is, without warranties.</li>
      </ul>
      <p className="mt-10 text-muted"><Link href="/privacy" className="underline">Privacy policy</Link></p>
    </main>
  );
}
