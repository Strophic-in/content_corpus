import Link from "next/link";

import { ACCOUNT_COLS, type Account, workspace } from "@/lib/channels";
import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";

import { ChannelForm } from "./channel-forms";

export const metadata = { title: "Channels · Content Corpus" };

export default async function ChannelsPage({ searchParams }: { searchParams: Promise<{ connect_error?: string }> }) {
  const user = await requireUser();
  const { channels } = await workspace(user.id);
  const accounts = await asUser(user.id, async (db) =>
    (await db.query(`select ${ACCOUNT_COLS} from channel_accounts`)).rows as Account[]);
  const { connect_error } = await searchParams;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Channels</h1>
        <p className="mt-1 text-sm text-muted">Each channel has its own voice, formats, ideas and connected accounts.</p>
      </div>
      {connect_error && <p role="alert" className="rounded-xl bg-danger-surface px-3 py-2 text-sm text-danger">{connect_error}</p>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {channels.map((c) => {
          const mine = accounts.filter((a) => a.channel_id === c.id);
          return (
            <Link key={c.id} href={`/channels/${c.id}`}
                  className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-4 transition hover:border-accent active:scale-[.99]">
              <div className="flex items-center gap-2">
                <span className="font-medium">{c.name}</span>
                {c.is_default && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">default</span>}
              </div>
              <p className="line-clamp-2 text-sm text-muted">{c.niche || "No niche set yet."}</p>
              <div className="flex gap-2 text-xs">
                {(["youtube", "instagram"] as const).map((p) => {
                  const a = mine.find((x) => x.platform === p);
                  return (
                    <span key={p} className={`rounded-full px-2 py-0.5 ${a?.status === "connected" ? "bg-ok/15 text-ok" : "bg-background text-muted"}`}>
                      {p === "youtube" ? "YouTube" : "Instagram"} {a?.status === "connected" ? `· ${a.handle ?? a.display_name ?? "connected"}` : "· not connected"}
                    </span>
                  );
                })}
              </div>
            </Link>
          );
        })}
      </div>
      <section className="rounded-2xl border border-border bg-surface p-5">
        <h2 className="font-medium">New channel</h2>
        <p className="mt-1 text-sm text-muted">It starts with the narrated 3D-explainer format; add others in its Library.</p>
        <div className="mt-4"><ChannelForm /></div>
      </section>
    </div>
  );
}
