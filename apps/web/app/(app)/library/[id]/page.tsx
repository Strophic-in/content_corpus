import Link from "next/link";
import { notFound } from "next/navigation";

import { FORMAT_COLS, type Format } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { PLACEHOLDERS } from "@/lib/prompt-defaults";
import { requireUser } from "@/lib/session";
import { template, templateDefaults, templateInfo } from "@/lib/templates";

import { FormatEditor, FormatMenu, VersionList } from "../library-forms";

export const metadata = { title: "Format · Content Corpus" };

export default async function FormatPage({ params }: { params: Promise<{ id: string }> }) {
  const user = await requireUser();
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const data = await asUser(user.id, async (db) => {
    const f = (await db.query(`select ${FORMAT_COLS} from formats where id = $1`, [id])).rows[0] as Format | undefined;
    if (!f) return null;
    const versions = (await db.query(
      `select version, saved_at, snapshot from format_versions where format_id = $1 order by version desc limit 30`,
      [id])).rows as { version: number; saved_at: Date; snapshot: Record<string, unknown> }[];
    // How its posts did against the channel's own usual views (never "viral": compared).
    const perf = (await db.query(
      `with v as (select p.format_id, sum(coalesce(s.views, 0)) as views
                    from posts p join post_stats s on s.post_id = p.id
                   where p.channel_id = $2 group by p.id, p.format_id)
       select count(*) filter (where format_id = $1)::int as posts,
              avg(views) filter (where format_id = $1)::float8 as mine, avg(views)::float8 as usual from v`,
      [id, f.channel_id])).rows[0] as { posts: number; mine: number | null; usual: number | null };
    return { f, versions, perf };
  });
  if (!data) notFound();
  const { f, versions, perf } = data;
  const t = template(f.template_id);
  const defaults = templateDefaults(f.template_id);
  const results = perf.posts >= 1 && perf.usual
    ? `${perf.posts} published post${perf.posts === 1 ? "" : "s"} with numbers · ${((perf.mine ?? 0) / perf.usual).toFixed(1)}× the channel's usual views`
    : null;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <Link href="/library" className="text-sm text-muted hover:text-foreground">← Formats</Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{f.name}</h1>
          <p className="text-sm text-muted">{t.display_name} · version {f.version}{f.is_default ? " · default format" : ""}</p>
        </div>
        <FormatMenu formatId={f.id} isDefault={f.is_default} />
      </div>
      <FormatEditor
        format={{ id: f.id, name: f.name, description: f.description, audio_source: f.audio_source,
                  target_seconds: f.target_seconds, visual_style: f.visual_style, idea_prompt: f.idea_prompt,
                  script_prompt: f.script_prompt, params: f.params ?? {}, template_id: f.template_id }}
        template={templateInfo(t)}
        defaults={defaults}
        placeholders={PLACEHOLDERS}
        results={results}
      />
      {versions.length > 0 && (
        <VersionList formatId={f.id} versions={versions.map((v) => ({
          version: v.version,
          savedAt: new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(v.saved_at),
          preview: String(v.snapshot.script_prompt ?? "").slice(0, 140),
        }))} />
      )}
    </div>
  );
}
