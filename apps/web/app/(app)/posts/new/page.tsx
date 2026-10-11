import { requireUser } from "@/lib/session";

import { PostForm } from "../post-form";

export const metadata = { title: "New post · Content Corpus" };

export default async function NewPostPage({ searchParams }: { searchParams: Promise<{ date?: string }> }) {
  await requireUser();
  const { date } = await searchParams;
  return (
    <div className="mx-auto flex max-w-xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New post</h1>
        <p className="mt-1 text-sm text-muted">
          Describe the idea. The script — hook, dialogue and shots — is written in the next step.
        </p>
      </div>
      <div className="rounded-xl border border-border bg-surface p-5">
        <PostForm defaults={{ slot_date: date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : "" }} />
      </div>
    </div>
  );
}
