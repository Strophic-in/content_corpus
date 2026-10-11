-- Rendering a post whose shots are all rendered already only re-runs assembly.
--
-- After the final join failed (2026-10-11), every shot was rendered and stored
-- but "Retry" asked for the GPU job again — which had *succeeded*, so nothing was
-- queued and the post waited forever. Now, when every shot of the approved
-- script is uploaded, request_render queues cpu/assemble and touches no GPU.

create or replace function api.request_render(p_post_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  p          public.posts := private.owned_post(p_post_id);
  n_shots    int;
  n_ready    int;
  n_rendered int;
  j          public.jobs;
begin
  if p.status not in ('approved','failed') or p.approved_script_id is null then
    raise exception 'only an approved post can be rendered (this one is %)', p.status
      using errcode = '55000';
  end if;
  select count(*),
         count(*) filter (where p.audio_source <> 'kokoro' or narration_key is not null),
         count(*) filter (where state = 'uploaded')
    into n_shots, n_ready, n_rendered
    from public.shots where script_id = p.approved_script_id;
  if n_shots = 0 or n_ready < n_shots then
    raise exception 'shots are still being planned or voiced; try again in a moment'
      using errcode = '55000';
  end if;

  if n_rendered = n_shots then
    -- The GPU work is done and stored: only the assembly is left.
    update public.posts set status = 'rendered', error = null where id = p.id;
    perform private.log_post_event(p.id, p.status, 'rendered',
                                   'user:' || private.caller(), 'assembly retried');
    return private.enqueue_job(p.user_id, 'cpu', 'assemble',
                               format('assemble:%s', p.approved_script_id),
                               jsonb_build_object('script_id', p.approved_script_id), p.id,
                               p_max_attempts => 3, p_lease_seconds => 900);
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
