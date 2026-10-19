import { headers } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/lib/auth";
import { origin } from "@/lib/site";
import { asUser } from "@/lib/db";
import { authorizeUrl, configured, newState, NONCE_COOKIE, PLATFORMS, type Platform } from "@/lib/oauth";

// "Connect YouTube / Instagram" on a channel: off to the provider's consent page.
export async function GET(req: NextRequest, ctx: RouteContext<"/api/connect/[platform]/start">) {
  const { platform } = await ctx.params;
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.redirect(new URL("/login", origin(req)));
  const channelId = req.nextUrl.searchParams.get("channel") ?? "";
  const back = new URL(`/channels/${channelId}`, origin(req));
  if (!PLATFORMS.includes(platform as Platform) || !/^[0-9a-f-]{36}$/i.test(channelId))
    return NextResponse.redirect(new URL("/channels", origin(req)));
  const p = platform as Platform;
  if (!configured(p)) {
    back.searchParams.set("connect_error", `${p === "youtube" ? "YouTube" : "Instagram"} isn't set up on the server yet.`);
    return NextResponse.redirect(back);
  }
  const owns = await asUser(session.user.id, async (db) =>
    (await db.query("select 1 from channels where id = $1", [channelId])).rowCount === 1);
  if (!owns) return NextResponse.redirect(new URL("/channels", origin(req)));

  const { state, nonce } = newState(session.user.id, channelId, p);
  const res = NextResponse.redirect(authorizeUrl(p, state));
  res.cookies.set(NONCE_COOKIE, nonce, { httpOnly: true, secure: true, sameSite: "lax", path: "/api/connect", maxAge: 900 });
  return res;
}
