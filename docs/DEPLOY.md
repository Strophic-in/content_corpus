# Deploying — the strophic VM

Everything runs on one always-on box (an Oracle Cloud Ampere A1: arm64, Ubuntu
24.04, Docker), next to the services already there:

| What | Where |
|---|---|
| Web app | container `web` → `127.0.0.1:3400` → nginx → `https://content-corpus.strophic.in` |
| cpu lane (scripts, narration, segments, assembly) | container `worker-cpu` |
| gpu lane (rents Race GPUs over the API + SSH) | container `worker-gpu` |
| Database | VibeDB's Postgres on the host, reached as `host.docker.internal` |
| Kokoro voice model | Voicer's `backend/models/`, mounted read-only (one copy on the box) |
| Media | Cloudflare R2 |

The containers publish nothing except the web app on localhost. The web app and
the workers wake each other over the compose network
(`http://worker-cpu:8787/wake`, `http://worker-gpu:8788/wake`). All three have
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
   - `CORPUS_WAKE_URL=http://worker-cpu:8787/wake,http://worker-gpu:8788/wake`
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

## Notes

- **Whisper** (word timings) downloads its model, about 500 MB, into the
  `corpus-cache` volume on first use.
- **Segments waiting for assembly** live in the same volume and are deleted once
  each reel is stored.
- **Pods without the models:** the gpu worker records Race pods that turned out
  to lack the models in `corpus-cache/content_corpus/race_pods.json`. Delete
  that file to make it try them again.
- **CPU:** the box has 2 cores. Encoding a shot segment takes noticeably longer
  here than on a desktop, but still less than the GPU spends per shot.
