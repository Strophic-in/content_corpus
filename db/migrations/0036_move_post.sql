-- Dragging a post to another day on the calendar (owner, 2026-10-19). The post keeps
-- its time of day (in its channel's timezone); a post already scheduled to publish
-- has its waiting publish jobs re-timed with it. Not into the past, and not a post
-- being rendered, put together or already posted.

create or replace function api.move_post(p_post_id uuid, p_date date) returns text
language plpgsql security definer set search_path = '' as $fn$
declare
  p     public.posts := private.owned_post(p_post_id);
  tz    text;
  t     time;
  at    timestamptz;
  today date;
begin
  select * into p from public.posts where id = p.id for update;
  if p.status in ('rendering', 'post_processing', 'published', 'cancelled') then
    raise exception 'a post that is % can''t be moved', replace(p.status, '_', ' ') using errcode = '55000';
  end if;
  tz := coalesce(p.publish_tz, (select timezone from public.channels where id = p.channel_id), 'UTC');
  today := (now() at time zone tz)::date;
  if p_date < today then
    raise exception 'pick today or a later day' using errcode = '22023';
  end if;
  if p_date = p.slot_date then
    return 'unchanged';
  end if;
  t := coalesce((p.publish_at at time zone tz)::time,
                (select default_publish_time from public.channels where id = p.channel_id), time '18:00');
  at := (p_date + t) at time zone tz;
  update public.posts set slot_date = p_date, publish_at = at, publish_tz = tz where id = p.id;
  -- A scheduled post goes out at its new time (straight away if that time today has passed).
  update public.jobs set not_before = greatest(at, now()), updated_at = now()
   where state = 'queued'
     and dedupe_key in (format('publish:%s:youtube', p.id), format('publish:%s:instagram', p.id));
  perform private.log_post_event(p.id, p.status, p.status, 'user:' || private.caller(),
                                 format('moved from %s to %s', p.slot_date, p_date));
  return 'moved';
end $fn$;
