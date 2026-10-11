import Link from "next/link";
import { notFound } from "next/navigation";

import { FORMAT_COLS, type Format } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { defaultPrompts, PLACEHOLDERS } from "@/lib/prompt-defaults";
import { requireUser } from "@/lib/session";

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
    return { f, versions };
  });
  if (!data) notFound();
  const { f, versions } = data;
  const defaults = defaultPrompts(f.audio_source === "kokoro" ? "narrated" : "dialogue");

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <Link href="/library" className="text-sm text-muted hover:text-foreground">← Library</Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{f.name}</h1>
          <p className="text-sm text-muted">Version {f.version}{f.is_default ? " · default format" : ""}</p>
        </div>
        <FormatMenu formatId={f.id} isDefault={f.is_default} />
      </div>
      <FormatEditor
        format={{ ...f, updated_at: undefined }}
        defaults={{ ...defaults, sources: defaults.sources }}
        placeholders={PLACEHOLDERS}
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
