import Link from "next/link";
import { notFound } from "next/navigation";

import { ACCOUNT_COLS, type Account, CHANNEL_COLS, type Channel } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { configured } from "@/lib/oauth";
import { requireUser } from "@/lib/session";

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
    return { channel, accounts };
  });
  if (!data) notFound();
  const { channel, accounts } = data;
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

      <section className="rounded-2xl border border-border bg-surface p-5">
        <h2 className="font-medium">Profile</h2>
        <p className="mt-1 text-sm text-muted">Every idea and script for this channel is written in this voice.</p>
        <div className="mt-4"><ChannelForm channel={channel} /></div>
      </section>
    </div>
  );
}
