import { headers } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { Readable } from "node:stream";

import { auth } from "@/lib/auth";
import { asUser } from "@/lib/db";
import { putStream } from "@/lib/r2";
import { membership } from "@/lib/session";
import { wakeWorker } from "@/lib/wake";

// One of the owner's own videos or photos, after api.start_upload made room for it
// (the startUpload action): the browser PUTs the file here and it streams on into
// the private bucket at the key that was reserved, exactly the size declared. Then
// the ideas worker normalises and analyses it (api.finish_upload). Outside proxy.ts,
// which would buffer the body: the session is checked here instead.
export async function PUT(req: NextRequest, ctx: RouteContext<"/api/upload/[assetId]">) {
  const { assetId } = await ctx.params;
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return NextResponse.json({ error: "Sign in again." }, { status: 401 });
  if ((await membership(session.user.id))?.status !== "active")
    return NextResponse.json({ error: "This account isn't active." }, { status: 403 });
  if (!/^[0-9a-f-]{36}$/i.test(assetId)) return NextResponse.json({ error: "Not found." }, { status: 404 });
  const a = await asUser(session.user.id, async (db) => (await db.query(
    `select kind, state, origin, bytes::text as bytes, fetch_from->>'upload_key' as key from assets where id = $1`,
    [assetId])).rows[0] as { kind: string; state: string; origin: string; bytes: string; key: string | null } | undefined);
  if (!a || a.origin !== "upload" || !a.key) return NextResponse.json({ error: "Not found." }, { status: 404 });
  if (a.state !== "uploading") return NextResponse.json({ error: "That upload already finished." }, { status: 409 });
  const length = Number(req.headers.get("content-length"));
  if (!req.body || length !== Number(a.bytes))
    return NextResponse.json({ error: "The file isn't the size that was announced — try again." }, { status: 400 });
  const type = req.headers.get("content-type") || (a.kind === "video" ? "video/mp4" : "image/jpeg");
  try {
    await putStream(a.key, Readable.fromWeb(req.body as Parameters<typeof Readable.fromWeb>[0]), length, type);
  } catch (err) {
    console.warn("upload to R2 failed", (err as Error)?.name);
    return NextResponse.json({ error: "Storing the file failed — try again." }, { status: 502 });
  }
  try {
    await asUser(session.user.id, (db) => db.query("select api.finish_upload($1)", [assetId]));
  } catch {
    return NextResponse.json({ error: "The file arrived but couldn't be queued — refresh the page." }, { status: 409 });
  }
  await wakeWorker();
  return NextResponse.json({ ok: true });
}
