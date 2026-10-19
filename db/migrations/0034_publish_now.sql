-- "Post it now" on a scheduled post: its waiting publish jobs (one per platform,
-- keyed publish:<post>:<platform>, due at the scheduled time) become due now. One
-- platform, or every platform it is scheduled on.

create or replace function api.publish_now(p_post_id uuid, p_platform text default null) returns int
language plpgsql security definer set search_path = '' as $fn$
declare
  p public.posts := private.owned_post(p_post_id);
  n int;
begin
  update public.jobs set not_before = now(), updated_at = now()
   where state = 'queued' and not_before > now()
     and dedupe_key in (format('publish:%s:youtube', p.id), format('publish:%s:instagram', p.id))
     and (p_platform is null or dedupe_key = format('publish:%s:%s', p.id, p_platform));
  get diagnostics n = row_count;
  if n = 0 then
    raise exception 'nothing is scheduled to post — it may be uploading already' using errcode = '55000';
  end if;
  perform private.log_post_event(p.id, p.status, p.status, 'user:' || private.caller(),
    case when p_platform is null then 'posting now instead of at its time'
         else format('posting to %s now', case p_platform when 'youtube' then 'YouTube' else 'Instagram' end) end);
  return n;
end $fn$;
