import Link from "next/link";

import { contactEmail, POLICIES_UPDATED } from "@/lib/site";

export const metadata = { title: "Privacy policy · Content Corpus" };

// Linked from the Google and Meta consent screens. Every statement here describes
// what the code does (lib/oauth.ts, lib/crypto.ts, channel-actions.ts, worker/);
// change the policy when that changes.
export default function PrivacyPage() {
  const contact = contactEmail();
  const mail = contact
    ? <a className="underline" href={`mailto:${contact}`}>{contact}</a>
    : "the address on the Content Corpus homepage";
  return (
    <main className="mx-auto w-full max-w-2xl px-4 pt-6 pb-16 text-sm leading-relaxed [&_h2]:mt-10 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-5 [&_h3]:mb-1 [&_h3]:font-medium [&_li]:mt-1 [&_p]:mt-3 [&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-5 [&_a]:underline">
      <h1 className="text-2xl font-semibold tracking-tight">Privacy policy</h1>
      <p className="text-muted">Content Corpus · last updated {POLICIES_UPDATED}</p>

      <p>
        Content Corpus (<Link href="/">content-corpus.strophic.in</Link>) is an AI short-video studio built and run by
        Strophic. It finds video ideas, makes short vertical videos, and publishes them to the YouTube channel and
        Instagram account its owner connects. It is a private tool: only the owner can sign in, and sign-ups are
        closed. This policy explains what data the app collects, how it uses, stores and shares that data, how long it
        keeps it, and how to have it deleted. &ldquo;We&rdquo; means Strophic, the operator of Content Corpus;
        &ldquo;you&rdquo; means the person signed in.
      </p>

      <h2>1. Data we collect</h2>
      <h3>Your account</h3>
      <ul>
        <li>Your email address and name, and your profile picture if you sign in with Google.</li>
        <li>If you sign in with email and password: a salted hash of your password, never the password itself.</li>
        <li>
          If you sign in with Google, the sign-in tokens Google returns. They are kept with your account record and not
          used for anything else.
        </li>
        <li>For each signed-in session: when it started and expires, your IP address and your browser&apos;s user agent.</li>
      </ul>

      <h3>Google user data, when you connect a YouTube channel</h3>
      <p>
        Content Corpus uses YouTube API Services. When you connect a channel, you grant the{" "}
        <code>youtube.upload</code> and <code>youtube.readonly</code> permissions, and we store:
      </p>
      <ul>
        <li>a refresh token, which lets the app upload videos to the channel later;</li>
        <li>the permissions you granted;</li>
        <li>
          your channel&apos;s ID, name, handle and picture URL, read once from the YouTube Data API when you connect, so
          the app can show which channel it will publish to.
        </li>
      </ul>
      <p>
        We do not read, collect or store your existing videos, comments, playlists, subscribers, analytics or any other
        YouTube or Google data.
      </p>

      <h3>Instagram data, when you connect an Instagram account</h3>
      <ul>
        <li>a long-lived access token (it expires after about 60 days) and the permissions you granted;</li>
        <li>your professional account&apos;s ID, username, name and profile picture URL, read once when you connect.</li>
      </ul>

      <h3>Content you create</h3>
      <p>
        Channels and their descriptions, prompts, ideas, scripts, schedules, and the narration, video and caption files
        the app generates for them.
      </p>

      <h3>Cookies and logs</h3>
      <ul>
        <li>
          A session cookie that keeps you signed in, and a short-lived security cookie (15 minutes) used while you
          connect an account. No advertising or analytics cookies, and no tracking.
        </li>
        <li>
          Our web server logs each request (IP address, time, page and browser) for security and troubleshooting, and
          deletes those logs after 14 days.
        </li>
      </ul>

      <h2>2. How we use it</h2>
      <ul>
        <li>Your account data: to sign you in and keep your account secure.</li>
        <li>
          Google user data: only to show which YouTube channel is connected, and to upload the videos you created and
          scheduled in Content Corpus to that channel, at the time you chose. We never publish anything you did not
          schedule, and never change or delete anything already on your channel.
        </li>
        <li>Instagram data: only to show which account is connected and to publish the Reels you scheduled to it.</li>
        <li>Your content: to make and publish your videos.</li>
      </ul>
      <p>
        Content Corpus&apos;s use and transfer of information received from Google APIs to any other app will adhere to
        the <a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data
        Policy</a>, including the Limited Use requirements. In particular, we do not use Google user data for
        advertising; we do not sell it; we do not use it to develop, improve or train AI or machine-learning models; and
        no person reads it unless you ask us to (for example, to help with a problem), it is necessary for security, or
        the law requires it.
      </p>

      <h2>3. Who we share it with</h2>
      <p>
        We do not sell, rent or trade any data, and we do not share Google or Instagram account data with anyone. The
        services below run parts of the app for us, and receive only what that part needs:
      </p>
      <ul>
        <li>Oracle Cloud hosts the server, the database and the narration model.</li>
        <li>Cloudflare serves the website and stores the generated video files in private storage (R2).</li>
        <li>
          OpenAI writes ideas and scripts. It receives topics, prompts and your channel&apos;s description, never your
          Google or Instagram data.
        </li>
        <li>A GPU rental service renders video shots from their text descriptions. It receives no account data.</li>
        <li>
          YouTube (Google) and Instagram (Meta) receive the videos you publish, together with their titles and
          captions.
        </li>
      </ul>
      <p>
        We may disclose data if the law requires it. Google&apos;s use of data is described in the{" "}
        <a href="https://policies.google.com/privacy">Google Privacy Policy</a>, and Instagram&apos;s in the{" "}
        <a href="https://privacycenter.instagram.com/policy">Instagram Privacy Policy</a>.
      </p>

      <h2>4. How we protect it</h2>
      <ul>
        <li>All traffic uses HTTPS.</li>
        <li>
          YouTube and Instagram tokens are encrypted with AES-256-GCM before they are stored. The website cannot read
          them back; only the background worker that publishes decrypts them, at the moment it publishes.
        </li>
        <li>The database limits every row to the account that owns it (row-level security).</li>
        <li>Video files sit in private storage that is not publicly reachable.</li>
      </ul>

      <h2>5. How long we keep it</h2>
      <ul>
        <li>YouTube and Instagram tokens and channel details: until you disconnect the account, or delete the channel it belongs to.</li>
        <li>Sessions: they expire after 7 days.</li>
        <li>Web server logs: 14 days.</li>
        <li>The idea agent&apos;s memory of past topics: 30 days per topic, unless you kept the idea.</li>
        <li>Your account and content: until you delete them, or ask us to.</li>
      </ul>

      <h2 id="delete-your-data">6. Your choices, and deleting your data</h2>
      <ul>
        <li>
          <strong>Disconnect an account:</strong> on the channel&apos;s page in Content Corpus, choose Disconnect. Its
          token and details are deleted from our database at once.
        </li>
        <li>
          <strong>Revoke access at the source:</strong> remove Content Corpus in your{" "}
          <a href="https://security.google.com/settings/security/permissions">Google Account permissions</a>, or in
          Instagram under Settings → Apps and websites. The app can then no longer use the token.
        </li>
        <li>
          <strong>Delete everything:</strong> email {mail} from the address you sign in with. We delete your account,
          content, files and tokens within 30 days and confirm by email.
        </li>
        <li>You can also email us to get a copy of your data or to correct it.</li>
      </ul>

      <h2>7. Children</h2>
      <p>Content Corpus is not meant for anyone under 16, and we do not knowingly collect their data.</p>

      <h2>8. Changes</h2>
      <p>
        If this policy changes, we update it on this page and change the date at the top. We will not use data already
        collected in a new way without asking for your consent first.
      </p>

      <h2>9. Contact</h2>
      <p>Questions or requests about privacy: {mail}.</p>

      <p className="text-muted"><Link href="/terms">Terms of service</Link></p>
    </main>
  );
}
