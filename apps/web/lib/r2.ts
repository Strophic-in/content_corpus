import "server-only";

import { GetObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

import "./env";

// The bucket is private. The web app only ever *reads*, through short-lived
// signed URLs, so a link that leaks stops working within the hour.
let client: S3Client | null = null;

function r2(): S3Client | null {
  const account = process.env.R2_ACCOUNT_ID;
  const key = process.env.R2_ACCESS_KEY_ID;
  const secret = process.env.R2_SECRET_ACCESS_KEY;
  if (!account || !key || !secret) return null;
  client ??= new S3Client({
    region: "auto",
    endpoint: `https://${account}.r2.cloudflarestorage.com`,
    credentials: { accessKeyId: key, secretAccessKey: secret },
  });
  return client;
}

/** A signed GET URL for a stored object, or null when R2 is not configured. */
export async function signedUrl(key: string, seconds = 3600, downloadAs?: string): Promise<string | null> {
  const c = r2();
  if (!c) return null;
  return getSignedUrl(
    c,
    new GetObjectCommand({
      Bucket: process.env.R2_BUCKET || "content-corpus-media",
      Key: key,
      ResponseContentDisposition: downloadAs ? `attachment; filename="${downloadAs}"` : undefined,
    }),
    { expiresIn: seconds },
  );
}
