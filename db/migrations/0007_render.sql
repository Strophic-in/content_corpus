-- Milestone 3/4: narration, rendering and assembly.
--
-- Pipeline for a narrated post (audio_source = 'kokoro'):
--   approve → plan_shots → narrate (TTS per shot; the voice sets each shot's
--   length) → [Render] → render_post (GPU) → assemble (stitch, mix, captions) → ready
-- A post whose characters speak skips narrate.

alter table shots
  add column narration         text,      -- this shot's voice-over line (narrated mode)
  add column narration_key     text,      -- R2 key of its recorded WAV
  add column narration_seconds numeric;   -- its measured length; drives num_frames

alter table storage_objects drop constraint storage_objects_kind_check;
alter table storage_objects add constraint storage_objects_kind_check
  check (kind in ('shot','last_frame','final','style_ref','narration','other'));

alter table app_settings
  add column narrator_voice text    not null default 'am_michael',
  add column narrator_speed numeric not null default 1.1
    check (narrator_speed between 0.7 and 1.5);

-- [Render] from the web. Only an approved post whose shots are all planned (and,
-- for narrated posts, voiced) can be queued; the GPU job is one per approved
-- script, so pressing twice cannot render twice.
create or replace function api.request_render(p_post_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  p       public.posts := private.owned_post(p_post_id);
  n_shots int;
  n_ready int;
  j       public.jobs;
begin
  if p.status not in ('approved','failed') or p.approved_script_id is null then
    raise exception 'only an approved post can be rendered (this one is %)', p.status
      using errcode = '55000';
  end if;
  select count(*), count(*) filter (where p.audio_source <> 'kokoro' or narration_key is not null)
    into n_shots, n_ready
    from public.shots where script_id = p.approved_script_id;
  if n_shots = 0 or n_ready < n_shots then
    raise exception 'shots are still being planned or voiced; try again in a moment'
      using errcode = '55000';
  end if;

  update public.posts set status = 'queued_for_render', error = null where id = p.id;
  perform private.log_post_event(p.id, p.status, 'queued_for_render',
                                 'user:' || private.caller(), 'render requested');
  j := private.enqueue_job(p.user_id, 'gpu', 'render_post',
                           format('render_post:%s', p.approved_script_id),
                           jsonb_build_object('script_id', p.approved_script_id), p.id,
                           p_priority => 50,
                           -- No free GPU is the common failure on Race; keep retrying
                           -- for hours (backoff is set by the handler) rather than fail.
                           p_max_attempts => 40, p_lease_seconds => 600);
  -- A re-render after a failure reuses the job row: put it back in the queue.
  update public.jobs set state = 'queued', not_before = now(), attempts = 0,
                         max_attempts = 40, error = null, finished_at = null
   where id = j.id and state in ('failed','dead','cancelled');
  select * into j from public.jobs where id = j.id;
  return j;
end $fn$;
