import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { CONTACT_EMAIL, siteUrl } from "@/lib/site";

import { Reveal } from "./reveal";
import { Showcase } from "./showcase";

const TITLE = "Content Corpus — AI studio for YouTube Shorts & Instagram Reels";
const DESCRIPTION = "Turn today's trending news into finished Shorts and Reels: Content Corpus finds the stories your "
  + "audience will tap, collects real logos, photos and footage, writes and voices the script, renders the video and "
  + "posts it on schedule.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  keywords: ["AI video generator", "YouTube Shorts automation", "Instagram Reels automation", "faceless YouTube channel",
             "news shorts", "AI script writer", "AI voiceover Hindi", "short video scheduler", "content automation"],
  alternates: { canonical: "/" },
  openGraph: { type: "website", title: TITLE, description: DESCRIPTION, siteName: "Content Corpus", url: "/" },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION },
};

// ── what it does ─────────────────────────────────────────────────────────────

const STEPS = [
  { title: "Discover", text: "Every morning it reads news sites, trend feeds and communities for each of your categories. "
      + "Jev, our decision model, ranks the stories by how many of your viewers would stop and tap — and you swipe "
      + "to keep the ones you want." },
  { title: "Collect", text: "Before a word is written it gathers the real thing: the logos of the companies named, photos "
      + "of the people and places, maps and flags, a card of each report, the reports' own photos and video — and "
      + "anything you add." },
  { title: "Write", text: "A script written from several outlets' reports, checked against them, in the format that suits "
      + "the story: a narrated explainer, a before/after, a countdown, footage with captions and music." },
  { title: "Make", text: "Real footage and pictures first; AI-generated shots only for what nothing real can show. Then "
      + "the voice, captions in the style that fits, music and a scroll-stopping cover." },
  { title: "Publish", text: "Title, caption with sources, hashtags, a first comment and the cover — posted to YouTube "
      + "Shorts and Instagram Reels at the time you chose. Or let autopilot do every step." },
] as const;

type Icon = "radar" | "swipe" | "photo" | "script" | "film" | "mic" | "type" | "layers" | "auto" | "calendar"
  | "megaphone" | "rupee";
const FEATURES: { icon: Icon; title: string; text: string }[] = [
  { icon: "radar", title: "Trend radar by category", text: "Science, crime, finance, sport, India, world… each category has its own sources and its own number of ideas a day." },
  { icon: "swipe", title: "Swipe to decide", text: "Ideas arrive as cards with the story, why it's trending, its media and what it cost. Right to keep, left to skip." },
  { icon: "photo", title: "Real assets, credited", text: "Logos, photos, maps, flags, report cards and news footage collected for every story — credited on screen and in the caption." },
  { icon: "script", title: "Sourced scripts", text: "Written from several outlets' reports and checked against them. Hooks that open a curiosity gap the video truly closes." },
  { icon: "film", title: "AI video where it counts", text: "Cinematic generated shots for what footage can't show, and image-to-video that brings a real photo to life." },
  { icon: "mic", title: "44 voices, English & Hindi", text: "Free natural narrators and expressive AI voices whose tone follows the script — urgent, calm or respectful." },
  { icon: "type", title: "Caption & cover styles", text: "Twelve caption styles and thirteen cover layouts, chosen per video to fit the story and the title." },
  { icon: "layers", title: "22 formats", text: "Explainers, before/after, countdowns, myth vs fact, split screens, footage with captions and music, carousels, picture cards." },
  { icon: "auto", title: "Autopilot", text: "Script, approval, render and posting without a single click — or stop at any step to review it yourself." },
  { icon: "calendar", title: "Calendar & library", text: "Plan the month, drag a video to another day, and see every video's stage, cost and views in one table." },
  { icon: "megaphone", title: "Ready to post", text: "A gripping, accurate title, a caption with its sources, hashtags, a first comment that adds context, and the cover." },
  { icon: "rupee", title: "Every rupee shown", text: "The cost of each idea and each video — writing, voice, GPU minutes — so you always know what a reel costs." },
];

const STATS = [["22", "formats"], ["25", "caption & cover styles"], ["44", "voices in English & Hindi"],
  ["2", "platforms: Shorts & Reels"]] as const;

const PLANS = [
  { name: "Base", who: "For one channel getting started", points: ["One channel, a few categories", "Daily ideas ranked for your audience",
      "Real assets collected for every story", "Free narrator voices", "Scheduling to YouTube Shorts & Instagram Reels"] },
  { name: "Pro", who: "For creators posting every day", featured: true, points: ["Everything in Base", "More channels and a higher monthly volume",
      "AI voices in English & Hindi", "Autopilot from idea to posted video", "Every format, caption style and cover layout"] },
  { name: "Elite", who: "For newsrooms and studios", points: ["Everything in Pro", "The most channels and the highest volume",
      "Your own formats and looks", "Detailed cost reports per channel", "First access to new formats and features"] },
] as const;

const FAQ = [
  ["What is Content Corpus?", "An AI studio for short vertical video. It finds the stories worth covering, collects real pictures and footage, writes and voices the script, renders the video and publishes it to YouTube Shorts and Instagram Reels on your schedule."],
  ["Do I have to post everything it makes?", "No. In manual mode nothing happens without you: you keep the ideas you like, read and approve each script, and choose when it goes out. Autopilot is an option per video or per channel."],
  ["Where do the pictures and footage come from?", "From the story itself: logos, photos, maps and flags from Wikipedia and Wikimedia Commons, the news reports' own photos and video, a card of each report, and anything you upload or link. Each is credited on screen and in the caption. AI-generated shots are used only for what nothing real can show."],
  ["Does it work in Hindi?", "Yes. Scripts can be written in Hindi and read by AI voices that speak natural Hindi; English uses free, natural narrators."],
  ["Can every video have narration — or none?", "Both. Narrated explainers suit stories that need explaining; for stories the pictures tell by themselves there's a format with captions and background music only. Jev picks the format that fits each story."],
  ["How much does a video cost to make?", "You see the exact cost of every idea and every video in the app — writing, voice and GPU minutes. Shots made from real pictures cost nothing to render, so real assets keep videos cheap."],
  ["Is my YouTube and Instagram account safe?", "It asks only for what signing in and publishing need, stores connection tokens encrypted, never reads or changes your other videos, and you can disconnect at any time. Details are below and in the privacy policy."],
  ["When can I sign up, and what will it cost?", "Content Corpus is in private beta. Base, Pro and Elite plans are coming soon — join the waitlist and we'll write to you when they open."],
] as const;

const GOOGLE_ACCESS = [
  ["Sign in with Google", "openid, email, profile",
    "Your name, email address and profile picture, to sign you in."],
  ["Upload YouTube videos", "youtube.upload",
    "To upload the videos you made and scheduled in Content Corpus to your channel, at the time you chose."],
  ["View your YouTube account", "youtube.readonly",
    "To read your channel's ID, name, handle and picture once, when you connect it, so the app shows which channel "
    + "it will publish to."],
] as const;

function FeatureIcon({ name }: { name: Icon }) {
  const d: Record<Icon, React.ReactNode> = {
    radar: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><path d="M12 12l6-6" /></>,
    swipe: <><rect x="5" y="3" width="11" height="16" rx="2" /><path d="M19 8v10a2 2 0 0 1-2 2H8" /></>,
    photo: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="9" cy="10" r="2" /><path d="M21 16l-5-5-9 9" /></>,
    script: <><path d="M6 3h9l4 4v14H6z" /><path d="M9 11h7M9 15h7M9 7h3" /></>,
    film: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 5v14M17 5v14M3 9h4M3 15h4M17 9h4M17 15h4" /></>,
    mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>,
    type: <><path d="M4 7V5h16v2M12 5v14M9 19h6" /></>,
    layers: <><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></>,
    auto: <><path d="M13 3L5 14h6l-1 7 8-11h-6z" /></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></>,
    megaphone: <><path d="M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1z" /><path d="M17 8a5 5 0 0 1 0 8" /></>,
    rupee: <><path d="M7 5h10M7 9h10M7 5c5 0 5 8 0 8l7 6" /></>,
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden className="size-5" fill="none" stroke="currentColor" strokeWidth={1.8}
         strokeLinecap="round" strokeLinejoin="round">{d[name]}</svg>
  );
}

function Check() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" fill="none" stroke="currentColor"
         strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10" /></svg>
  );
}

// The public homepage (also what Google's OAuth verification reviews: it names the
// app as the consent screen does, says what it is for, and why it asks for each
// permission — the "Trust" section).
export default function HomePage() {
  const site = siteUrl();
  const waitlist = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Content Corpus waitlist")}`;
  const jsonLd = [
    { "@context": "https://schema.org", "@type": "SoftwareApplication", name: "Content Corpus",
      applicationCategory: "MultimediaApplication", operatingSystem: "Web, Android, iOS (installable web app)",
      description: DESCRIPTION, url: site, publisher: { "@type": "Organization", name: "Strophic" },
      featureList: FEATURES.map((f) => f.title) },
    { "@context": "https://schema.org", "@type": "FAQPage",
      mainEntity: FAQ.map(([q, a]) => ({ "@type": "Question", name: q, acceptedAnswer: { "@type": "Answer", text: a } })) },
  ];

  return (
    <main className="overflow-x-clip">
      <script type="application/ld+json"
              dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />

      {/* ── hero ── */}
      <section className="relative">
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
          <div className="blob absolute -top-32 -left-24 size-[28rem] rounded-full bg-accent/25 blur-3xl" />
          <div className="blob blob-2 absolute top-20 -right-32 size-[26rem] rounded-full bg-[var(--accent-2)]/20 blur-3xl" />
        </div>
        <div className="mx-auto grid w-full max-w-6xl grid-cols-1 items-center gap-12 px-4 pt-10 pb-16 sm:pt-16 lg:grid-cols-[1.1fr_0.9fr]">
          <Reveal>
            <p className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-muted">
              <span className="size-1.5 rounded-full bg-accent" /> Private beta · by Strophic
            </p>
            <h1 className="mt-4 text-4xl leading-[1.08] font-semibold tracking-tight sm:text-6xl">
              From today&apos;s news to a posted Short — <span className="gradient-text">while you sleep.</span>
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">
              Content Corpus finds the stories your audience will tap, collects the real logos, photos and footage,
              writes and voices the script, renders the video and posts it to <strong className="text-foreground">YouTube
              Shorts</strong> and <strong className="text-foreground">Instagram Reels</strong> — on your schedule.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <a href={waitlist} className="pressable rounded-xl bg-accent px-5 py-3 font-medium text-accent-foreground shadow-lg shadow-accent/25">
                Join the waitlist
              </a>
              <a href="#how" className="pressable rounded-xl border border-border bg-surface px-5 py-3 font-medium">See how it works</a>
            </div>
            <dl className="mt-10 grid max-w-xl grid-cols-2 gap-4 sm:grid-cols-4">
              {STATS.map(([n, what]) => (
                <div key={what}>
                  <dt className="text-2xl font-semibold tabular-nums">{n}</dt>
                  <dd className="text-xs text-muted">{what}</dd>
                </div>
              ))}
            </dl>
          </Reveal>
          <Reveal delay={150} className="relative mx-auto w-full max-w-md lg:max-w-none">
            <div className="relative mx-auto aspect-[4/5] w-full max-w-[26rem]">
              <div className="browser-frame float-slow absolute top-6 right-0 w-[78%] overflow-hidden">
                <Image src="/site/post.webp" alt="A video's progress in Content Corpus" width={1600} height={1000}
                       className="aspect-[4/5] w-full object-cover object-left-top" priority />
              </div>
              <div className="phone-frame float absolute bottom-0 left-0 w-[52%]">
                <Image src="/site/phone-discover.webp" alt="Swiping through ideas in Discover" width={780} height={1688}
                       className="h-auto w-full rounded-[1.6rem]" priority />
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── how it works ── */}
      <section id="how" className="scroll-mt-20 border-y border-border bg-surface/60">
        <div className="mx-auto w-full max-w-6xl px-4 py-20">
          <Reveal className="max-w-2xl">
            <p className="text-sm font-medium text-accent">How it works</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Five steps. You decide how many you take.</h2>
            <p className="mt-3 text-muted">Review every script and choose every posting time — or switch on autopilot and
              let each video go from idea to posted on its own.</p>
          </Reveal>
          <ol className="mt-12 grid grid-cols-1 gap-4 md:grid-cols-5">
            {STEPS.map((s, i) => (
              <Reveal as="li" key={s.title} delay={i * 90}
                      className="relative rounded-2xl border border-border bg-surface p-5 shadow-[var(--shadow)]">
                <span className="grid size-8 place-items-center rounded-full bg-accent text-sm font-semibold text-accent-foreground">
                  {i + 1}
                </span>
                <h3 className="mt-4 font-semibold">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{s.text}</p>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      {/* ── features ── */}
      <section id="features" className="mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-20">
        <Reveal className="max-w-2xl">
          <p className="text-sm font-medium text-accent">Features</p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Everything a short-video newsroom does — in one place.</h2>
        </Reveal>
        <ul className="mt-12 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <Reveal as="li" key={f.title} delay={(i % 3) * 80}
                    className="group rounded-2xl border border-border bg-surface p-5 transition hover:-translate-y-0.5 hover:border-accent/50 hover:shadow-[var(--shadow)]">
              <span className="grid size-10 place-items-center rounded-xl bg-accent/10 text-accent transition group-hover:bg-accent group-hover:text-accent-foreground">
                <FeatureIcon name={f.icon} />
              </span>
              <h3 className="mt-4 font-semibold">{f.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">{f.text}</p>
            </Reveal>
          ))}
        </ul>
      </section>

      {/* ── screens ── */}
      <section id="screens" className="scroll-mt-20 border-y border-border bg-surface/60">
        <div className="mx-auto w-full max-w-6xl px-4 py-20">
          <Reveal className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-medium text-accent">Inside the app</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Built for the phone in your pocket and the desk.</h2>
          </Reveal>
          <Reveal delay={100} className="mt-10"><Showcase /></Reveal>
          <div className="mt-14 grid grid-cols-1 items-end gap-6 sm:grid-cols-3">
            {[["/site/phone-discover.webp", "Discover: swipe through the day's ideas"],
              ["/site/phone-post.webp", "A video's progress and next step"],
              ["/site/phone-calendar.webp", "The calendar as a list on your phone"]].map(([src, alt], i) => (
              <Reveal key={src} delay={i * 120} className="text-center">
                <div className="phone-frame mx-auto w-full max-w-[15rem]">
                  <Image src={src} alt={alt} width={780} height={1688} className="h-auto w-full rounded-[1.6rem]" />
                </div>
                <p className="mt-3 text-sm text-muted">{alt}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── pricing ── */}
      <section id="pricing" className="mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-20">
        <Reveal className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-medium text-accent">Pricing</p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Three plans. Coming soon.</h2>
          <p className="mt-3 text-muted">Content Corpus is in private beta. Join the waitlist and we&apos;ll tell you first
            when Base, Pro and Elite open.</p>
        </Reveal>
        <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-3">
          {PLANS.map((p, i) => (
            <Reveal key={p.name} delay={i * 100}
                    className={`relative flex flex-col rounded-3xl border p-6 ${"featured" in p && p.featured
                      ? "border-accent bg-surface shadow-[0_20px_60px_-20px] shadow-accent/40" : "border-border bg-surface"}`}>
              {"featured" in p && p.featured && (
                <span className="absolute -top-3 left-6 rounded-full bg-accent px-3 py-1 text-xs font-semibold text-accent-foreground">
                  Most popular
                </span>
              )}
              <h3 className="text-xl font-semibold">{p.name}</h3>
              <p className="mt-1 text-sm text-muted">{p.who}</p>
              <p className="mt-6 flex items-baseline gap-2">
                <span className="text-3xl font-semibold tracking-tight">Coming soon</span>
              </p>
              <ul className="mt-6 flex flex-1 flex-col gap-2.5 text-sm">
                {p.points.map((pt) => <li key={pt} className="flex gap-2"><Check />{pt}</li>)}
              </ul>
              <a href={waitlist}
                 className={`pressable mt-8 rounded-xl px-4 py-2.5 text-center font-medium ${"featured" in p && p.featured
                   ? "bg-accent text-accent-foreground" : "border border-border"}`}>
                Join the waitlist
              </a>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── FAQ ── */}
      <section id="faq" className="scroll-mt-20 border-y border-border bg-surface/60">
        <div className="mx-auto w-full max-w-3xl px-4 py-20">
          <Reveal className="text-center">
            <p className="text-sm font-medium text-accent">FAQ</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">Questions, answered</h2>
          </Reveal>
          <div className="mt-10 flex flex-col gap-3">
            {FAQ.map(([q, a], i) => (
              <Reveal key={q} delay={i * 40}>
                <details className="faq group rounded-2xl border border-border bg-surface px-5 py-4 open:shadow-[var(--shadow)]">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                    {q}
                    <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-full border border-border text-muted transition group-open:rotate-45">+</span>
                  </summary>
                  <p className="mt-3 text-sm leading-relaxed text-muted">{a}</p>
                </details>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── trust & permissions (what Google's OAuth review reads) ── */}
      <section id="trust" className="mx-auto w-full max-w-4xl scroll-mt-20 px-4 py-20">
        <Reveal>
          <p className="text-sm font-medium text-accent">Trust & permissions</p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight">Why it asks for access to your Google account</h2>
          <p className="mt-3 leading-relaxed text-muted">
            Content Corpus uses Google Sign-In and the YouTube Data API (YouTube API Services). It asks only for what
            signing in and publishing need:
          </p>
          <dl className="mt-6 divide-y divide-border rounded-2xl border border-border bg-surface">
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
          <h3 className="mt-10 text-xl font-semibold tracking-tight">Instagram</h3>
          <p className="mt-2 leading-relaxed text-muted">
            With Instagram Login, Content Corpus reads your professional account&apos;s ID, username, name and profile
            picture, and publishes the Reels you schedule to it. Nothing else in your account is read or changed.
          </p>
          <div className="mt-10 rounded-2xl border border-border bg-surface p-6">
            <h3 className="text-xl font-semibold tracking-tight">Your data</h3>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm leading-relaxed text-muted">
              <li>Connection tokens are encrypted before they are stored, and deleted when you disconnect.</li>
              <li>Nothing is sold, shared for advertising, or given to anyone else.</li>
              <li>Data from your Google and Instagram accounts is never sent to AI models or used to train them.</li>
            </ul>
            <p className="mt-4 text-sm">
              The <Link href={`${site}/privacy`} className="underline">privacy policy</Link> explains exactly what is
              stored, for how long, and how to delete it. Use is subject to the{" "}
              <Link href={`${site}/terms`} className="underline">terms of service</Link>.
            </p>
          </div>
        </Reveal>
      </section>

      {/* ── last call ── */}
      <section className="px-4 pb-20">
        <Reveal className="cta-card mx-auto w-full max-w-5xl rounded-3xl px-6 py-14 text-center text-white sm:px-12">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">Your channel, posting every day.</h2>
          <p className="mx-auto mt-3 max-w-xl text-white/85">Join the waitlist for early access to Content Corpus.</p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <a href={waitlist} className="pressable inline-block rounded-xl bg-white px-6 py-3 font-semibold text-[#2a1f8f]">
              Join the waitlist
            </a>
            <Link href="/contact" className="pressable inline-block rounded-xl border border-white/40 px-6 py-3 font-semibold text-white">
              Talk to us
            </Link>
          </div>
        </Reveal>
      </section>
    </main>
  );
}
