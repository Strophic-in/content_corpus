import "server-only";

import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

// AES-256-GCM secret vault — must stay byte-compatible with worker/corpus/crypto.py.
// A secret is one self-describing string:
//
//     v1.<base64(12-byte nonce)>.<base64(ciphertext || 16-byte GCM tag)>
//
// Python's AESGCM appends the tag to the ciphertext, so here the cipher output is
// concatenated with getAuthTag() to match.

const PREFIX = "v1";
const NONCE_BYTES = 12;
const TAG_BYTES = 16;

function key(): Buffer {
  const raw = process.env.APP_ENCRYPTION_KEY;
  if (!raw) throw new Error("APP_ENCRYPTION_KEY is not set");
  const k = Buffer.from(raw, "base64");
  if (k.length !== 32) throw new Error(`APP_ENCRYPTION_KEY must decode to 32 bytes, got ${k.length}`);
  return k;
}

export function encrypt(plaintext: string): string {
  const nonce = randomBytes(NONCE_BYTES);
  const cipher = createCipheriv("aes-256-gcm", key(), nonce);
  const ct = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final(), cipher.getAuthTag()]);
  return [PREFIX, nonce.toString("base64"), ct.toString("base64")].join(".");
}

export function decrypt(stored: string): string {
  const parts = stored.split(".");
  if (parts.length !== 3 || parts[0] !== PREFIX) {
    throw new Error(`unrecognised secret format (prefix ${JSON.stringify(parts[0])})`);
  }
  const nonce = Buffer.from(parts[1], "base64");
  const body = Buffer.from(parts[2], "base64");
  if (nonce.length !== NONCE_BYTES) throw new Error(`nonce must be ${NONCE_BYTES} bytes`);
  const decipher = createDecipheriv("aes-256-gcm", key(), nonce);
  decipher.setAuthTag(body.subarray(body.length - TAG_BYTES));
  return Buffer.concat([decipher.update(body.subarray(0, body.length - TAG_BYTES)), decipher.final()])
    .toString("utf8");
}
