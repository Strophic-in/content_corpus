-- Owner, 2026-10-20: "if I have heard a news or topic or anything I should give as
-- idea and make reel or video", and Explore's "Make an idea" showed nothing.
--
-- api.idea_from_topic: what the owner heard about, in their own words, and maybe a
-- link about it, becomes one idea card on the channel's Discover deck (the ideas
-- lane finds the news about it and writes the idea; suggest_ideas.py).
--
-- api.idea_from_video: asking again for the same video now asks again. Its job was
-- keyed by category and video alone, so a second press found the first, finished
-- job (one that had made no idea, say) and did nothing. Both keys now carry the
-- minute: a double press is still one request.

create or replace function api.idea_from_video(p_category_id uuid, p_video jsonb) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare k public.categories := private.owned_category(p_category_id);
begin
  perform private.check_quota(k.user_id);
  if octet_length(p_video::text) > 20000 or coalesce(p_video->>'id', '') !~ '^[A-Za-z0-9_-]{6,20}$'
     or coalesce(p_video->>'title', '') = '' then
    raise exception 'not a YouTube video' using errcode = '22023';
  end if;
  return private.enqueue_job(k.user_id, 'ideas', 'idea_from_video',
                             format('idea_from_video:%s:%s:%s', k.id, p_video->>'id',
                                    to_char(now(), 'YYYYMMDDHH24MI')),
                             jsonb_build_object('category_id', k.id, 'video', p_video), null,
                             p_priority => 20, p_max_attempts => 2, p_lease_seconds => 300);
end $fn$;

create or replace function api.idea_from_topic(p_category_id uuid, p_topic text, p_url text default null)
returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  k public.categories := private.owned_category(p_category_id);
  t text := btrim(coalesce(p_topic, ''));
  u text := nullif(btrim(coalesce(p_url, '')), '');
begin
  perform private.check_quota(k.user_id);
  if char_length(t) < 3 then
    raise exception 'say in a few words what the video should be about' using errcode = '22023';
  end if;
  if char_length(t) > 1000 then
    raise exception 'keep it under 1000 characters' using errcode = '22023';
  end if;
  if u is not null and (u !~* '^https?://[^[:space:]]+$' or char_length(u) > 2000) then
    raise exception 'that link is not a web address' using errcode = '22023';
  end if;
  return private.enqueue_job(k.user_id, 'ideas', 'idea_from_topic',
                             format('idea_from_topic:%s:%s:%s', k.id, md5(lower(t) || coalesce(u, '')),
                                    to_char(now(), 'YYYYMMDDHH24MI')),
                             jsonb_build_object('category_id', k.id, 'topic', t, 'url', u), null,
                             p_priority => 20, p_max_attempts => 2, p_lease_seconds => 300);
end $fn$;
