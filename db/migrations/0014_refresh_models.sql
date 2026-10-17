-- Keep the list of OpenAI models the owner's key can use up to date.
--
-- The list was read once, when the key was saved; models OpenAI adds later (or the
-- owner enables in their OpenAI project afterwards, like gpt-6-luna on 2026-10-17)
-- never appeared. The web app can't read the key back (write-only), so the ideas
-- worker lists the models: on request (Settings → Refresh list) and once a day.
create or replace function api.refresh_openai_models() returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare u text := private.caller();
begin
  return private.enqueue_job(u, 'ideas', 'refresh_models',
                             format('refresh_models:%s:%s', u, to_char(now(), 'YYYYMMDDHH24MI')),
                             '{}'::jsonb, null, p_priority => 30, p_max_attempts => 1, p_lease_seconds => 120);
end $fn$;
