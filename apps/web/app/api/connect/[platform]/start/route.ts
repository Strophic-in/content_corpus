import { headers } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/lib/auth";
import { origin } from "@/lib/site";
import { asUser } from "@/lib/db";
import { membership } from "@/lib/session";
import {
  authorizeUrl, configured, instagramLoginConfigured, type IgApi, newState, NONCE_COOKIE, PLATFORMS, type Platform,
  unifiedConfigured,
} from "@/lib/oauth";

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
  // Only the owner gets Unified Login (trending music); members keep Instagram Login.
  const m = await membership(session.user.id);
  const igApi: IgApi | undefined = p !== "instagram" ? undefined
    : unifiedConfigured() && m?.role === "owner" ? "unified" : "instagram_login";
  if (!configured(p) || (igApi === "instagram_login" && !instagramLoginConfigured())) {
    back.searchParams.set("connect_error", `${p === "youtube" ? "YouTube" : "Instagram"} isn't set up on the server yet.`);
    return NextResponse.redirect(back);
  }
  const owns = await asUser(session.user.id, async (db) =>
    (await db.query("select 1 from channels where id = $1", [channelId])).rowCount === 1);
  if (!owns) return NextResponse.redirect(new URL("/channels", origin(req)));

  const { state, nonce } = newState(session.user.id, channelId, p, igApi);
  const res = NextResponse.redirect(authorizeUrl(p, state, igApi));
  res.cookies.set(NONCE_COOKIE, nonce, { httpOnly: true, secure: true, sameSite: "lax", path: "/api/connect", maxAge: 900 });
  return res;
}
