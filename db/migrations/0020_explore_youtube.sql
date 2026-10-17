-- Explore YouTube: the web server reads YouTube's public data (trending charts,
-- searches, statistics) with the owner's own YouTube Data API key, and can turn a
-- video into an idea card.
--
-- The key vault stays write-only from the web for everything else: this returns the
-- caller's YouTube key only (a key for public data), still encrypted; the web
-- decrypts it with APP_ENCRYPTION_KEY, which it already holds to encrypt keys.
create or replace function api.youtube_key_ciphertext() returns text
language sql stable security definer set search_path = '' as $fn$
  select ciphertext from public.user_keys where user_id = private.caller() and name = 'youtube_api_key';
$fn$;

-- "Make an idea" from a video: the ideas lane writes one idea for the category in
-- the channel's voice (suggest_ideas with the video as its only item), then the
-- card gets the video's thumbnail like any card. The video itself is never fetched.
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
                             format('idea_from_video:%s:%s', k.id, p_video->>'id'),
                             jsonb_build_object('category_id', k.id, 'video', p_video), null,
                             p_priority => 20, p_max_attempts => 2, p_lease_seconds => 300);
end $fn$;
