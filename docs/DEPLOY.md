# Deploying — the strophic VM

Everything runs on one always-on box (an Oracle Cloud Ampere A1: arm64, Ubuntu
24.04, Docker), next to the services already there:

| What | Where |
|---|---|
| Web app | container `web` → `127.0.0.1:3400` → nginx → `https://content-corpus.strophic.in` |
| cpu lane (scripts, narration, segments, assembly) | container `worker-cpu` |
| gpu lane (rents Race GPUs over the API + SSH) | container `worker-gpu` |
| publish lane (posts reels to YouTube and Instagram) | container `worker-publish` |
| ideas lane (Reddit, news sites, trends; card media) | container `worker-ideas` |
| Database | VibeDB's Postgres on the host, reached as `host.docker.internal` |
| Kokoro voice model | Voicer's `backend/models/`, mounted read-only (one copy on the box) |
| Idea memory (Qdrant) | HealMem's Qdrant, collection `content_corpus_memory`; worker-cpu joins the `healmem_vector` network |
| Media | Cloudflare R2 |

The containers publish nothing except the web app on localhost. The web app and
the workers wake each other over the compose network
(`http://worker-cpu:8787/wake`, `http://worker-gpu:8788/wake`,
`http://worker-publish:8789/wake,http://worker-ideas:8790/wake`, `http://worker-ideas:8790/wake`). All of them have
`cpu_shares: 512`, so they yield to the box's other services under contention
and use the whole CPU when it is idle.

## Updating

```bash
~/strophic/content_corpus/deploy/deploy.sh     # pull, migrate, build, restart
cd ~/strophic/content_corpus/deploy
docker compose --env-file ../.env ps
docker compose --env-file ../.env logs -f --tail 50 worker-gpu
```

Always pass `--env-file ../.env`: compose reads `KOKORO_MODELS_DIR` from it.
To roll back, `git checkout <sha>` in the checkout and run the build/up steps
from `deploy.sh` by hand.

## First-time setup

Run these as the deploy user (`hafeez`, in the `docker` group) unless marked `sudo`.

1. **Code**
   ```bash
   git clone https://github.com/Strophic-in/content_corpus.git ~/strophic/content_corpus
   ```

2. **`.env`** at the repo root (mode 600). Start from your working `.env`, then
   change these for the box:
   - `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `WEB_DATABASE_URL`: host
     `host.docker.internal` (same ports 6432/5432) and `sslmode=disable`. The
     connection never leaves the machine, and VibeDB allows plain connections
     only from Docker's private range.
   - `BETTER_AUTH_URL=https://content-corpus.strophic.in`
   - `CORPUS_WAKE_URL=http://worker-cpu:8787/wake,http://worker-gpu:8788/wake,http://worker-publish:8789/wake`
   - `KOKORO_MODELS_DIR=/home/hafeez/strophic/voicer/backend/models`
     (it must hold `kokoro-v1.0.onnx` and `voices-v1.0.bin`).

3. **Race SSH key.** This is the private key whose public half is registered
   with Race. The gpu worker runs as uid 10001.
   ```bash
   mkdir -p secrets
   sudo install -o 10001 -g 10001 -m 600 /path/to/id_ed25519 secrets/race_ssh_key
   ```

4. **DNS.** In Cloudflare, add an A record `content-corpus` → the VM's public IP
   (proxied is fine). Don't look the name up before the record exists:
   resolvers cache "not found" for 30 minutes (the zone's negative TTL).

5. **nginx + certificate** (`sudo`)
   ```bash
   # a port-80-only block first, so certbot can answer the challenge
   printf 'server { listen 80; listen [::]:80; server_name content-corpus.strophic.in; location / { return 404; } }\n' \
     > /etc/nginx/sites-available/content-corpus.strophic.in
   ln -s /etc/nginx/sites-available/content-corpus.strophic.in /etc/nginx/sites-enabled/
   nginx -t && systemctl reload nginx
   certbot certonly --nginx -d content-corpus.strophic.in
   cp deploy/nginx/content-corpus.strophic.in.conf /etc/nginx/sites-available/content-corpus.strophic.in
   nginx -t && systemctl reload nginx
   ```

6. **Start:** `deploy/deploy.sh`

7. **Retire any other workers** (for example on a laptop) so only these lanes
   claim jobs. The web app's sign-in session starts fresh on the new domain.

## Connecting YouTube and Instagram (Channels → Connect)

Both use standard OAuth. The owner clicks Connect on a channel and approves on
Google's or Instagram's own page, and the token is stored encrypted. Each platform
needs a developer app, set up once: put its keys in the VM's .env and redeploy.

**YouTube** (Google Cloud console):
1. Create a project and enable **YouTube Data API v3**.
2. In Google Auth Platform, set up Branding and Audience as an external app, with
   your email as a test user. Under Data access, add the youtube.upload and
   youtube.readonly scopes. Set the publishing status to **In production**: while
   it is "Testing", Google expires refresh tokens after 7 days. You will see an
   "unverified app" warning; that is expected for a personal app.
3. Under Clients, create a **Web application** client with these redirect URIs:
   - https://content-corpus.strophic.in/api/connect/youtube/callback
   - https://content-corpus.strophic.in/api/auth/callback/google (for Google sign-in)
4. In .env, set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.

**Instagram** (Meta for Developers, "Instagram API with Instagram Login"):
1. The Instagram account must be a Professional (Creator or Business) account.
2. Create a Business-type app with the Instagram use case. Under Instagram, in API
   setup with Instagram login, set the redirect URI
   https://content-corpus.strophic.in/api/connect/instagram/callback.
3. Under App roles, add the Instagram account as an Instagram tester, then accept
   the invite in the Instagram app. Development mode is enough for your own account.
4. In .env, set INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET. These are the Instagram
   app's ID and secret, not the Facebook app's.

## Notes

- The idea agent's embedding model (bge-small, about 34 MB) downloads into the
  corpus-cache volume on first use. Ideas are kept for 30 days unless accepted.
- **Whisper** (word timings) downloads its model, about 500 MB, into the
  `corpus-cache` volume on first use.
- **Segments waiting for assembly** live in the same volume and are deleted once
  each reel is stored.
- **Pods without the models:** the gpu worker records Race pods that turned out
  to lack the models in `corpus-cache/content_corpus/race_pods.json`. Delete
  that file to make it try them again.
- **CPU:** the box has 2 cores. Encoding a shot segment takes noticeably longer
  here than on a desktop, but still less than the GPU spends per shot.
