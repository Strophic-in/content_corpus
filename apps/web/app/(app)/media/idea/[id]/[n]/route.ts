import { headers } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/lib/auth";
import { asUser } from "@/lib/db";
import { signedUrl } from "@/lib/r2";

// A card's picture or video (?poster=1 for a video's poster frame). The bucket is
// private and signed links expire within the hour, while a deck can stay open far
// longer: the card points here and each load is redirected to a fresh link.
export async function GET(req: NextRequest, ctx: RouteContext<"/media/idea/[id]/[n]">) {
  const { id, n } = await ctx.params;
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return new NextResponse(null, { status: 401 });
  if (!/^[0-9a-f-]{36}$/i.test(id) || !/^\d{1,2}$/.test(n)) return new NextResponse(null, { status: 404 });
  const media = await asUser(session.user.id, async (db) =>
    (await db.query("select media from ideas where id = $1", [id])).rows[0]?.media as
      | { key?: string; poster_key?: string }[] | undefined);
  const m = media?.[Number(n)];
  const key = req.nextUrl.searchParams.has("poster") ? m?.poster_key : m?.key;
  const url = key ? await signedUrl(key, 3600) : null;
  if (!url) return new NextResponse(null, { status: 404 });
  return NextResponse.redirect(url, { status: 302, headers: { "Cache-Control": "private, max-age=600" } });
}
