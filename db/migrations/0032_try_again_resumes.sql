-- "Try again" on a post that stopped while its shots were being planned or voiced
-- now restarts that step. Before, go_ahead asked for a render, the render was
-- refused ("shots are still being planned or voiced"), and go_ahead answered
-- "will render when its shots are ready" — but the step had died, so nothing ran
-- and the post stayed failed.
--
-- The dead job is revived (enqueue_job revives dead/failed jobs by key; one still
-- queued or running is left alone), the post goes back to approved, and the
-- go-ahead it keeps renders it once the voice is recorded.

create or replace function api.go_ahead(p_post_id uuid) returns text
language plpgsql security definer set search_path = '' as $fn$
declare
  p        public.posts := private.owned_post(p_post_id);
  actor    text := 'user:' || private.caller();
  s        uuid;
  n_shots  int;
  n_silent int;
begin
  perform private.check_quota(private.caller());
  select * into p from public.posts where id = p.id for update;
  if p.status in ('draft') or (p.status = 'failed' and p.approved_script_id is null) then
    update public.posts set go_ahead = true where id = p.id;
    perform private.generate_script(p.id, actor);
    return 'writing the script';
  end if;
  if p.status = 'awaiting_approval' then
    select id into s from public.scripts
     where post_id = p.id and state = 'awaiting_approval' order by version desc limit 1;
    if s is null then
      raise exception 'no script is waiting for approval' using errcode = '55000';
    end if;
    update public.posts set go_ahead = true where id = p.id;
    perform private.approve_script(s, actor);
    return 'approved';
  end if;
  if p.status in ('approved','failed') then
    update public.posts set go_ahead = true where id = p.id;
    begin
      perform private.request_render(p.id, actor);
      update public.posts set go_ahead = false where id = p.id;
      return 'rendering';
    exception when sqlstate '55000' then
      if sqlerrm not like 'shots are still being planned%' then
        raise;
      end if;
    end;
    -- Shots not planned or not voiced yet: (re)start that step.
    select count(*), count(*) filter (where p.audio_source = 'kokoro' and narration_key is null)
      into n_shots, n_silent
      from public.shots where script_id = p.approved_script_id;
    if n_shots = 0 then
      perform private.enqueue_job(p.user_id, 'cpu', 'plan_shots', format('plan_shots:%s', p.approved_script_id),
                                  jsonb_build_object('script_id', p.approved_script_id), p.id,
                                  p_max_attempts => 3, p_lease_seconds => 300);
    elsif n_silent > 0 then
      perform private.enqueue_job(p.user_id, 'cpu', 'narrate', format('narrate:%s', p.approved_script_id),
                                  jsonb_build_object('script_id', p.approved_script_id), p.id,
                                  p_max_attempts => 3, p_lease_seconds => 600);
    end if;
    if p.status = 'failed' then
      update public.posts set status = 'approved', error = null where id = p.id;
      perform private.log_post_event(p.id, 'failed', 'approved', actor, 'tried again');
    end if;
    return 'will render when its shots are ready';
  end if;
  if p.status = 'scripting' then
    update public.posts set go_ahead = true where id = p.id;
    return 'will be approved and rendered once written';
  end if;
  raise exception 'nothing to do: it is %', replace(p.status, '_', ' ') using errcode = '55000';
end $fn$;
