import Link from "next/link";

import { requireUser } from "@/lib/session";
import { userSettings } from "@/lib/posts";

import { SignOutButton } from "../sign-out-button";
import { KeyForm, SettingsForm } from "./settings-forms";

export const metadata = { title: "Settings · Content Corpus" };

export default async function SettingsPage() {
  const user = await requireUser();
  const { settings, keys } = await userSettings(user.id);
  const openai = keys.find((k) => k.name === "openai");

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>

      <section className="rounded-xl border border-border bg-surface p-5">
        <h2 className="font-medium">OpenAI API key</h2>
        <p className="mt-1 text-sm text-muted">
          Used by the worker to write scripts. Stored encrypted; it can be replaced but never shown again.
        </p>
        <p className="mt-3 text-sm">
          {openai ? (
            <>Saved · last changed {new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeZone: settings.timezone }).format(openai.updated_at)}</>
          ) : (
            <span className="text-warn">Not set — scripts can’t be written until it is.</span>
          )}
        </p>
        <div className="mt-3"><KeyForm hasKey={Boolean(openai)} /></div>
      </section>

      <SettingsForm settings={settings} />

      <section className="flex items-center gap-3 rounded-xl border border-border bg-surface p-5">
        <div className="min-w-0 flex-1">
          <h2 className="font-medium">Account</h2>
          <p className="truncate text-sm text-muted">{user.email}</p>
        </div>
        <SignOutButton />
      </section>

      <Link href="/dashboard" className="rounded-xl border border-border bg-surface p-5 transition hover:border-accent">
        <h2 className="font-medium">System status →</h2>
        <p className="mt-1 text-sm text-muted">Workers, storage used against the 9 GB cap, and posts by status.</p>
      </Link>
    </div>
  );
}
