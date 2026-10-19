-- A day's post without anyone there (owner, 2026-10-19): on a day the owner hasn't
-- picked anything, the channel's single best story of the day is made and posted on
-- autopilot — without an idea batch (no idea-writing call: tokens saved). On a day
-- the owner is there, they press "More ideas" in Discover and pick what goes out
-- today; then the automatic pick stands aside.
--
-- channels.daily_auto_post: on for this; daily_pick_at: when the pick is made (local
-- time), leaving time to research, write, voice, render and post by the channel's
-- posting time. The worker's ideas/auto_pick does the rest and checks first that
-- nothing is already on its way for today.

alter table channels
  add column daily_auto_post boolean not null default false,
  add column daily_pick_at time not null default '13:30';

create or replace function private.schedule_daily_pick() returns int
language plpgsql security definer set search_path = '' as $fn$
declare
  r record;
  d date;
  k text;
  n int := 0;
begin
  for r in select c.id, c.user_id, c.timezone, c.daily_pick_at from public.channels c
            where c.daily_auto_post and (c.ideas_paused_until is null or c.ideas_paused_until <= now()) loop
    d := (now() at time zone r.timezone)::date;
    k := format('auto_pick:%s:%s', r.id, d);
    if not exists (select 1 from public.jobs where dedupe_key = k) then
      perform private.enqueue_job(r.user_id, 'ideas', 'auto_pick', k,
                                  jsonb_build_object('channel_id', r.id, 'day', d), null,
                                  p_priority => 60, p_max_attempts => 2, p_lease_seconds => 1800,
                                  p_not_before => (d + r.daily_pick_at) at time zone r.timezone);
      n := n + 1;
    end if;
  end loop;
  return n;
end $fn$;
