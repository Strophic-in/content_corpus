# Content Corpus — web app

The owner's dashboard: sign in, plan posts on a calendar, review and approve
scripts, start renders, watch progress and play or download finished reels.
See the [repository README](../../README.md) for how it fits with the workers.

- Next.js 16 (App Router; `proxy.ts` replaces middleware), React 19, Tailwind CSS 4.
- Auth: Better Auth (`lib/auth.ts`); sign-up is limited to `AUTH_ALLOWED_EMAILS`.
- Data: `lib/db.ts` connects as the restricted `corpus_web` role and sets
  `app.user_id` per transaction, so row-level security scopes every query.
  Changes go through `api.*` database functions, never raw table writes.
- Configuration comes from the repo-root `.env` (loaded by `lib/env.ts`).

```bash
npm install
npx next dev            # http://localhost:3000 (Windows: add --webpack if Turbopack crashes)
npm run build && npm start
```
