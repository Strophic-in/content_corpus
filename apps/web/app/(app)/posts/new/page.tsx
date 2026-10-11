import { workspace } from "@/lib/channels";
import { requireUser } from "@/lib/session";

import { PostForm } from "../post-form";

export const metadata = { title: "New post · Content Corpus" };

export default async function NewPostPage({ searchParams }: { searchParams: Promise<{ date?: string }> }) {
  const user = await requireUser();
  const { active, formats } = await workspace(user.id);
  const { date } = await searchParams;
  return (
    <div className="mx-auto flex max-w-xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New post</h1>
        <p className="mt-1 text-sm text-muted">
          For {active.name}. Describe the idea; the script — hook, narration and shots — is written next.
          Or let the agent suggest ideas in Discover.
        </p>
      </div>
      <div className="rounded-xl border border-border bg-surface p-5">
        <PostForm formats={formats} defaults={{ slot_date: date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : "",
                                                publish_time: active.default_publish_time }} />
      </div>
    </div>
  );
}
