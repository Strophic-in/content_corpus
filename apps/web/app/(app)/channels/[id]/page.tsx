import Link from "next/link";
import { notFound } from "next/navigation";

import { ACCOUNT_COLS, type Account, CHANNEL_COLS, type Channel } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { configured } from "@/lib/oauth";
import { requireUser } from "@/lib/session";
import { looks } from "@/lib/looks";
import { KIND_LABEL, template } from "@/lib/templates";

import { AutoRefresh } from "../../posts/[id]/post-actions";
import { CategoriesSection, type CategoryData } from "../categories";
import { ChannelForm, ChannelMenu, ConnectionCard } from "../channel-forms";

export const metadata = { title: "Channel · Content Corpus" };

export default async function ChannelPage({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<{ connected?: string; connect_error?: string }>;
}) {
  const user = await requireUser();
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const data = await asUser(user.id, async (db) => {
    const channel = (await db.query(`select ${CHANNEL_COLS} from channels where id = $1`, [id])).rows[0] as Channel | undefined;
    if (!channel) return null;
    const accounts = (await db.query(`select ${ACCOUNT_COLS} from channel_accounts where channel_id = $1`, [id])).rows as Account[];
    const formats = (await db.query(
      "select id, name, template_id from formats where channel_id = $1 order by is_default desc, created_at",
      [id])).rows as { id: string; name: string; template_id: string }[];
    // Each category with its sources, whether a check is running, and the latest suggestions.
    const categories = (await db.query(
      `select k.id, k.name, k.color, k.brief, k.keywords, k.format_ids, k.ideas_per_batch, k.enabled,
              coalesce((select json_agg(json_build_object('id', s.id, 'kind', s.kind, 'value', s.value,
                                 'enabled', s.enabled, 'status', s.status, 'last_items', s.last_items,
                                 'last_error', s.last_error) order by s.created_at)
                          from category_sources s where s.category_id = k.id), '[]') as sources,
              exists (select 1 from jobs j where j.kind = 'check_sources' and j.state in ('queued','claimed')
                        and j.payload->>'category_id' = k.id::text) as checking,
              (select json_build_object('state', j.state, 'result', j.result) from jobs j
                where j.kind = 'suggest_sources' and j.payload->>'category_id' = k.id::text
                order by j.created_at desc limit 1) as suggestion
         from categories k where k.channel_id = $1 order by k.created_at`, [id])).rows as CategoryData[];
    return { channel, accounts, formats, categories };
  });
  if (!data) notFound();
  const { channel, accounts, formats, categories } = data;
  const busy = categories.some((c) => c.checking || c.sources.some((s) => s.status === "new") ||
                                      ["queued", "claimed"].includes(c.suggestion?.state ?? ""));
  const { connected, connect_error } = await searchParams;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <Link href="/channels" className="text-sm text-muted hover:text-foreground">← Channels</Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{channel.name}</h1>
        </div>
        <ChannelMenu channelId={channel.id} isDefault={channel.is_default} />
      </div>

      {connected && <p role="status" className="rounded-xl bg-ok/15 px-3 py-2 text-sm text-ok">
        {connected === "youtube" ? "YouTube" : "Instagram"} connected.</p>}
      {connect_error && <p role="alert" className="rounded-xl bg-danger-surface px-3 py-2 text-sm text-danger">{connect_error}</p>}

      <section className="flex flex-col gap-3">
        <h2 className="font-medium">Accounts</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {(["youtube", "instagram"] as const).map((p) => (
            <ConnectionCard key={p} platform={p} channelId={channel.id} ready={configured(p)}
                            account={accounts.find((a) => a.platform === p) ?? null} />
          ))}
        </div>
      </section>

      {busy && <AutoRefresh everyMs={5000} />}
      <CategoriesSection channelId={channel.id} categories={categories}
                         formats={formats.map((f) => ({ id: f.id, name: f.name, kind: KIND_LABEL[template(f.template_id).content_type] }))} />

      <section className="rounded-2xl border border-border bg-surface p-5">
        <h2 className="font-medium">Profile</h2>
        <p className="mt-1 text-sm text-muted">Every idea and script for this channel is written in this voice.</p>
        <div className="mt-4"><ChannelForm channel={channel} looks={looks()} /></div>
      </section>
    </div>
  );
}
