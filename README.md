# Content Corpus

**Plan, script, render and publish AI-animated YouTube Shorts on a shoestring.**

Every morning an idea agent reads free trend feeds and suggests video ideas as
cards you swipe: right to schedule one, left to skip it. You can also add topics
to the calendar yourself. OpenAI writes each one up as a short script, and you
approve it. Rented GPUs then render the shots with LTX-2.5. A local
voice model narrates, captions are timed to the word, and a finished 9:16 reel is
ready to download. Publishing to YouTube Shorts comes next. A 40-second reel costs
about **₹15 of GPU time** and is ready a few minutes after you click *Render*.

> Status: owner-only and in active development. Planning, scripting, rendering and
> assembly work end to end. YouTube publishing and the production deploy are in
> progress.

---

## What it does

- **Channels**: run several YouTube and Instagram channels, each with its own
  niche, audience, voice, timezone and connected accounts. Connecting an account is
  standard OAuth: click Connect, then approve.
- **Prompt library**: every prompt that shapes a video lives in a *format*: the
  idea agent's prompt, the script writer's prompt, the look of every shot, and the
  trend sources. You edit them in the app, with full version history and one-tap
  restore.
- **Discover**: an idea agent reads free feeds (Wikipedia most-read, Google Trends,
  science news, Reddit TIL and others) and suggests ideas as swipeable cards. It
  remembers what was made, suggested and skipped (local embeddings plus Qdrant), so
  it never repeats itself, and it learns from the reasons you give for skipping.
- **Many posts a day**, each at its own time, on a calendar per channel.
- **Installable app**: on a phone it opens full-screen with a bottom tab bar.

## How a reel is made

```mermaid
flowchart LR
    A["Calendar slot<br/>topic + brief"] -->|Write script| B["OpenAI<br/>script + self-review"]
    B -->|you approve| C["Plan shots<br/>prompts, seeds, sizes"]
    C --> D["Narrate<br/>Kokoro TTS + Whisper timings"]
    D -->|Render| E["Rent GPUs on Race<br/>LTX-2.5 in ComfyUI"]
    E -->|each shot as it lands| F["Caption + encode<br/>the shot"]
    F --> G["Join, loudness-normalise<br/>reel stored in R2"]
    G --> H["Preview, download<br/>YouTube Shorts"]
```

Every step is a job in a Postgres queue, run by one of two worker processes
(*lanes*):

| Job | Lane | What it does |
|---|---|---|
| `write_script` | cpu | OpenAI writes the script (hook, shots, narration, look) and an honest self-review. |
| `plan_shots` | cpu | Turns the approved script into shot prompts with fixed seeds, sized for LTX (704×1280, 8n+1 frames). |
| `narrate` | cpu | Kokoro voices each line on the CPU. Each line's length sets its shot's length, and Whisper times every word for the captions. |
| `render_post` | gpu | Rents the cheapest usable GPU (and a second one if a cached pod is free), drives ComfyUI over an SSH tunnel, and uploads each shot. The pod is always paused afterwards. |
| `build_segment` | cpu | While the GPU renders the next shot, burns captions into the finished one and cuts its sound to the frame. |
| `assemble` | cpu | Joins the segments (no re-encode), normalises the loudness to −14 LUFS once, and stores the reel. |

A post moves `draft → scripting → awaiting_approval → approved →
queued_for_render → rendering → rendered → post_processing → ready`, and the web
app shows each step as it happens.

## What keeps it cheap and fast

- **Paused pods keep their models.** LTX-2.5 is about 40 GB. A pod is *paused*, not
  deleted, after each render, so the next render resumes it in seconds instead of
  downloading again. A fresh host is checked for real free disk before a byte is
  written, and the models arrive as 16 parallel range downloads, each verified by
  its hash.
- **Two GPUs when they are free.** Pods take shots from one shared queue, longest
  first. A shot that runs out of memory on the smaller GPU moves to the bigger one,
  and a pod that drops hands its shots back.
- **Assembly happens during rendering.** Each shot is captioned and encoded the
  moment it lands, so the final step is a 5-second join, not a 2-minute encode.
- **No idle polling.** Workers sleep until the next job is due, or until the web
  app (or the other lane) wakes them over HTTP.
- **Storage has a hard cap.** Every upload reserves space in a ledger first, and at
  9 GB uploads stop and the app shows an alert.

## Repository layout

```
apps/web/          Next.js 16 app: login, calendar, script review, render progress, reel player
worker/            Python workers (one process per lane)
  corpus/handlers/   one module per job kind (table above)
  corpus/gpu/        Race pod acquisition, model setup, ComfyUI driving, the LTX-2.5 graph
  corpus/media/      Kokoro TTS, captions (ASS + bundled Montserrat), segment build and join
  corpus/runner.py   the lane loop: claim → run under a lease → finish; wake endpoint
  tests/             pipeline tests with fakes for OpenAI, S3, the GPU and ComfyUI
db/
  migrations/        numbered SQL migrations (schema, queue, storage ledger, RLS)
  access.sql         grants for the web role, re-applied on every migrate
  migrate.py         applies migrations (sha-tracked) + access.sql
  tests/             adversarial checks that the web role cannot get round its gates
  dev/test_db.sh     a throwaway Postgres for the tests
prompts/           the script-writing prompts (narrated explainer; characters speak)
docs/              DATABASE.md: setup, backups and restore
```

## Stack

| | |
|---|---|
| Web | Next.js 16 (App Router), React 19, Tailwind CSS 4, Better Auth (email + Google) |
| Database | PostgreSQL (self-hosted VibeDB) with row-level security, `SECURITY DEFINER` APIs and a job queue built on `FOR UPDATE SKIP LOCKED` |
| Workers | Python 3.11, psycopg 3, boto3, ffmpeg/libass, kokoro-onnx, faster-whisper |
| Video model | LTX-2.5 22B distilled (int8) in ComfyUI on [Race Engineering](https://raceengineering.ai) GPUs |
| Storage | Cloudflare R2 (private; the web app plays reels through short-lived signed URLs) |
| Scripts | OpenAI (the model is chosen in Settings; your key is encrypted at rest) |

## Security model

- **Sign-up is closed.** Only addresses in `AUTH_ALLOWED_EMAILS` can create an account.
- **The web app uses a separate database role.** It connects as `corpus_web`, whose
  reads are limited by row-level security (keyed on a per-transaction `app.user_id`)
  and column grants. Every state change goes through `api.*` functions that check
  the post's state. The workers use the owner role and `private.*` functions, which
  the web role cannot call.
- **Secrets are encrypted at rest.** Users' API keys are stored with AES-GCM under
  `APP_ENCRYPTION_KEY`.
- **GPU pods hold no credentials.** The worker drives each rented pod over SSH,
  closes the pod's public ComfyUI port, and keeps every database and R2 credential
  on the worker side.
- **Worker wake calls are authenticated.** The wake endpoints require a bearer token.

## Running it locally

Prerequisites: Node 22+, Python 3.11, `ffmpeg`/`ffprobe` with libass on `PATH`,
Docker (for the test database), and an SSH client whose key is registered with
Race (only the gpu lane needs it).

```bash
cp .env.example .env                      # fill in; see comments in the file

# Workers + migrations
python -m venv worker/.venv
worker/.venv/bin/pip install -r worker/requirements.txt -r worker/requirements-dev.txt
worker/.venv/bin/python db/migrate.py     # needs DATABASE_URL_UNPOOLED

# Web app → http://localhost:3000
cd apps/web && npm install && npx next dev   # on Windows, add --webpack if Turbopack crashes

# Workers: one process per lane (from worker/)
CORPUS_LANE=cpu python -m corpus
CORPUS_LANE=gpu CORPUS_WAKE_PORT=8788 python -m corpus
```

The Kokoro voice files and the Whisper model download on first use into
`~/.cache/content_corpus` and the Hugging Face cache.

## Tests

The tests use a real Postgres but fake every paid service. OpenAI, S3 (moto), Race
and ComfyUI (local fake servers) are all stand-ins, so nothing is billed. ffmpeg
really runs, so the reels the tests build are real files.

```bash
bash db/dev/test_db.sh                    # Postgres 18 in Docker on 127.0.0.1:55442
worker/.venv/bin/python -m pytest db/tests worker/tests -q
```

## Third-party models and assets

- LTX-2.5 by Lightricks: a gated model under its own licence, so accept it on
  Hugging Face before use.
- Kokoro-82M (Apache-2.0) for narration.
- Whisper (MIT), via faster-whisper, for word timings.
- The Montserrat font is bundled under the SIL Open Font License
  (`worker/corpus/media/fonts/OFL.txt`).
