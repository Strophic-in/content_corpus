import { headers } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/lib/auth";
import { asUser } from "@/lib/db";
import { signedUrl } from "@/lib/r2";

// A post's footage file (the original or its AI version), for the post page. Like
// a card's media: redirected to a fresh signed link on each load.
export async function GET(_req: NextRequest, ctx: RouteContext<"/media/asset/[id]">) {
  const { id } = await ctx.params;
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return new NextResponse(null, { status: 401 });
  if (!/^[0-9a-f-]{36}$/i.test(id)) return new NextResponse(null, { status: 404 });
  const key = await asUser(session.user.id, async (db) =>
    (await db.query("select key from assets where id = $1", [id])).rows[0]?.key as string | null | undefined);
  const url = key ? await signedUrl(key, 3600) : null;
  if (!url) return new NextResponse(null, { status: 404 });
  return NextResponse.redirect(url, { status: 302, headers: { "Cache-Control": "private, max-age=600" } });
}
