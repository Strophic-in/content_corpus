-- Pause a channel's daily ideas for a while (Discover: "Pause daily ideas").
--
-- channels.ideas_paused_until: no daily batch is scheduled before then ('infinity':
-- until the owner resumes). Pausing also cancels a batch already queued for later
-- today; "More ideas" by hand still works while paused.

alter table channels add column ideas_paused_until timestamptz;

create or replace function private.schedule_daily_ideas() returns int
language plpgsql security definer set search_path = '' as $fn$
declare
  r   record;
  d   date;
  k   text;
  n   int := 0;
begin
  for r in select cat.id, cat.user_id, cat.channel_id, c.timezone, c.ideas_daily_at,
                  row_number() over (partition by c.id order by cat.created_at) - 1 as i
             from public.channels c
             join public.categories cat on cat.channel_id = c.id and cat.enabled
            where c.ideas_daily and (c.ideas_paused_until is null or c.ideas_paused_until <= now()) loop
    d := (now() at time zone r.timezone)::date;
    k := format('suggest_ideas:cat:%s:daily:%s', r.id, d);
    if not exists (select 1 from public.jobs where dedupe_key = k) then
      perform private.enqueue_job(r.user_id, 'ideas', 'suggest_ideas', k,
                                  jsonb_build_object('category_id', r.id, 'channel_id', r.channel_id,
                                                     'trigger', 'daily'), null,
                                  p_priority => 90, p_max_attempts => 2, p_lease_seconds => 900,
                                  p_not_before => ((d + r.ideas_daily_at) at time zone r.timezone)
                                                  + make_interval(mins => 3 * r.i::int));
      n := n + 1;
    end if;
  end loop;
  return n;
end $fn$;

-- p_until: when daily ideas start again ('infinity': until resumed); null resumes now.
create or replace function api.pause_daily_ideas(p_channel_id uuid, p_until timestamptz) returns public.channels
language plpgsql security definer set search_path = '' as $fn$
declare
  c public.channels;
begin
  if p_until is not null and p_until <= now() then
    raise exception 'pick a time in the future' using errcode = '22023';
  end if;
  update public.channels set ideas_paused_until = p_until, updated_at = now()
   where id = p_channel_id and user_id = private.caller()
  returning * into c;
  if not found then
    raise exception 'channel not found' using errcode = 'P0002';
  end if;
  if p_until is not null then
    update public.jobs set state = 'cancelled', finished_at = now()
     where kind = 'suggest_ideas' and state = 'queued' and payload->>'trigger' = 'daily'
       and payload->>'channel_id' = c.id::text;
  end if;
  return c;
end $fn$;
