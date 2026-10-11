-- The moving parts: job queue (claim, heartbeat, finish, reap, enqueue), the R2
-- storage ledger, and the narrow `api` surface the web app may call.
--
-- `private` functions are for workers, which connect as the owner. `api`
-- functions are SECURITY DEFINER and are the only way `corpus_web` changes
-- lifecycle state. They read the caller from `app.user_id` (set per transaction
-- by apps/web/lib/db.ts) and never take a user id as an argument.
--
-- No pg_cron: the cpu worker calls private.reap_expired_leases() on every tick,
-- so lease recovery needs nothing installed beyond plain PostgreSQL and keeps
-- working on any host (VibeDB in production, a Neon copy restored from backup).

-- ─────────────────────────────────────────────────────────────────────────────
-- claim_job — take the next ready job in a lane, or return nothing.
-- One statement with FOR UPDATE SKIP LOCKED: several pollers on one table never
-- race on the read, which the two-round-trip read-then-update pattern does.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.claim_job(
  p_worker  text,
  p_lane    text,
  p_version text,
  p_kinds   text[] default null
) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  j   public.jobs;
  cfg public.lane_config;
begin
  select * into cfg from public.lane_config where lane = p_lane;
  if not found then
    raise exception 'unknown lane %', p_lane;
  end if;

  -- An operator can stop a lane from draining without stopping the worker, which
  -- matters most for `gpu`: you may want the pod online for debugging without it
  -- eating the week's queue.
  if cfg.paused then
    return null;
  end if;

  -- A pod running last week's code must not claim work. There is no stable SSH
  -- address to go fix it at, so refusing the claim is the only lever available.
  if cfg.required_version <> '' and p_version is distinct from cfg.required_version then
    return null;
  end if;

  select * into j
    from public.jobs
   where lane = p_lane
     and state = 'queued'
     and not_before <= now()
     and (p_kinds is null or kind = any(p_kinds))
   order by priority, created_at
   for update skip locked
   limit 1;

  if not found then
    return null;
  end if;

  update public.jobs set
      state            = 'claimed',
      attempts         = attempts + 1,
      claimed_by       = p_worker,
      claimed_at       = now(),
      lease_expires_at = now() + make_interval(secs => lease_seconds),
      started_at       = coalesce(started_at, now())
   where id = j.id
   returning * into j;

  update public.workers
     set state = 'busy', current_job_id = j.id, last_heartbeat_at = now()
   where id = p_worker;

  return j;
end $fn$;

-- ─────────────────────────────────────────────────────────────────────────────
-- heartbeat_job — extend the lease and report liveness.
--
-- Heartbeat-extended leases rather than one global stale window: a single
-- window cannot serve both a 20-second job and a 60-minute render. Here the
-- lease sits lease_seconds ahead of now and is pushed forward every ~15s, so a
-- dead worker is detected in ~2 minutes no matter how long the job takes.
--
-- Returns true if the worker should keep going, false if cancellation was
-- requested — the worker checks this between shots rather than killing a sampler
-- whose 8 minutes are already spent.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.heartbeat_job(
  p_job_id uuid,
  p_worker text,
  p_stats  jsonb default '{}'::jsonb
) returns boolean
language plpgsql security definer set search_path = '' as $fn$
declare
  j public.jobs;
begin
  update public.jobs
     set lease_expires_at = now() + make_interval(secs => lease_seconds)
   where id = p_job_id
     and claimed_by = p_worker
     and state = 'claimed'
   returning * into j;

  -- The lease was reaped out from under us, or another worker owns this job now.
  -- Telling the worker to stop is the only safe answer: continuing would mean two
  -- processes writing one job's artifacts.
  if not found then
    return false;
  end if;

  update public.workers
     set last_heartbeat_at = now(),
         stats             = coalesce(p_stats, '{}'::jsonb),
         state             = 'busy',
         current_job_id    = p_job_id
   where id = p_worker;

  return j.cancel_requested_at is null;
end $fn$;

-- ─────────────────────────────────────────────────────────────────────────────
-- worker_ping — heartbeat with no job in hand.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.worker_ping(
  p_worker  text,
  p_lane    text,
  p_version text,
  p_boot_id text default null,
  p_stats   jsonb default '{}'::jsonb
) returns void
language plpgsql security definer set search_path = '' as $fn$
begin
  insert into public.workers (id, lane, version, boot_id, state, stats,
                              last_heartbeat_at)
  values (p_worker, p_lane, p_version, p_boot_id, 'idle',
          coalesce(p_stats, '{}'::jsonb), now())
  on conflict (id) do update set
      lane              = excluded.lane,
      version           = excluded.version,
      -- A new boot_id means the pod was resumed (or terminated and recreated).
      -- Keeping it lets the UI say "resumed 4m ago" and lets a cleanup pass
      -- notice that pod-local latents from last week are gone.
      boot_id           = coalesce(excluded.boot_id, public.workers.boot_id),
      state             = 'idle',
      current_job_id    = null,
      stats             = excluded.stats,
      last_heartbeat_at = now();
end $fn$;

-- ─────────────────────────────────────────────────────────────────────────────
-- finish_job — terminal transition, with retry/backoff decided here.
--
-- Everything upstream of publish retries freely: a shot render is a pure
-- function of (prompt, seed, size, frames), so at worst a retry wastes compute.
-- "No double-render" is an economic guarantee. "No double-post" is a
-- correctness guarantee, so `publish` has max_attempts=1 and a lost publish
-- means *unknown, ask a human* — never 'failed', which invites a blind retry.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.finish_job(
  p_job_id   uuid,
  p_worker   text,
  p_state    text,               -- 'succeeded' | 'failed' | 'needs_review'
  p_error    jsonb default null,
  p_result   jsonb default null,
  p_retry_in int default null    -- seconds; null = use the default backoff
) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  j          public.jobs;
  next_state text;
  backoff    int;
begin
  select * into j from public.jobs where id = p_job_id for update;
  if not found then
    raise exception 'no such job %', p_job_id;
  end if;

  -- A worker whose lease expired must not be able to overwrite the outcome the
  -- reaper (or the worker that re-claimed the job) already recorded.
  if j.claimed_by is distinct from p_worker or j.state <> 'claimed' then
    return j;
  end if;

  if p_state = 'succeeded' then
    next_state := 'succeeded';
  elsif p_state = 'needs_review' then
    next_state := 'needs_review';
  elsif j.attempts >= j.max_attempts then
    -- 'dead' rather than 'failed' so the UI can distinguish "gave up after 3
    -- tries" from "one attempt, failed, retryable by hand".
    next_state := 'dead';
  else
    next_state := 'queued';
    backoff := coalesce(p_retry_in, 30 * power(2, greatest(j.attempts - 1, 0))::int);
  end if;

  update public.jobs set
      state       = next_state,
      error       = coalesce(p_error, case when next_state = 'succeeded'
                                          then null else jobs.error end),
      result      = coalesce(p_result, jobs.result),
      finished_at = case when next_state = 'queued' then null else now() end,
      claimed_by  = case when next_state = 'queued' then null else claimed_by end,
      claimed_at  = case when next_state = 'queued' then null else claimed_at end,
      lease_expires_at = null,
      not_before  = case when next_state = 'queued'
                         then now() + make_interval(secs => backoff)
                         else not_before end
   where id = p_job_id
   returning * into j;

  update public.workers
     set state = 'idle', current_job_id = null, last_heartbeat_at = now()
   where id = p_worker;

  return j;
end $fn$;

-- ─────────────────────────────────────────────────────────────────────────────
-- reap_expired_leases — recover work whose worker vanished.
--
-- The canonical case is the GPU pod being paused mid-render: pause is not a
-- graceful shutdown, so there is no SIGTERM and no chance to release the claim.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.reap_expired_leases()
returns table (job_id uuid, kind text, new_state text)
language plpgsql security definer set search_path = '' as $fn$
begin
  return query
  with expired as (
    select id from public.jobs
     where state = 'claimed'
       and lease_expires_at is not null
       and lease_expires_at < now()
     for update skip locked
  ),
  updated as (
    update public.jobs j set
        -- The publish lane is the only side-effecting one, so a lost lease there
        -- means the outcome is genuinely unknown: the upload may have completed
        -- after the worker died. needs_review is the honest answer, and
        -- publish_attempts.upload_session_uri is what lets a human resolve it.
        state = case
                  when j.lane = 'publish' then 'needs_review'
                  when j.attempts >= j.max_attempts then 'dead'
                  else 'queued'
                end,
        error = coalesce(j.error, '{}'::jsonb) || jsonb_build_object(
                  'stage', 'lease_expired',
                  'message', format('lease expired while claimed by %s', j.claimed_by),
                  'retryable', j.lane <> 'publish',
                  'at', now()),
        claimed_by  = case when j.lane = 'publish' then j.claimed_by else null end,
        claimed_at  = case when j.lane = 'publish' then j.claimed_at else null end,
        lease_expires_at = null,
        finished_at = case when j.lane = 'publish'
                            or j.attempts >= j.max_attempts then now() else null end,
        not_before  = case when j.lane = 'publish'
                            or j.attempts >= j.max_attempts then j.not_before
                           else now() + make_interval(secs => 30) end
     where j.id in (select id from expired)
     returning j.id, j.kind, j.state
  )
  select * from updated;
end $fn$;

-- ─────────────────────────────────────────────────────────────────────────────
-- enqueue_job — insert-or-ignore on dedupe_key.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.enqueue_job(
  p_user_id       text,
  p_lane          text,
  p_kind          text,
  p_dedupe_key    text,
  p_payload       jsonb default '{}'::jsonb,
  p_post_id       uuid default null,
  p_shot_id       uuid default null,
  p_batch_id      uuid default null,
  p_priority      int  default 100,
  p_max_attempts  int  default 1,
  p_lease_seconds int  default 120,
  p_state         text default 'queued',
  p_not_before    timestamptz default null
) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare j public.jobs;
begin
  insert into public.jobs (user_id, lane, kind, dedupe_key, payload, post_id,
                           shot_id, batch_id, priority, max_attempts,
                           lease_seconds, state, not_before)
  values (p_user_id, p_lane, p_kind, p_dedupe_key, coalesce(p_payload, '{}'::jsonb),
          p_post_id, p_shot_id, p_batch_id, p_priority, p_max_attempts,
          p_lease_seconds, p_state, coalesce(p_not_before, now()))
  on conflict (dedupe_key) do nothing
  returning * into j;

  if j.id is null then
    select * into j from public.jobs where dedupe_key = p_dedupe_key;
  end if;
  return j;
end $fn$;

-- The earliest moment any queued job becomes claimable. The worker sleeps until
-- then (or until the web app wakes it) instead of polling a sleeping database.
create or replace function private.next_due(p_lanes text[])
returns timestamptz
language sql stable security definer set search_path = '' as $fn$
  select min(not_before) from public.jobs
   where state = 'queued' and lane = any(p_lanes);
$fn$;

-- ─────────────────────────────────────────────────────────────────────────────
-- Fan-in: assemble waits for all shots.
--
-- The only real dependency in the whole pipeline, so it gets a trigger rather
-- than a depends_on[] resolver and a DAG engine. Everything else is sequential —
-- each handler enqueues the next job.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.unblock_assemble() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  if new.state in ('uploaded','skipped')
     and not exists (
       select 1 from public.shots
        where script_id = new.script_id
          and state in ('planned','queued','rendering')
     )
  then
    update public.jobs
       set state = 'queued', not_before = now()
     where post_id = new.post_id
       and kind = 'assemble'
       and state = 'blocked';
  end if;
  return new;
end $fn$;

create trigger shots_unblock_assemble
  after update of state on shots
  for each row execute function private.unblock_assemble();

-- ─────────────────────────────────────────────────────────────────────────────
-- Post event log helper.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.log_post_event(
  p_post_id uuid, p_from text, p_to text, p_actor text,
  p_reason text default null, p_detail jsonb default null
) returns void
language sql security definer set search_path = '' as $fn$
  insert into public.post_events (post_id, from_state, to_state, actor, reason, detail)
  values (p_post_id, p_from, p_to, p_actor, p_reason, p_detail);
$fn$;

-- ─────────────────────────────────────────────────────────────────────────────
-- Storage ledger. Reserve before upload, commit after, release on failure.
--
-- A transaction-scoped advisory lock serialises reservations, so two uploads
-- that each fit on their own cannot both squeeze past the cap together.
--
-- A refusal RETURNS ok=false rather than raising. Raising would roll back the
-- storage_config.full_since stamp in the same transaction, and that stamp is
-- what makes the UI show "storage full" — an alert that vanished with the error
-- it reports would be worse than none. The worker's one storage wrapper turns
-- ok=false into a failed job with stage 'storage_full'.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.storage_used() returns bigint
language sql stable security definer set search_path = '' as $fn$
  select coalesce(sum(bytes), 0)::bigint from public.storage_objects
   where state in ('reserved','stored');
$fn$;

create or replace function private.reserve_storage(
  p_key     text,
  p_bytes   bigint,
  p_kind    text,
  p_user_id text default null,
  p_post_id uuid default null,
  p_shot_id uuid default null
) returns table (ok boolean, used_bytes bigint, cap_bytes bigint)
language plpgsql security definer set search_path = '' as $fn$
declare
  cap  bigint;
  used bigint;
begin
  perform pg_advisory_xact_lock(hashtext('corpus.storage_quota'));
  select c.cap_bytes into cap from public.storage_config c;

  -- An object being re-uploaded under the same key replaces itself, so its old
  -- size must not count against its new one.
  select coalesce(sum(s.bytes), 0) into used from public.storage_objects s
   where s.state in ('reserved','stored') and s.key <> p_key;

  if used + p_bytes > cap then
    update public.storage_config set full_since = coalesce(full_since, now());
    return query select false, used, cap;
    return;
  end if;

  insert into public.storage_objects (key, user_id, kind, post_id, shot_id, bytes, state)
  values (p_key, p_user_id, p_kind, p_post_id, p_shot_id, p_bytes, 'reserved')
  on conflict (key) do update set
      bytes = excluded.bytes, state = 'reserved', kind = excluded.kind,
      user_id = excluded.user_id, post_id = excluded.post_id, shot_id = excluded.shot_id,
      sha256 = null, stored_at = null, deleted_at = null;
  return query select true, used + p_bytes, cap;
end $fn$;

create or replace function private.commit_storage(
  p_key text, p_bytes bigint, p_sha256 text default null
) returns public.storage_objects
language plpgsql security definer set search_path = '' as $fn$
declare o public.storage_objects;
begin
  update public.storage_objects
     set state = 'stored', bytes = p_bytes, sha256 = p_sha256, stored_at = now()
   where key = p_key
   returning * into o;
  if not found then
    raise exception 'commit_storage: no reservation for %', p_key;
  end if;
  return o;
end $fn$;

-- After an upload fails: drop the reservation so the space is free again.
create or replace function private.release_storage(p_key text) returns void
language sql security definer set search_path = '' as $fn$
  delete from public.storage_objects where key = p_key and state = 'reserved';
$fn$;

-- After the object is deleted from R2. Clears the alert once usage is back
-- under the cap.
create or replace function private.mark_storage_deleted(p_key text) returns void
language plpgsql security definer set search_path = '' as $fn$
begin
  update public.storage_objects
     set state = 'deleted', deleted_at = now()
   where key = p_key and state <> 'deleted';
  update public.storage_config
     set full_since = null
   where full_since is not null and private.storage_used() < cap_bytes;
end $fn$;

-- ─────────────────────────────────────────────────────────────────────────────
-- api — the web app's only route to lifecycle changes.
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function private.caller() returns text
language plpgsql stable set search_path = '' as $fn$
declare u text := nullif(current_setting('app.user_id', true), '');
begin
  if u is null then
    raise exception 'no signed-in user for this transaction' using errcode = '28000';
  end if;
  return u;
end $fn$;

-- Owned post or an error; never reveals whether someone else's post exists.
create or replace function private.owned_post(p_post_id uuid) returns public.posts
language plpgsql stable security definer set search_path = '' as $fn$
declare p public.posts;
begin
  select * into p from public.posts where id = p_post_id and user_id = private.caller();
  if not found then
    raise exception 'post not found' using errcode = 'P0002';
  end if;
  return p;
end $fn$;

create or replace function api.ensure_settings() returns public.app_settings
language plpgsql security definer set search_path = '' as $fn$
declare s public.app_settings;
begin
  insert into public.app_settings (user_id) values (private.caller())
  on conflict (user_id) do nothing;
  select * into s from public.app_settings where user_id = private.caller();
  return s;
end $fn$;

-- Ask the cpu worker for a (new) script version.
create or replace function api.generate_script(p_post_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  p   public.posts := private.owned_post(p_post_id);
  nxt int;
  j   public.jobs;
begin
  if p.status not in ('draft','awaiting_approval','failed') then
    raise exception 'cannot (re)write the script of a post in status %', p.status
      using errcode = '55000';
  end if;
  select coalesce(max(version), 0) + 1 into nxt from public.scripts where post_id = p.id;

  update public.posts set status = 'scripting', error = null where id = p.id;
  perform private.log_post_event(p.id, p.status, 'scripting',
                                 'user:' || private.caller(), 'script requested');
  j := private.enqueue_job(p.user_id, 'cpu', 'write_script',
                           format('write_script:%s:v%s', p.id, nxt),
                           jsonb_build_object('version', nxt), p.id,
                           p_max_attempts => 3, p_lease_seconds => 300);
  return j;
end $fn$;

-- The one approval path. Approval is a state on the script (not a flag on the
-- post), stamped with who and when, and it is what unlocks shot planning. Both
-- a human (api.approve_script) and auto-approve (the worker, for posts whose
-- auto_approve snapshot is true) come through here, so they cannot drift apart.
create or replace function private.approve_script(p_script_id uuid, p_actor text)
returns public.posts
language plpgsql security definer set search_path = '' as $fn$
declare
  s public.scripts;
  p public.posts;
begin
  select * into s from public.scripts where id = p_script_id for update;
  if not found then
    raise exception 'script not found' using errcode = 'P0002';
  end if;
  if s.state <> 'awaiting_approval' then
    raise exception 'script is %, not awaiting approval', s.state using errcode = '55000';
  end if;

  update public.scripts
     set state = 'approved', approved_at = now(), approved_by = p_actor
   where id = s.id;
  update public.posts
     set status = 'approved', approved_script_id = s.id, error = null
   where id = s.post_id
   returning * into p;
  perform private.log_post_event(p.id, 'awaiting_approval', 'approved', p_actor,
                                 'script approved', jsonb_build_object('script_id', s.id,
                                                                       'version', s.version));
  perform private.enqueue_job(p.user_id, 'cpu', 'plan_shots',
                              format('plan_shots:%s', s.id),
                              jsonb_build_object('script_id', s.id), p.id,
                              p_max_attempts => 3, p_lease_seconds => 300);
  return p;
end $fn$;

create or replace function api.approve_script(p_script_id uuid) returns public.posts
language plpgsql security definer set search_path = '' as $fn$
declare
  s public.scripts;
begin
  select * into s from public.scripts where id = p_script_id;
  if not found then
    raise exception 'script not found' using errcode = 'P0002';
  end if;
  perform private.owned_post(s.post_id);   -- raises unless the caller owns it
  return private.approve_script(p_script_id, 'user:' || private.caller());
end $fn$;

create or replace function api.reject_script(p_script_id uuid, p_note text default null)
returns public.posts
language plpgsql security definer set search_path = '' as $fn$
declare
  s  public.scripts;
  p  public.posts;
  me text := private.caller();
begin
  select * into s from public.scripts where id = p_script_id for update;
  if not found then
    raise exception 'script not found' using errcode = 'P0002';
  end if;
  p := private.owned_post(s.post_id);
  if s.state <> 'awaiting_approval' then
    raise exception 'script is %, not awaiting approval', s.state using errcode = '55000';
  end if;

  update public.scripts set state = 'rejected', rejection_note = p_note where id = s.id;
  update public.posts set status = 'draft' where id = p.id returning * into p;
  perform private.log_post_event(p.id, 'awaiting_approval', 'draft', 'user:' || me,
                                 'script rejected', jsonb_build_object('script_id', s.id,
                                                                       'note', p_note));
  return p;
end $fn$;

-- Bucket-wide usage for the dashboard meter and the "storage full" alert. The
-- ledger rows themselves stay per-user under RLS.
create or replace function api.storage_status()
returns table (used_bytes bigint, cap_bytes bigint, full_since timestamptz)
language sql stable security definer set search_path = '' as $fn$
  select private.storage_used(), c.cap_bytes, c.full_since from public.storage_config c;
$fn$;
