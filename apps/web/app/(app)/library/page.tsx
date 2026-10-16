import Link from "next/link";

import { workspace } from "@/lib/channels";
import { requireUser } from "@/lib/session";

import { ChannelPicker } from "../nav";
import { NewFormatForm } from "./library-forms";

export const metadata = { title: "Library · Content Corpus" };

export default async function LibraryPage() {
  const user = await requireUser();
  const { channels, active, formats } = await workspace(user.id);
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Prompt library</h1>
        <p className="mt-1 text-sm text-muted">
          Formats for <ChannelPicker channels={channels.map(({ id, name }) => ({ id, name }))} activeId={active.id} /> — each kind of video it
          makes, with every prompt that shapes it: ideas, scripts and the look of every shot. Where ideas come from is
          set per category on the channel&apos;s page.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {formats.map((f) => (
          <Link key={f.id} href={`/library/${f.id}`}
                className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-4 transition hover:border-accent active:scale-[.99]">
            <div className="flex items-center gap-2">
              <span className="font-medium">{f.name}</span>
              {f.is_default && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">default</span>}
              <span className="ml-auto text-xs text-muted">v{f.version}</span>
            </div>
            <p className="line-clamp-2 text-sm text-muted">{f.description || "No description."}</p>
            <p className="text-xs text-muted">
              {f.audio_source === "kokoro" ? "Narrated voice-over" : "Characters speak"} · {f.target_seconds}s
            </p>
          </Link>
        ))}
      </div>
      <section className="rounded-2xl border border-border bg-surface p-5">
        <h2 className="font-medium">New format</h2>
        <p className="mt-1 text-sm text-muted">Starts from the built-in prompts; change anything after.</p>
        <div className="mt-4"><NewFormatForm /></div>
      </section>
    </div>
  );
}
