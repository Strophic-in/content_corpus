-- Every post collects its assets before its script (owner, 2026-10-19): the logos and
-- photos of who and what the story names, a headline card of each report, the
-- reports' own photos and videos (worker: finder.collect, at the end of research_post),
-- and what the owner adds — uploads (0021) and now links.
--
-- api.collect_assets starts (or restarts) the collection for one post: posts made by
-- hand had none, and a post whose collection ran before this existed gets one. The
-- research job is keyed by post, so a finished one is cancelled first and revived by
-- enqueue_job (which revives cancelled jobs, not finished ones).
--
-- api.add_asset_link: a link the owner pastes — a picture, a video page (YouTube, X,
-- a news site's player: yt-dlp) or an article (its lead picture) — becomes an
-- approved asset, fetched like any other.

create or replace function api.collect_assets(p_post_id uuid) returns text
language plpgsql security definer set search_path = '' as $fn$
declare
  p    public.posts := private.owned_post(p_post_id);
  idea uuid;
begin
  if p.status not in ('draft','awaiting_approval','approved','failed','scripting') then
    raise exception 'assets are collected before the post is made, not while it is %', replace(p.status, '_', ' ')
      using errcode = '55000';
  end if;
  if p.media_choice = 'ai' then
    raise exception 'this post was set to use AI pictures only' using errcode = '55000';
  end if;
  select id into idea from public.ideas where post_id = p.id order by created_at desc limit 1;
  update public.posts set research_state = 'pending' where id = p.id;
  update public.jobs set state = 'cancelled', updated_at = now()
   where dedupe_key = format('research_post:%s', p.id) and state = 'succeeded';
  perform private.enqueue_job(p.user_id, 'ideas', 'research_post', format('research_post:%s', p.id),
                              jsonb_build_object('post_id', p.id, 'idea_id', idea), p.id,
                              p_priority => 35, p_max_attempts => 2, p_lease_seconds => 900);
  return 'collecting';
end $fn$;

create or replace function api.add_asset_link(p_post_id uuid, p_url text, p_kind text default 'auto')
returns public.assets
language plpgsql security definer set search_path = '' as $fn$
declare
  p    public.posts := private.owned_post(p_post_id);
  url  text := btrim(coalesce(p_url, ''));
  kind text := coalesce(nullif(p_kind, 'auto'), '');
  host text;
  item jsonb;
  a    public.assets;
  k    int;
begin
  if url !~* '^https?://[^\s/]+\.[^\s]+$' or length(url) > 2000 then
    raise exception 'paste a full link, starting with https://' using errcode = '22023';
  end if;
  if kind not in ('', 'image', 'video') then
    raise exception 'a link is a picture or a video' using errcode = '22023';
  end if;
  if p.status not in ('draft','awaiting_approval','approved','failed','scripting') then
    raise exception 'footage can be added before the post is made, not while it is %', replace(p.status, '_', ' ')
      using errcode = '55000';
  end if;
  if (select count(*) from public.assets where post_id = p.id and origin in ('upload', 'link')) >= 12 then
    raise exception 'a post holds at most 12 of your own uploads and links' using errcode = '54000';
  end if;
  host := regexp_replace(lower(substring(url from '^https?://([^/:?#]+)')), '^www\.', '');
  if kind = '' then
    kind := case
      when url ~* '\.(jpe?g|png|webp|avif|gif)([?#].*)?$' then 'image'
      when host ~ '(^|\.)(youtube\.com|youtu\.be|x\.com|twitter\.com|instagram\.com|facebook\.com|fb\.watch|vimeo\.com|tiktok\.com|dailymotion\.com|reddit\.com|v\.redd\.it)$'
        or url ~* '\.(mp4|mov|webm|m3u8)([?#].*)?$' then 'video'
      else 'image' end;                       -- an article: its lead picture
  end if;
  if kind = 'video' then
    item := jsonb_build_object('page_url', url, 'page_index', 0, 'media_hint', 'video', 'link', url);
  elsif url ~* '\.(jpe?g|png|webp|avif|gif)([?#].*)?$' then
    item := jsonb_build_object('image_url', url, 'media_hint', 'image', 'link', url);
  else
    item := jsonb_build_object('link', url, 'media_hint', 'page');
  end if;
  if exists (select 1 from public.assets where post_id = p.id and source_url = url and state <> 'failed') then
    raise exception 'that link is already one of this post''s assets' using errcode = '23505';
  end if;
  perform pg_advisory_xact_lock(hashtext('assets:' || p.id::text));
  select coalesce(max(n), 0) + 1 into k from public.assets where post_id = p.id;
  insert into public.assets (user_id, post_id, n, kind, origin, source_url, credit, license, rights, state, fetch_from)
  values (p.user_id, p.id, k, kind, 'link', url, host, 'third_party', 'approved', 'pending',
          jsonb_build_object('item', item, 'found', jsonb_build_object('role', 'owner', 'shows', 3.0, 'usable', 1.0)))
  returning * into a;
  perform private.enqueue_job(p.user_id, 'ideas', 'fetch_asset', format('fetch_asset:%s', a.id),
                              jsonb_build_object('asset_id', a.id), p.id,
                              p_priority => 30, p_max_attempts => 2, p_lease_seconds => 900);
  return a;
end $fn$;
