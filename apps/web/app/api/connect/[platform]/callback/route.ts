import { headers } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/lib/auth";
import { origin } from "@/lib/site";
import { encrypt } from "@/lib/crypto";
import { asUser } from "@/lib/db";
import { AccountMismatch, exchange, NONCE_COOKIE, PLATFORMS, readState, type IgApi, type Platform } from "@/lib/oauth";

// The provider sends the owner back here after they approve (or decline).
export async function GET(req: NextRequest, ctx: RouteContext<"/api/connect/[platform]/callback">) {
  const { platform } = await ctx.params;
  if (!PLATFORMS.includes(platform as Platform)) return NextResponse.redirect(new URL("/channels", origin(req)));
  const p = platform as Platform;
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.redirect(new URL("/login", origin(req)));

  const q = req.nextUrl.searchParams;
  const state = readState(q.get("state"), req.cookies.get(NONCE_COOKIE)?.value, p);
  if (!state || state.u !== session.user.id) {
    return NextResponse.redirect(new URL("/channels?connect_error=That+connection+link+expired+—+try+again.", origin(req)));
  }
  const back = new URL(`/channels/${state.c}`, origin(req));
  const done = (key: string, value: string) => {
    back.searchParams.set(key, value);
    const res = NextResponse.redirect(back);
    res.cookies.delete({ name: NONCE_COOKIE, path: "/api/connect" });
    return res;
  };
  if (q.get("error") || !q.get("code")) return done("connect_error", "You didn't approve the connection.");

  const api: IgApi | undefined = p === "instagram" ? (state.a ?? "instagram_login") : undefined;
  let current: { external_id: string; handle: string | null; api: IgApi } | undefined;
  try {
    // A reconnect must be the account the channel already has, if it has one: a Unified
    // login may not silently switch to another account.
    if (p === "instagram") current = await asUser(session.user.id, async (db) =>
      (await db.query("select external_id, handle, api from channel_accounts where channel_id = $1 and platform = 'instagram'",
                      [state.c])).rows[0] as typeof current);
    const keepId = current ? String(current.external_id) : null;
    const acc = await exchange(p, q.get("code")!, api, keepId);
    await asUser(session.user.id, (db) => db.query(
      `insert into channel_accounts (user_id, channel_id, platform, external_id, handle, display_name, avatar_url,
                                     token_ciphertext, token_expires_at, scopes, status, updated_at, api)
       values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'connected', now(), $11)
       on conflict (channel_id, platform) do update set
         external_id = $4, handle = $5, display_name = $6, avatar_url = $7, token_ciphertext = $8,
         token_expires_at = $9, scopes = $10, status = 'connected', updated_at = now(), api = $11`,
      [session.user.id, state.c, p, acc.externalId, acc.handle, acc.displayName, acc.avatarUrl,
       encrypt(acc.token), acc.expiresAt, acc.scopes, acc.api ?? "instagram_login"]));
    return done("connected", p);
  } catch (err) {
    if (err instanceof AccountMismatch) {
      const was = current?.handle ? `log in with ${current.handle}` : "log in with the account this channel was connected to";
      return done("connect_error", `That isn't the Instagram account this channel was connected to — ${was} or disconnect first.`);
    }
    console.warn(`connect ${p} failed:`, (err as Error).message);
    return done("connect_error", (err as Error).message.slice(0, 200));
  }
}
