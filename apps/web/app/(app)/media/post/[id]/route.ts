import { headers } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/lib/auth";
import { asUser } from "@/lib/db";
import { signedUrl } from "@/lib/r2";

// A finished post's video, (?slide=1) its first slide for the Library grid, or
// (?cover=1) the cover it goes out with.
// Like a card's media: redirected to a fresh signed link on each load.
export async function GET(req: NextRequest, ctx: RouteContext<"/media/post/[id]">) {
  const { id } = await ctx.params;
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return new NextResponse(null, { status: 401 });
  if (!/^[0-9a-f-]{36}$/i.test(id)) return new NextResponse(null, { status: 404 });
  const post = await asUser(session.user.id, async (db) =>
    (await db.query("select final_key, slides, package->>'thumbnail_key' as cover from posts where id = $1",
                    [id])).rows[0] as
      | { final_key: string | null; slides: { key: string }[] | null; cover: string | null } | undefined);
  const q = req.nextUrl.searchParams;
  const key = q.has("cover") ? post?.cover : q.has("slide") ? post?.slides?.[0]?.key : post?.final_key;
  const url = key ? await signedUrl(key, 3600) : null;
  if (!url) return new NextResponse(null, { status: 404 });
  return NextResponse.redirect(url, { status: 302, headers: { "Cache-Control": "private, max-age=600" } });
}
