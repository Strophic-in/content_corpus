import Link from "next/link";

import { workspace } from "@/lib/channels";
import { requireUser } from "@/lib/session";
import { COST_LABEL, KIND_LABEL, ordered, template, templateInfo } from "@/lib/templates";

import { ChannelPicker } from "../nav";
import { NewFormatForm } from "./library-forms";

export const metadata = { title: "Library · Content Corpus" };

const AUDIO = { kokoro: "Narrated", ltx_native: "Characters speak", none: "No voice" } as const;

export default async function LibraryPage() {
  const user = await requireUser();
  const { channels, active, formats } = await workspace(user.id);
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Formats</h1>
        <p className="mt-1 text-sm text-muted">
          The kinds of post <ChannelPicker channels={channels.map(({ id, name }) => ({ id, name }))} activeId={active.id} /> makes —
          each one a template (a reel, a carousel, a picture card…) with your prompts and look. A category picks which
          of them its ideas may use; the idea agent chooses one per idea.
        </p>
      </div>
      <div className="grid auto-rows-fr gap-3 sm:grid-cols-2">
        {formats.map((f) => {
          const t = template(f.template_id);
          return (
            <Link key={f.id} href={`/library/${f.id}`}
                  className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-4 transition hover:border-accent active:scale-[.99]">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium">{f.name}</span>
                {f.is_default && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">default</span>}
                <span className="ml-auto shrink-0 text-xs text-muted">v{f.version}</span>
              </div>
              <p className="text-xs font-medium text-muted">{t.display_name}</p>
              <p className="line-clamp-2 text-sm text-muted">{f.description || t.format}</p>
              <p className="mt-auto text-xs text-muted">
                {KIND_LABEL[f.content_type]} · {f.content_type === "video" ? `${AUDIO[f.audio_source]} · ${f.target_seconds}s · ` : ""}
                {COST_LABEL[t.estimated_render_cost]}
              </p>
            </Link>
          );
        })}
      </div>
      <section className="rounded-2xl border border-border bg-surface p-5">
        <h2 className="font-medium">New format</h2>
        <p className="mt-1 text-sm text-muted">Pick a template; it starts with the template&apos;s prompts and look, and you change anything after.</p>
        <div className="mt-4"><NewFormatForm templates={ordered().map(templateInfo)} /></div>
      </section>
    </div>
  );
}
