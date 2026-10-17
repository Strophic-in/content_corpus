import Link from "next/link";

import { asUser } from "@/lib/db";
import { requireOwner } from "@/lib/session";

import { ConfigForm, MemberForm } from "./admin-forms";

export const metadata = { title: "Members · Content Corpus" };

type Member = {
  user_id: string; email: string; name: string; role: "owner" | "member"; status: string;
  monthly_limit_paise: number | null; month_paise: string; storage_bytes: string; created_at: Date;
};

const inr = (paise: number) => `₹${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

// The owner's view of everyone who uses Content Corpus: approve sign-ups, set each
// member's monthly spending limit (scripts, renders and idea batches stop at it),
// suspend an account. Owners come from AUTH_ALLOWED_EMAILS and aren't edited here.
export default async function AdminPage() {
  const owner = await requireOwner();
  const { members, config } = await asUser(owner.id, async (db) => ({
    members: (await db.query("select * from api.admin_members()")).rows as Member[],
    config: (await db.query("select * from api.admin_config()")).rows[0] as
      { signups_need_approval: boolean; member_monthly_limit_paise: number },
  }));
  const open = process.env.SIGNUPS_OPEN === "true";
  const waiting = members.filter((m) => m.status === "pending").length;
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div>
        <Link href="/settings" className="text-sm text-muted hover:text-foreground">← Settings</Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Members</h1>
        <p className="text-sm text-muted">
          {open ? "Sign-ups are open (SIGNUPS_OPEN=true)." : "Sign-ups are closed: only AUTH_ALLOWED_EMAILS can sign in. "
            + "Set SIGNUPS_OPEN=true on the server to let others sign up."}
          {waiting > 0 && ` ${waiting} waiting for you.`}
        </p>
      </div>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5">
        <h2 className="font-medium">New accounts</h2>
        <ConfigForm approval={config.signups_need_approval} limitRupees={config.member_monthly_limit_paise / 100} />
      </section>

      <section className="flex flex-col divide-y divide-border rounded-xl border border-border bg-surface text-sm">
        {members.map((m) => (
          <div key={m.user_id} className="flex flex-col gap-2 p-4">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-medium">{m.name}</span>
              <span className="text-muted">{m.email}</span>
              {m.role === "owner" && <span className="rounded bg-accent/15 px-1.5 text-xs text-accent">owner</span>}
              {m.status === "pending" && <span className="rounded bg-warn/15 px-1.5 text-xs text-warn">waiting</span>}
            </div>
            <p className="text-xs text-muted">
              This month {inr(Number(m.month_paise))}
              {m.monthly_limit_paise !== null ? ` of ${inr(m.monthly_limit_paise)}` : ""} · storage{" "}
              {(Number(m.storage_bytes) / 1e6).toFixed(0)} MB · joined{" "}
              {new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(new Date(m.created_at))}
            </p>
            {m.role === "member" && (
              <MemberForm userId={m.user_id} status={m.status}
                          limitRupees={m.monthly_limit_paise === null ? null : m.monthly_limit_paise / 100} />
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
