-- Asking again for work whose job gave up runs it again.
--
-- Jobs are deduplicated by key, and the key names the work, not the attempt
-- (write_script:<post>:v<n>, assemble:<script>, ...). So when a job had died and
-- the same work was requested again — "Write script" after a failed first try,
-- where no version was written and n is unchanged — the insert hit the old key
-- and handed back the dead job: the post said "scripting" and nothing ran.
--
-- Now a dead, failed or cancelled job with that key is revived in place, with
-- the new request's settings and fresh attempts. A job still queued or running,
-- or one that succeeded, is returned untouched as before.

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
    update public.jobs
       set state = p_state, attempts = 0, max_attempts = p_max_attempts,
           lease_seconds = p_lease_seconds, priority = p_priority,
           payload = coalesce(p_payload, '{}'::jsonb),
           not_before = coalesce(p_not_before, now()),
           error = null, result = null, claimed_by = null, claimed_at = null,
           lease_expires_at = null, cancel_requested_at = null,
           started_at = null, finished_at = null, updated_at = now()
     where dedupe_key = p_dedupe_key and state in ('failed', 'dead', 'cancelled')
    returning * into j;
  end if;
  if j.id is null then
    select * into j from public.jobs where dedupe_key = p_dedupe_key;
  end if;
  return j;
end $fn$;
