import "server-only";

import path from "node:path";

import { config } from "dotenv";

// One .env for the whole repo (web, worker, db/migrate.py), at the root. Loaded
// here, from server code, because Next resets process.env inside its build and
// render workers — loading it in next.config.ts is silently undone there, and
// Better Auth would fall back to its default secret. On Vercel there is no file;
// the project's environment variables apply and this is a no-op.
config({ path: path.resolve(process.cwd(), "../../.env"), override: false, quiet: true });
