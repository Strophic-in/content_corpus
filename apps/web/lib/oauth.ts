import "server-only";

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import "./env";

// Connecting a channel's YouTube and Instagram accounts: the standard OAuth
// authorization-code flow. The owner clicks Connect, approves on Google's or
// Instagram's own page, and the callback stores the long-lived credential
// encrypted (channel_accounts.token_ciphertext, write-only to the web).

export type Platform = "youtube" | "instagram";
export const PLATFORMS: Platform[] = ["youtube", "instagram"];

// Instagram has two APIs: Instagram Login (members) and Unified Login via
// Facebook (the owner only: Meta offers trending music only through it).
export type IgApi = "unified" | "instagram_login";

const base = () => (process.env.BETTER_AUTH_URL ?? "").replace(/\/$/, "");
export const redirectUri = (p: Platform) => `${base()}/api/connect/${p}/callback`;

export const instagramLoginConfigured = () =>
  Boolean(process.env.INSTAGRAM_APP_ID && process.env.INSTAGRAM_APP_SECRET);
export const unifiedConfigured = () =>
  Boolean(process.env.META_APP_ID && process.env.META_APP_SECRET && process.env.META_IG_CONFIG_ID);

export function configured(p: Platform): boolean {
  return p === "youtube"
    ? Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET)
    : instagramLoginConfigured() || unifiedConfigured();
}

// ── state: signed, short-lived, and tied to this browser by a nonce cookie ────
export const NONCE_COOKIE = "cc_oauth_nonce";
type State = { u: string; c: string; p: Platform; n: string; t: number; a?: IgApi };

const sign = (data: string) =>
  createHmac("sha256", `${process.env.BETTER_AUTH_SECRET}:oauth-state`).update(data).digest("base64url");

export function newState(userId: string, channelId: string, p: Platform, api?: IgApi) {
  const n = randomBytes(16).toString("base64url");
  const body = Buffer.from(JSON.stringify({ u: userId, c: channelId, p, n, t: Date.now(), a: api } satisfies State))
    .toString("base64url");
  return { state: `${body}.${sign(body)}`, nonce: n };
}

export function readState(token: string | null, nonce: string | undefined, p: Platform): State | null {
  if (!token || !nonce) return null;
  const [body, sig] = token.split(".");
  const want = Buffer.from(sign(body ?? ""));
  if (!sig || want.length !== sig.length || !timingSafeEqual(want, Buffer.from(sig))) return null;
  const s = JSON.parse(Buffer.from(body, "base64url").toString()) as State;
  if (s.p !== p || s.n !== nonce || Date.now() - s.t > 15 * 60_000) return null;
  return s;
}

// ── providers ─────────────────────────────────────────────────────────────────
// force-ssl: the first comment under each Short (commentThreads.insert needs it).
const YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly",
  "https://www.googleapis.com/auth/youtube.force-ssl"];
const IG_SCOPES = ["instagram_business_basic", "instagram_business_content_publish"];

export function authorizeUrl(p: Platform, state: string, api?: IgApi): string {
  if (p === "youtube") {
    const q = new URLSearchParams({
      client_id: process.env.GOOGLE_CLIENT_ID!, redirect_uri: redirectUri(p), response_type: "code",
      scope: YT_SCOPES.join(" "), access_type: "offline", prompt: "consent", include_granted_scopes: "true", state,
    });
    return `https://accounts.google.com/o/oauth2/v2/auth?${q}`;
  }
  if (api === "unified") {
    // The configuration in Meta's app decides the permissions, so no scope here.
    const q = new URLSearchParams({
      client_id: process.env.META_APP_ID!, config_id: process.env.META_IG_CONFIG_ID!, redirect_uri: redirectUri(p),
      response_type: "code", state,
    });
    return `https://www.facebook.com/v27.0/dialog/oauth?${q}`;
  }
  const q = new URLSearchParams({
    client_id: process.env.INSTAGRAM_APP_ID!, redirect_uri: redirectUri(p), response_type: "code",
    scope: IG_SCOPES.join(","), state,
  });
  return `https://www.instagram.com/oauth/authorize?${q}`;
}

export type Connected = {
  externalId: string; handle: string | null; displayName: string | null; avatarUrl: string | null;
  token: string; expiresAt: Date | null; scopes: string[]; api: IgApi | null;
};

// The owner's reconnect landed on a different Instagram account than the channel has.
export class AccountMismatch extends Error {}

async function json(r: Response, what: string) {
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    // The provider's error code only; never tokens or secrets.
    const code = body?.error?.message ?? body?.error_message ?? body?.error_description ?? body?.error ?? r.status;
    throw new Error(`${what} failed: ${typeof code === "string" ? code : JSON.stringify(code)}`);
  }
  return body;
}

export async function exchange(p: Platform, code: string, api?: IgApi, keepId?: string | null): Promise<Connected> {
  if (p === "youtube") {
    const tok = await json(await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      body: new URLSearchParams({ code, client_id: process.env.GOOGLE_CLIENT_ID!, client_secret: process.env.GOOGLE_CLIENT_SECRET!,
                                  redirect_uri: redirectUri(p), grant_type: "authorization_code" }),
    }), "Google token exchange");
    if (!tok.refresh_token) throw new Error("Google did not return a refresh token — remove the app's access in your Google account and connect again");
    const ch = await json(await fetch("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true", {
      headers: { Authorization: `Bearer ${tok.access_token}` },
    }), "Reading your YouTube channel");
    const item = ch.items?.[0];
    if (!item) throw new Error("This Google account has no YouTube channel");
    return {
      externalId: item.id, handle: item.snippet?.customUrl ?? null, displayName: item.snippet?.title ?? null,
      avatarUrl: item.snippet?.thumbnails?.default?.url ?? null, token: tok.refresh_token, expiresAt: null,
      scopes: String(tok.scope ?? "").split(" ").filter(Boolean), api: null,
    };
  }
  if (api === "unified") return unifiedExchange(p, code, keepId ?? null);
  const tok = await json(await fetch("https://api.instagram.com/oauth/access_token", {
    method: "POST",
    body: new URLSearchParams({ client_id: process.env.INSTAGRAM_APP_ID!, client_secret: process.env.INSTAGRAM_APP_SECRET!,
                                grant_type: "authorization_code", redirect_uri: redirectUri(p), code }),
  }), "Instagram token exchange");
  // Meta documents this reply wrapped in a `data` list but has sent it flat too.
  const short = tok.data?.[0] ?? tok;
  if (!short.access_token) throw new Error("Instagram token exchange returned no token");
  const long = await json(await fetch(`https://graph.instagram.com/access_token?${new URLSearchParams({
    grant_type: "ig_exchange_token", client_secret: process.env.INSTAGRAM_APP_SECRET!, access_token: short.access_token,
  })}`), "Instagram long-lived token");
  const me = await json(await fetch(`https://graph.instagram.com/me?${new URLSearchParams({
    fields: "user_id,username,name,profile_picture_url", access_token: long.access_token,
  })}`), "Reading your Instagram profile");
  return {
    externalId: String(me.user_id ?? short.user_id), handle: me.username ? `@${me.username}` : null,
    displayName: me.name ?? me.username ?? null, avatarUrl: me.profile_picture_url ?? null, token: long.access_token,
    expiresAt: new Date(Date.now() + Number(long.expires_in ?? 5_184_000) * 1000),
    scopes: Array.isArray(short.permissions) ? short.permissions : String(short.permissions ?? "").split(","),
    api: "instagram_login",
  };
}

// Unified Login: one Facebook token, then the Instagram account Meta assigned to the app.
async function unifiedExchange(p: Platform, code: string, keepId: string | null): Promise<Connected> {
  const tok = await json(await fetch(`https://graph.facebook.com/v27.0/oauth/access_token?${new URLSearchParams({
    client_id: process.env.META_APP_ID!, client_secret: process.env.META_APP_SECRET!,
    redirect_uri: redirectUri(p), code,
  })}`), "Instagram token exchange");
  if (!tok.access_token) throw new Error("Instagram token exchange returned no token");
  const assigned = await json(await fetch(`https://graph.facebook.com/v27.0/me/assigned_instagram_accounts?${new URLSearchParams({
    fields: "id,username", access_token: tok.access_token,
  })}`), "Reading your Instagram accounts");
  const accounts: { id: string | number; username?: string }[] = assigned.data ?? [];
  if (accounts.length === 0) throw new Error("This Facebook login has no Instagram account assigned to the app");
  // A reconnect keeps the account the channel already has, if the owner logs in with it.
  const pick = keepId ? accounts.find((a) => String(a.id) === keepId) : accounts[0];
  if (!pick) throw new AccountMismatch("different Instagram account");
  const id = encodeURIComponent(String(pick.id));
  const me = await json(await fetch(`https://graph.facebook.com/v27.0/${id}?${new URLSearchParams({
    fields: "username,name,profile_picture_url", access_token: tok.access_token,
  })}`), "Reading your Instagram profile");
  const username = me.username ?? pick.username;
  const expiresIn = Number(tok.expires_in ?? 0);
  return {
    externalId: String(pick.id), handle: username ? `@${username}` : null,
    displayName: me.name ?? username ?? null, avatarUrl: me.profile_picture_url ?? null, token: tok.access_token,
    expiresAt: expiresIn > 0 ? new Date(Date.now() + expiresIn * 1000) : null, scopes: [], api: "unified",
  };
}
