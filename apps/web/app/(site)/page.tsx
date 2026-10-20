import type { Metadata } from "next";
import Link from "next/link";

import { CONTACT_EMAIL, siteUrl } from "@/lib/site";

import { CountUp, Faq, Headline, In, Monitor, Rundown, Timecode } from "./motion-bits";
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
  { slug: "Discover", time: "06:00", title: "The day's stories, ranked for your audience",
    text: "Every morning it reads news sites, trend feeds and communities for each of your categories. Jev, our decision "
      + "model, ranks the stories by how many of your viewers would stop and tap — and you swipe to keep the ones you want." },
  { slug: "Collect", time: "06:05", title: "The real thing, before a word is written",
    text: "The logos of the companies named, photos of the people and places, maps and flags, a card of each report, the "
      + "reports' own photos and video — and anything you add." },
  { slug: "Write", time: "06:12", title: "A script told like an explainer",
    text: "Written from several outlets' reports and checked against them, in the format the story's shape calls for: a "
      + "narrated explainer, a before/after, a countdown, footage with captions and music." },
  { slug: "Make", time: "06:20", title: "Real pictures first, AI where nothing real can show it",
    text: "Pictures pan, zoom and scroll; news footage plays; just a couple of AI-generated shots for the moment itself. "
      + "Then the voice, captions in the style that fits, music and a scroll-stopping cover." },
  { slug: "Publish", time: "18:00", title: "On air at the time you chose",
    text: "Title, caption with sources, hashtags, a first comment that adds context and the cover — posted to YouTube "
      + "Shorts and Instagram Reels. Or let autopilot run the whole day." },
] as const;

const DESKS = [
  { name: "The desk", note: "Finding the story", items: [
    ["Trend radar by category", "Science, crime, finance, sport, India, world… each category with its own sources and its own daily count."],
    ["Swipe to decide", "Ideas arrive as cards: the story, why it's trending, its media and what it cost so far."],
    ["Real assets, credited", "Logos, photos, maps, flags, report cards and news footage — credited on screen and in the caption."],
    ["Sourced scripts", "Written from several reports and checked against them; hooks that open a curiosity gap the video closes."],
  ] },
  { name: "The edit", note: "Making the video", items: [
    ["AI video where it counts", "Cinematic generated shots for what footage can't show — and image-to-video that brings a photo to life."],
    ["44 voices, English & Hindi", "Free natural narrators and expressive AI voices whose tone follows the script."],
    ["25 caption & cover styles", "Chosen per video to fit the story and the title; captions never cover a picture's own words."],
    ["22 formats", "Explainers, before/after, countdowns, myth vs fact, split screens, footage with captions, carousels."],
  ] },
  { name: "The broadcast", note: "Getting it out", items: [
    ["Autopilot", "When you're away it picks the day's top stories and posts them — no idea batch, no wasted tokens."],
    ["Calendar & library", "Plan the month, drag a video to another day, see every video's stage, cost and views."],
    ["Ready to post", "A gripping, accurate title, a sourced caption, hashtags, a first comment and the cover."],
    ["Every rupee shown", "The cost of each idea and each video — writing, voice, GPU minutes — always in view."],
  ] },
] as const;

const TICKER = ["ISRO's reusable rocket lands itself", "Sensex climbs 1.2% as banks rally", "Limoges town hall spire falls in a protest fire",
  "Monsoon: Mumbai's coastal road sank 12 cm", "Jio Platforms' IPO leads a busy week", "Why your phone battery dies faster in winter",
  "Bleached corals recover in seven weeks", "India clinch the series in Harare"];

const PLANS = [
  { name: "Base", who: "For one channel getting started", points: ["One channel, a few categories", "Daily stories ranked for your audience",
      "Real assets collected for every story", "Free narrator voices", "Scheduling to Shorts & Reels"] },
  { name: "Pro", who: "For creators posting every day", featured: true, points: ["Everything in Base", "More channels, higher monthly volume",
      "AI voices in English & Hindi", "Autopilot from idea to posted video", "Every format, caption style and cover"] },
  { name: "Elite", who: "For newsrooms and studios", points: ["Everything in Pro", "The most channels and the highest volume",
      "Your own formats and looks", "Cost reports per channel", "First access to new formats"] },
] as const;

const FAQ = [
  ["What is Content Corpus?", "An AI studio for short vertical video. It finds the stories worth covering, collects real pictures and footage, writes and voices the script, renders the video and publishes it to YouTube Shorts and Instagram Reels on your schedule."],
  ["Do I have to post everything it makes?", "No. In manual mode nothing happens without you: you keep the ideas you like, read and approve each script, and choose when it goes out. Autopilot is an option per video or per channel."],
  ["Where do the pictures and footage come from?", "From the story itself: logos, photos, maps and flags from Wikipedia and Wikimedia Commons, the news reports' own photos and video, a card of each report, and anything you upload or link. Each is credited on screen and in the caption. AI-generated shots are used only for what nothing real can show."],
  ["Does it work in Hindi?", "Yes. Scripts can be written in Hindi and read by AI voices that speak natural Hindi; English uses free, natural narrators."],
  ["Can every video have narration — or none?", "Both. Narrated explainers suit stories that need explaining; for stories the pictures tell by themselves there's a format with captions and background music only. Jev picks the format by the story's shape."],
  ["How much does a video cost to make?", "You see the exact cost of every idea and every video in the app. Shots made from real pictures cost nothing to render and AI shots are capped per video, so videos stay cheap."],
  ["Is my YouTube and Instagram account safe?", "It asks only for what signing in and publishing need, stores connection tokens encrypted, never reads or changes your other videos, and you can disconnect at any time. Details are below and in the privacy policy."],
  ["When can I sign up, and what will it cost?", "Content Corpus is in private beta. Base, Pro and Elite plans are coming soon — join the waitlist and we'll write to you when they open."],
] as const;

const GOOGLE_ACCESS = [
  ["Sign in with Google", "openid, email, profile", "Your name, email address and profile picture, to sign you in."],
  ["Upload YouTube videos", "youtube.upload",
    "To upload the videos you made and scheduled in Content Corpus to your channel, at the time you chose."],
  ["View your YouTube account", "youtube.readonly",
    "To read your channel's ID, name, handle and picture once, when you connect it, so the app shows which channel "
    + "it will publish to."],
] as const;

const PHONE_SHOTS = [{ src: "/site/phone-discover.webp", label: "Discover" }, { src: "/site/phone-post.webp", label: "The run" },
  { src: "/site/phone-calendar.webp", label: "Calendar" }];

// The public homepage (also what Google's OAuth verification reads: it names the app
// as the consent screen does, says what it is for and why it asks for each permission
// — the "Standards & permissions" section).
export default function HomePage() {
  const site = siteUrl();
  const waitlist = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Content Corpus waitlist")}`;
  const today = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric",
                                                   timeZone: "Asia/Kolkata" }).format(new Date());
  const jsonLd = [
    { "@context": "https://schema.org", "@type": "SoftwareApplication", name: "Content Corpus",
      applicationCategory: "MultimediaApplication", operatingSystem: "Web, Android, iOS (installable web app)",
      description: DESCRIPTION, url: site, publisher: { "@type": "Organization", name: "Strophic" },
      featureList: DESKS.flatMap((d) => d.items.map(([t]) => t)) },
    { "@context": "https://schema.org", "@type": "FAQPage",
      mainEntity: FAQ.map(([q, a]) => ({ "@type": "Question", name: q, acceptedAnswer: { "@type": "Answer", text: a } })) },
  ];

  return (
    <main className="overflow-x-clip">
      <script type="application/ld+json"
              dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />

      {/* ── the dateline ── */}
      <div className="border-y border-ink/80">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-4 px-4 py-2 font-mono text-[11px] uppercase tracking-[0.14em]">
          <span className="flex items-center gap-2 text-accent"><span className="on-air-dot" /> On air</span>
          <span className="hidden text-muted sm:inline">Private beta · Edition 01</span>
          <span className="ml-auto hidden text-muted md:inline" suppressHydrationWarning>{today}</span>
          <Timecode className="text-foreground" />
        </div>
      </div>

      {/* ── front page ── */}
      <section className="mx-auto grid w-full max-w-6xl grid-cols-1 items-center gap-12 px-4 pt-12 pb-16 sm:pt-16 lg:grid-cols-[1.15fr_0.85fr]">
        <div>
          <In><p className="kicker text-muted">The AI newsroom for Shorts &amp; Reels</p></In>
          <Headline words={["From", "today's", "news", "to", "a", "posted", "Short."]} accent={[5, 6]}
                    className="mt-4 text-[2.9rem] leading-[0.98] font-semibold tracking-tight sm:text-7xl" />
          <In delay={0.55}>
            <div className="mt-6 h-px w-24 bg-accent" />
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted">
              Content Corpus finds the stories your audience will tap, collects the real logos, photos and footage, writes
              and voices the script, renders the video and posts it to <strong className="text-foreground">YouTube
              Shorts</strong> and <strong className="text-foreground">Instagram Reels</strong> — on your schedule.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a href={waitlist} className="pressable btn-primary group inline-flex items-center gap-2 rounded-lg px-5 py-3 font-medium">
                Join the waitlist <span className="transition-transform group-hover:translate-x-0.5">→</span>
              </a>
              <a href="#rundown" className="pressable rounded-lg border border-ink/80 px-5 py-3 font-medium hover:bg-ink hover:text-background">
                See the running order
              </a>
            </div>
          </In>
          <In delay={0.75}>
            <dl className="mt-12 grid max-w-xl grid-cols-2 border-t border-border sm:grid-cols-4">
              {[[22, "formats"], [25, "caption & cover styles"], [44, "voices, English & Hindi"], [2, "platforms"]].map(([n, what], i) => (
                <div key={String(what)} className={`py-4 pr-3 ${i ? "sm:border-l sm:border-border sm:pl-4" : ""}`}>
                  <dt className="font-[family-name:var(--font-display)] text-4xl font-semibold"><CountUp to={Number(n)} /></dt>
                  <dd className="kicker mt-1 text-[10px] text-muted">{what}</dd>
                </div>
              ))}
            </dl>
          </In>
        </div>
        <In delay={0.3} className="mx-auto w-full max-w-[19rem] lg:max-w-[20rem]">
          <Monitor shots={PHONE_SHOTS} />
        </In>
      </section>

      {/* ── the ticker ── */}
      <div className="ticker relative flex overflow-hidden border-y border-ink bg-ink text-background" aria-hidden>
        <span className="relative z-10 flex shrink-0 items-center gap-2 bg-accent px-4 py-3 font-mono text-xs font-semibold tracking-[0.18em] text-white">
          BREAKING
        </span>
        <div className="ticker-track flex shrink-0 items-center gap-10 py-3 pl-6 font-medium whitespace-nowrap">
          {[...TICKER, ...TICKER].map((t, i) => (
            <span key={i} className="flex items-center gap-10">{t}<span className="text-accent">◆</span></span>
          ))}
        </div>
      </div>

      {/* ── the running order ── */}
      <section id="rundown" className="mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-24">
        <In className="max-w-3xl">
          <p className="kicker text-accent">How it works</p>
          <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-6xl">Tonight&apos;s running order.</h2>
          <p className="mt-4 max-w-2xl text-lg text-muted">Five steps from the morning&apos;s news to the evening&apos;s post.
            Review every script and choose every time — or switch on autopilot and let the day run itself.</p>
        </In>
        <Rundown steps={[...STEPS]} />
      </section>

      {/* ── the desks ── */}
      <section id="features" className="scroll-mt-20 border-t border-ink/80 bg-surface/50">
        <div className="mx-auto w-full max-w-6xl px-4 py-24">
          <In className="flex flex-wrap items-end justify-between gap-6">
            <div className="max-w-2xl">
              <p className="kicker text-accent">Features</p>
              <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-6xl">A whole newsroom, in one place.</h2>
            </div>
            <p className="max-w-sm text-muted">Three desks, one run: find the story, make the video, get it on air.</p>
          </In>
          <div className="mt-14 grid grid-cols-1 border-t-2 border-ink md:grid-cols-3">
            {DESKS.map((d, di) => (
              <In key={d.name} delay={di * 0.1}
                  className={`border-border py-8 md:px-7 ${di ? "border-t md:border-t-0 md:border-l" : "md:pl-0"} ${di === 2 ? "md:pr-0" : ""}`}>
                <p className="kicker text-muted">0{di + 1} · {d.note}</p>
                <h3 className="mt-2 font-[family-name:var(--font-display)] text-3xl font-semibold italic tracking-tight">{d.name}</h3>
                <ul className="mt-6 flex flex-col">
                  {d.items.map(([t, text]) => (
                    <li key={t} className="group border-t border-border py-4">
                      <p className="flex items-center gap-2 font-semibold">
                        <span className="h-px w-0 bg-accent transition-all duration-300 group-hover:w-4" />{t}
                      </p>
                      <p className="mt-1 text-sm leading-relaxed text-muted">{text}</p>
                    </li>
                  ))}
                </ul>
              </In>
            ))}
          </div>
        </div>
      </section>

      {/* ── the monitor wall ── */}
      <section id="screens" className="scroll-mt-20 border-t border-ink/80">
        <div className="mx-auto w-full max-w-6xl px-4 py-24">
          <In className="mx-auto max-w-2xl text-center">
            <p className="kicker text-accent">Inside the app</p>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-6xl">The monitor wall.</h2>
            <p className="mt-4 text-muted">Built for the phone in your pocket and the desk in the morning.</p>
          </In>
          <In delay={0.1} className="mt-12"><Showcase /></In>
        </div>
      </section>

      {/* ── editions (pricing) ── */}
      <section id="pricing" className="scroll-mt-20 border-t border-ink/80 bg-surface/50">
        <div className="mx-auto w-full max-w-6xl px-4 py-24">
          <In className="mx-auto max-w-2xl text-center">
            <p className="kicker text-accent">Pricing</p>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-6xl">Three editions.</h2>
            <p className="mt-4 text-muted">Content Corpus is in private beta. Join the waitlist and you&apos;ll hear first when
              Base, Pro and Elite go to press.</p>
          </In>
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
            {PLANS.map((p, i) => {
              const featured = "featured" in p && p.featured;
              return (
                <In key={p.name} delay={i * 0.1}
                    className={`relative flex h-full flex-col border p-7 ${featured ? "border-ink bg-ink text-background" : "border-ink/70 bg-background"}`}>
                  <div className={`border-b pb-4 ${featured ? "border-background/25" : "border-ink/30"}`}>
                    <p className={`kicker ${featured ? "text-accent-2" : "text-muted"}`}>The {p.name} edition</p>
                    <h3 className="mt-2 font-[family-name:var(--font-display)] text-5xl font-semibold tracking-tight">{p.name}</h3>
                    <p className={`mt-2 text-sm ${featured ? "text-background/70" : "text-muted"}`}>{p.who}</p>
                  </div>
                  <span className="stamp absolute top-6 right-5">Coming soon</span>
                  <ul className="mt-6 flex flex-1 flex-col gap-3 text-sm">
                    {p.points.map((pt) => (
                      <li key={pt} className="flex gap-2.5"><span className="mt-2 h-px w-3 shrink-0 bg-accent" />{pt}</li>
                    ))}
                  </ul>
                  <a href={waitlist}
                     className={`pressable mt-8 rounded-lg px-4 py-3 text-center font-medium ${featured
                       ? "btn-primary" : "border border-ink/80 hover:bg-ink hover:text-background"}`}>
                    Join the waitlist
                  </a>
                </In>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── questions ── */}
      <section id="faq" className="scroll-mt-20 border-t border-ink/80">
        <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-10 px-4 py-24 lg:grid-cols-[0.8fr_1.2fr]">
          <In>
            <p className="kicker text-accent">FAQ</p>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-6xl">Letters to the editor.</h2>
            <p className="mt-4 text-muted">Something else? <Link href="/contact" className="text-accent underline underline-offset-4">Write to us</Link>.</p>
          </In>
          <In delay={0.1} className="border-t border-ink">
            {FAQ.map(([q, a], i) => <Faq key={q} q={q} a={a} i={i} />)}
          </In>
        </div>
      </section>

      {/* ── standards & permissions (what Google's OAuth review reads) ── */}
      <section id="trust" className="scroll-mt-20 border-t border-ink/80 bg-surface/50">
        <div className="mx-auto w-full max-w-4xl px-4 py-24">
          <In>
            <p className="kicker text-accent">Standards &amp; permissions</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">Why it asks for access to your Google account</h2>
            <p className="mt-4 leading-relaxed text-muted">
              Content Corpus uses Google Sign-In and the YouTube Data API (YouTube API Services). It asks only for what
              signing in and publishing need:
            </p>
            <dl className="mt-6 border-y-2 border-ink">
              {GOOGLE_ACCESS.map(([what, scope, why]) => (
                <div key={what} className="grid grid-cols-1 gap-1 border-b border-border py-5 last:border-b-0 sm:grid-cols-[14rem_1fr] sm:gap-6">
                  <dt>
                    <span className="font-semibold">{what}</span>
                    <code className="mt-1 block font-mono text-xs text-muted">{scope}</code>
                  </dt>
                  <dd className="text-sm leading-relaxed text-muted">{why}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-5 text-sm leading-relaxed text-muted">
              It never reads, changes or deletes your existing videos, comments, playlists or analytics, and it never
              publishes anything you did not schedule. Disconnect your channel at any time in the app, or remove the
              app&apos;s access in your{" "}
              <a className="underline" href="https://security.google.com/settings/security/permissions">Google Account</a>.
            </p>
            <div className="mt-10 grid grid-cols-1 gap-8 sm:grid-cols-2">
              <div>
                <h3 className="font-[family-name:var(--font-display)] text-2xl font-semibold">Instagram</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  With Instagram Login, Content Corpus reads your professional account&apos;s ID, username, name and
                  profile picture, and publishes the Reels you schedule to it. Nothing else in your account is read or
                  changed.
                </p>
              </div>
              <div>
                <h3 className="font-[family-name:var(--font-display)] text-2xl font-semibold">Your data</h3>
                <ul className="mt-2 flex flex-col gap-1.5 text-sm leading-relaxed text-muted">
                  <li>Connection tokens are encrypted before they are stored, and deleted when you disconnect.</li>
                  <li>Nothing is sold, shared for advertising, or given to anyone else.</li>
                  <li>Data from your Google and Instagram accounts is never sent to AI models or used to train them.</li>
                </ul>
              </div>
            </div>
            <p className="mt-8 text-sm">
              The <Link href={`${site}/privacy`} className="underline">privacy policy</Link> explains exactly what is
              stored, for how long, and how to delete it. Use is subject to the{" "}
              <Link href={`${site}/terms`} className="underline">terms of service</Link>.
            </p>
          </In>
        </div>
      </section>

      {/* ── sign-off ── */}
      <section className="relative overflow-hidden bg-ink text-background">
        <div className="mx-auto w-full max-w-6xl px-4 py-24">
          <In>
            <p className="kicker flex items-center gap-2 text-accent-2"><span className="on-air-dot" /> Stand by</p>
            <h2 className="mt-4 max-w-4xl text-5xl leading-[1] font-semibold tracking-tight sm:text-7xl">
              Your channel, on air <span className="text-accent italic">every day.</span>
            </h2>
            <div className="mt-10 flex flex-wrap gap-3">
              <a href={waitlist} className="pressable btn-primary rounded-lg px-6 py-3 font-semibold">Join the waitlist →</a>
              <Link href="/contact" className="pressable rounded-lg border border-background/40 px-6 py-3 font-semibold hover:bg-background hover:text-ink">
                Talk to us
              </Link>
            </div>
          </In>
        </div>
      </section>
    </main>
  );
}
