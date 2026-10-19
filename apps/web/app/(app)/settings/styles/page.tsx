import Link from "next/link";

import { asUser } from "@/lib/db";
import { requireUser } from "@/lib/session";
import { captionStyles, thumbStyles } from "@/lib/styles";

import { StylesBoard } from "./styles-board";

export const metadata = { title: "Styles · Content Corpus" };

// Settings → Styles: the caption styles and cover layouts Jev picks from for each post.
export default async function StylesPage() {
  const user = await requireUser();
  const st = await asUser(user.id, async (db) => {
    await db.query("select api.ensure_settings()");
    return (await db.query("select caption_styles_enabled, thumb_styles_enabled from app_settings")).rows[0] as
      { caption_styles_enabled: string[]; thumb_styles_enabled: string[] };
  });
  const map = (kind: "caption" | "thumb") => (p: { id: string; name: string; description: string; families: string[] }) =>
    ({ id: p.id, name: p.name, description: p.description, families: p.families, preview: `/styles/${kind}-${p.id}.jpg` });
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div>
        <Link href="/settings" className="text-sm text-muted hover:text-foreground">← Settings</Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Styles</h1>
        <p className="mt-1 text-sm text-muted">Captions and covers. Switch on the ones you like; for each video Jev picks
          the best fit for its story and title. Meme and ad styles are for meme and ad formats.</p>
      </div>
      <StylesBoard captions={captionStyles().map(map("caption"))} thumbs={thumbStyles().map(map("thumb"))}
                   captionsOn={st.caption_styles_enabled} thumbsOn={st.thumb_styles_enabled} />
    </div>
  );
}
