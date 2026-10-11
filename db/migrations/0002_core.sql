-- content_corpus — core schema (PostgreSQL 18 on VibeDB; ported from the Supabase draft).
--
-- Design notes that are load-bearing and easy to undo by accident:
--
--  * Two roles. Workers and migrations connect as the database owner, which owns
--    every table and so is not subject to RLS. The web app connects as
--    `corpus_web`: RLS (0004_rls.sql) scopes it to the signed-in user, and column
--    grants (db/access.sql) keep it off the lifecycle columns. Lifecycle changes the UI may request
--    go through SECURITY DEFINER functions in `api`, which take the caller from the
--    transaction-local `app.user_id`, never from an argument.
--  * Every invariant that protects money or prevents a double-post lives in a
--    CONSTRAINT, not in Python. The LTX frame/dimension rules especially:
--    violating them fails a render 40 minutes into a rented GPU hour.
--  * A user who can set their own row to 'queued' can bypass the approval gate.
--    That is why posts.status is not writable by `corpus_web`.
--  * User ids are Better Auth's text ids ("user".id), not uuids.

create schema if not exists private;   -- worker-only functions
create schema if not exists api;       -- functions the web app may call

-- No extensions: gen_random_uuid() is core PostgreSQL (13+), and a VibeDB
-- project owner should not need to create any.

-- ─────────────────────────────────────────────────────────────────────────────
-- Settings & key vault
-- ─────────────────────────────────────────────────────────────────────────────

create table app_settings (
  user_id                 text primary key references "user"(id) on delete cascade,
  timezone                text        not null default 'Asia/Kolkata',
  -- The DEFAULT for new posts. Never read this to decide whether an existing
  -- post is approved — see posts.auto_approve.
  auto_approve            boolean     not null default false,
  default_publish_time    time        not null default '09:00',
  youtube_category_id     text        not null default '22',
  -- The YouTube API project is unaudited at launch, and YouTube forces uploads from
  -- unaudited projects to private anyway. Flip to 'public' once the audit passes.
  youtube_privacy         text        not null default 'private'
                          check (youtube_privacy in ('private','unlisted','public')),
  caption_style_id        uuid,
  gpu_autopause           boolean     not null default true,
  -- ₹91/hr + 18% GST for the RTX 5090, in paise. Drives the cost counter in the UI.
  gpu_rate_paise_per_hour int         not null default 10738,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

-- Per-user secrets, AES-256-GCM encrypted by the caller before insert. The
-- ciphertext format is byte-compatible between apps/web/lib/crypto.ts and
-- worker/corpus/crypto.py — do not change one without the other.
create table user_keys (
  user_id    text not null references "user"(id) on delete cascade,
  name       text not null,
  ciphertext text not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, name)
);

create table caption_styles (
  id              uuid primary key default gen_random_uuid(),
  user_id         text not null references "user"(id) on delete cascade,
  name            text not null,
  font_family     text not null default 'Montserrat',
  font_size_px    int  not null default 84,
  primary_color   text not null default '#FFFFFF',
  accent_color    text not null default '#FFE000',
  outline_px      int  not null default 8,
  shadow_px       int  not null default 4,
  -- 0.0 = top, 1.0 = bottom. The default clears the Reels UI safe area.
  position_y      numeric not null default 0.72,
  words_per_group int  not null default 3,
  active_scale    numeric not null default 1.18,
  uppercase       boolean not null default true,
  created_at      timestamptz not null default now(),
  unique (user_id, name),
  check (words_per_group between 1 and 6),
  check (position_y between 0 and 1)
);

alter table app_settings
  add constraint app_settings_caption_style_fk
  foreign key (caption_style_id) references caption_styles(id) on delete set null;

-- ─────────────────────────────────────────────────────────────────────────────
-- Render batches — the GPU window. A "week" is just a date range over posts, so
-- it gets no table; a batch has a real lifecycle, so it does.
-- ─────────────────────────────────────────────────────────────────────────────

create table render_batches (
  id                 uuid primary key default gen_random_uuid(),
  user_id            text not null references "user"(id) on delete cascade,
  week_start         date not null,
  state              text not null default 'draft'
                     check (state in ('draft','requested','pod_waiting','running',
                                      'drained','completed','failed','cancelled')),
  est_gpu_seconds    numeric,
  actual_gpu_seconds numeric,
  requested_at       timestamptz,
  first_claim_at     timestamptz,
  last_progress_at   timestamptz,
  drained_at         timestamptz,
  notes              text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index render_batches_user_week on render_batches (user_id, week_start desc);

-- ─────────────────────────────────────────────────────────────────────────────
-- Posts — one row per published thing.
-- ─────────────────────────────────────────────────────────────────────────────

create table posts (
  id                 uuid primary key default gen_random_uuid(),
  user_id            text not null references "user"(id) on delete cascade,
  format             text not null default 'reel'
                     check (format in ('reel','longform','carousel')),
  topic              text not null,
  brief              text,
  slot_date          date not null,
  publish_tz         text not null default 'Asia/Kolkata',
  publish_at         timestamptz,
  status             text not null default 'draft'
                     check (status in ('draft','scripting','awaiting_approval','approved',
                                       'queued_for_render','rendering','rendered',
                                       'post_processing','ready','scheduled','published',
                                       'needs_review','failed','cancelled')),
  -- SNAPSHOT of app_settings.auto_approve at creation time, filled by a trigger —
  -- the web role cannot write it. Deliberately not a live lookup: if this were
  -- read at approval time, flipping the toggle on a Saturday morning would
  -- retroactively approve a week of unreviewed scripts and ship them.
  auto_approve       boolean not null default false,
  audio_source       text not null default 'ltx_native'
                     check (audio_source in ('ltx_native','kokoro')),
  target_seconds     int,
  platforms          text[] not null default '{youtube}',
  captions_enabled   boolean not null default true,
  caption_style_id   uuid references caption_styles(id) on delete set null,
  render_batch_id    uuid references render_batches(id) on delete set null,
  approved_script_id uuid,          -- FK added below, after scripts exists
  final_key          text,          -- R2 object key of the finished reel
  final_sha256       text,
  final_duration_s   numeric,
  final_bytes        bigint,
  error              jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  -- One post per calendar day is a product invariant, so it lives where a
  -- Server Action cannot forget to check it.
  unique (user_id, slot_date),
  check (target_seconds is null or target_seconds between 5 and 300)
);
create index posts_user_slot on posts (user_id, slot_date desc);
create index posts_batch     on posts (render_batch_id) where render_batch_id is not null;
create index posts_status    on posts (user_id, status);

-- ─────────────────────────────────────────────────────────────────────────────
-- Scripts — versioned, approval-gated. Approval lives HERE, not as a boolean on
-- posts, so the render gate is one join that a stray post UPDATE cannot bypass,
-- and so "which script did Thursday's video actually use" still has an answer
-- after three regenerations.
-- ─────────────────────────────────────────────────────────────────────────────

create table scripts (
  id                uuid primary key default gen_random_uuid(),
  post_id           uuid not null references posts(id) on delete cascade,
  version           int  not null,
  state             text not null default 'draft'
                    check (state in ('draft','awaiting_approval','approved',
                                     'rejected','superseded')),
  title             text,
  hook              text,
  description       text,
  hashtags          text[] not null default '{}',
  -- What we EXPECT to be said. With audio_source='ltx_native' we do not control
  -- the words, so this is not narration to be spoken verbatim — it is the
  -- initial_prompt that biases ASR toward our names and jargon. (Verified
  -- 2026-10-03: it recovered a background shout Whisper otherwise dropped.)
  intended_dialogue text not null default '',
  shot_plan         jsonb not null default '[]',
  -- Frozen look string appended verbatim to every shot prompt for this post.
  -- This plus style_ref_key is what keeps drift O(1) instead of O(n).
  style_prompt      text,
  style_ref_key     text,
  model             text,
  -- sha256(topic|brief|prompt_template|model). A retrying write_script job that
  -- finds a matching row returns it instead of spending another LLM call,
  -- which is what makes the job safe to retry at all.
  input_sha256      text,
  review            jsonb,   -- ADVISORY. Never a gate. Shown next to Approve.
  token_usage       jsonb,
  cost_micros       int,
  approved_at       timestamptz,
  approved_by       text,
  rejection_note    text,
  created_at        timestamptz not null default now(),
  unique (post_id, version)
);
-- At most one live version per post; older versions must be superseded/rejected.
create unique index scripts_one_live on scripts (post_id)
  where state in ('draft','awaiting_approval','approved');

alter table posts
  add constraint posts_approved_script_fk
  foreign key (approved_script_id) references scripts(id) on delete set null;

-- ─────────────────────────────────────────────────────────────────────────────
-- Shots — the unit of GPU work and the unit of retry.
-- ─────────────────────────────────────────────────────────────────────────────

create table shots (
  id                 uuid primary key default gen_random_uuid(),
  post_id            uuid not null references posts(id) on delete cascade,
  script_id          uuid not null references scripts(id) on delete cascade,
  idx                int  not null,
  -- Shots sharing a latent chain. Keep groups to 2-3 shots (16-24s): drift
  -- becomes obvious past ~12-16s of autoregressive generation.
  scene_group        int  not null default 0,
  chain_role         text not null default 'anchor'
                     check (chain_role in ('anchor','extend')),
  prompt             text not null,
  negative_prompt    text,
  -- Fixed at plan time, never regenerated. Makes a retry byte-comparable and
  -- makes "regenerate shot 4 only" a real feature rather than a lottery.
  seed               bigint not null,
  width              int not null,
  height             int not null,
  num_frames         int not null,
  fps                int not null default 24,
  duration_s         numeric generated always as ((num_frames - 1)::numeric / fps) stored,
  guide_kind         text check (guide_kind in ('style_ref','first_frame','flf2v','latent')),
  guide_from_shot_id uuid references shots(id) on delete set null,
  state              text not null default 'planned'
                     check (state in ('planned','queued','rendering','uploaded',
                                      'failed','skipped')),
  artifact_key       text,     -- R2 object key
  artifact_sha256    text,
  artifact_bytes     bigint,
  last_frame_key     text,
  latent_path        text,     -- pod-local only; never leaves the pod
  -- The crash-recovery handle: a restarted worker checks GET /history/{id}
  -- before spending another 12 minutes. If the pod itself survived, the render
  -- probably already finished.
  comfy_prompt_id    text,
  gpu_seconds        numeric,
  -- True when an OOM retry shortened this shot, so the UI can say why it is
  -- short instead of silently lying.
  degraded           boolean not null default false,
  attempts           int not null default 0,
  error              jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (script_id, idx),
  -- The LTX invariants. In the database because a future change to prompt
  -- planning is exactly the kind of edit that violates them silently. The
  -- 64-pixel rule (not 32) is because LTX-2.5 renders stage 1 at half size and
  -- both stages must land on the 32-pixel grid.
  constraint shots_frames_legal    check (num_frames % 8 = 1),
  constraint shots_dims_legal      check (width % 64 = 0 and height % 64 = 0),
  constraint shots_frames_positive check (num_frames >= 9)
);
create index shots_post    on shots (post_id, idx);
create index shots_pending on shots (post_id)
  where state in ('planned','queued','rendering');

-- ─────────────────────────────────────────────────────────────────────────────
-- Jobs — one table, all lanes. Resist per-kind tables: the lease/claim/reaper
-- logic is the only genuinely hard code here and there should be exactly one
-- copy of it, one index, one reaper, one "what is happening now" query.
-- ─────────────────────────────────────────────────────────────────────────────

create table jobs (
  id                  uuid primary key default gen_random_uuid(),
  user_id             text not null references "user"(id) on delete cascade,
  lane                text not null check (lane in ('cpu','gpu','publish')),
  kind                text not null,
  post_id             uuid references posts(id) on delete cascade,
  shot_id             uuid references shots(id) on delete cascade,
  batch_id            uuid references render_batches(id) on delete cascade,
  -- Enqueue-side idempotency, e.g. 'render_shot:<shot_id>' or
  -- 'publish:<post_id>:youtube'. Stable across retries (a retry reuses the row),
  -- so the web app and a worker can both enqueue without coordinating.
  dedupe_key          text not null unique,
  payload             jsonb not null default '{}',
  priority            int  not null default 100,
  state               text not null default 'queued'
                      check (state in ('blocked','queued','claimed','succeeded',
                                       'failed','dead','needs_review','cancelled')),
  attempts            int not null default 0,
  max_attempts        int not null default 1,
  lease_seconds       int not null default 120,
  -- Doubles as retry backoff and as the scheduled-publish gate.
  not_before          timestamptz not null default now(),
  claimed_by          text,
  claimed_at          timestamptz,
  lease_expires_at    timestamptz,
  cancel_requested_at timestamptz,
  started_at          timestamptz,
  finished_at         timestamptz,
  -- jsonb, not text. By the third OOM debug you want vram_peak_mb as a number,
  -- separate from the stderr tail.
  error               jsonb,
  result              jsonb,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  check (max_attempts >= 1),
  check (lease_seconds between 30 and 3600)
);
create index jobs_ready on jobs (lane, priority, created_at) where state = 'queued';
create index jobs_lease on jobs (lease_expires_at)           where state = 'claimed';
create index jobs_post  on jobs (post_id)  where post_id  is not null;
create index jobs_batch on jobs (batch_id) where batch_id is not null;

-- ─────────────────────────────────────────────────────────────────────────────
-- Workers — heartbeats. The ONLY source of truth for "is the GPU online".
-- Never store a 'paused' state: a paused pod cannot write one, because pause is
-- not a graceful shutdown. Online-ness is derived from last_heartbeat_at.
-- ─────────────────────────────────────────────────────────────────────────────

create table workers (
  id                text primary key,   -- 'cpu-oracle-1' | 'publish-oracle-1' | 'gpu-race-1'
  lane              text not null check (lane in ('cpu','gpu','publish')),
  version           text not null,      -- git sha of the deployed worker
  boot_id           text,               -- new per pod resume; lets the UI say "resumed 4m ago"
  state             text not null default 'idle'
                    check (state in ('idle','busy','draining')),
  current_job_id    uuid,
  stats             jsonb not null default '{}',  -- comfy_ok, vram_used_mb, disk_free_gb
  started_at        timestamptz not null default now(),
  last_heartbeat_at timestamptz not null default now()
);

-- A stale pod must not claim work it cannot do correctly. One config row beats a
-- support call about a box you cannot SSH into at a stable address.
create table lane_config (
  lane             text primary key check (lane in ('cpu','gpu','publish')),
  -- When non-empty, only a worker reporting exactly this version may claim.
  -- Exact match on purpose: versions are git shas, which have no order, so the
  -- draft's `p_version < min_worker_version` was comparing hex strings.
  required_version text not null default '',
  paused           boolean not null default false
);
insert into lane_config (lane) values ('cpu'), ('gpu'), ('publish');

alter table jobs add constraint jobs_claimed_by_fk
  foreign key (claimed_by) references workers(id) on delete set null;
alter table workers add constraint workers_current_job_fk
  foreign key (current_job_id) references jobs(id) on delete set null;

-- ─────────────────────────────────────────────────────────────────────────────
-- Publish attempts — append-only audit. The double-post guard lives here.
-- ─────────────────────────────────────────────────────────────────────────────

create table publish_attempts (
  id                 uuid primary key default gen_random_uuid(),
  post_id            uuid not null references posts(id) on delete cascade,
  platform           text not null check (platform in ('youtube','instagram')),
  state              text not null default 'started'
                     check (state in ('started','uploading','uploaded','scheduled',
                                      'live','failed','abandoned')),
  -- Written BEFORE any bytes go out. This is what makes "publisher died between
  -- upload and record" recoverable: PUT the session URI with
  -- Content-Range: bytes */<len> and YouTube reports the id or resumes.
  upload_session_uri text,
  remote_id          text,
  remote_url         text,
  privacy            text,
  publish_at         timestamptz,
  response           jsonb,
  error              jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
-- At most one in-flight or successful attempt per (post, platform). The database
-- prevents the double-post; the code is only the first line of defence.
create unique index publish_one_inflight on publish_attempts (post_id, platform)
  where state in ('started','uploading','uploaded','scheduled','live');
create index publish_attempts_post on publish_attempts (post_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Post events — cheap, and the only way you will ever explain why Thursday's
-- reel never went out.
-- ─────────────────────────────────────────────────────────────────────────────

create table post_events (
  id         bigserial primary key,
  post_id    uuid not null references posts(id) on delete cascade,
  from_state text,
  to_state   text not null,
  actor      text not null,   -- 'user:<id>' | 'worker:<id>' | 'system'
  reason     text,
  detail     jsonb,
  at         timestamptz not null default now()
);
create index post_events_post on post_events (post_id, at desc);

-- ─────────────────────────────────────────────────────────────────────────────
-- Storage ledger — the R2 hard cap. R2 has no native quota, so every object is
-- recorded here BEFORE it is uploaded, and private.reserve_storage refuses a
-- reservation that would take the bucket past storage_config.cap_bytes. The
-- ledger is bucket-wide (the R2 free tier is per account), not per user.
-- ─────────────────────────────────────────────────────────────────────────────

create table storage_config (
  id        boolean primary key default true check (id),   -- single row
  -- 9 GB, in decimal bytes: a margin under the 10 GB-month R2 free tier.
  cap_bytes bigint not null default 9000000000 check (cap_bytes > 0),
  -- Set by the last refusal; the UI shows the "storage full" alert while set.
  full_since timestamptz
);
insert into storage_config default values;

create table storage_objects (
  key        text primary key,
  user_id    text references "user"(id) on delete set null,
  kind       text not null check (kind in ('shot','last_frame','final','style_ref','other')),
  post_id    uuid references posts(id) on delete set null,
  shot_id    uuid references shots(id) on delete set null,
  -- Reserved bytes until the upload lands, then the real size.
  bytes      bigint not null check (bytes >= 0),
  state      text not null default 'reserved'
             check (state in ('reserved','stored','deleted')),
  sha256     text,
  created_at timestamptz not null default now(),
  stored_at  timestamptz,
  deleted_at timestamptz
);
create index storage_objects_live on storage_objects (state) where state <> 'deleted';
create index storage_objects_post on storage_objects (post_id) where post_id is not null;

-- ─────────────────────────────────────────────────────────────────────────────
-- Triggers
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $fn$
begin
  new.updated_at = now();
  return new;
end $fn$;

do $mig$
declare t text;
begin
  foreach t in array array['app_settings','render_batches','posts','shots','jobs',
                           'publish_attempts']
  loop
    execute format(
      'create trigger %1$I_touch before update on public.%1$I
         for each row execute function private.touch_updated_at()', t);
  end loop;
end $mig$;

-- posts.auto_approve is a snapshot the web role cannot write; take it from the
-- owner's settings at insert time.
create or replace function private.snapshot_auto_approve() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  select coalesce(s.auto_approve, false) into new.auto_approve
    from public.app_settings s where s.user_id = new.user_id;
  new.auto_approve := coalesce(new.auto_approve, false);
  return new;
end $fn$;

create trigger posts_snapshot_auto_approve before insert on posts
  for each row execute function private.snapshot_auto_approve();
