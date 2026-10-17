-- Phase 2: reels from real footage. Beside shots generated on the GPU, a shot can
-- now show the post's own video or picture (used only when the owner chose so on
-- accepting the idea, and always credited), a Pexels stock video, or a photo with
-- a slow Ken Burns move. A reel without generated shots never rents a GPU.
--
--   assets   media a post may use, fetched at full quality by the ideas lane and
--            analysed (what happens when, what is said) on the cpu lane. Rights
--            are the owner's: a shot may show only an approved, fetched asset,
--            checked again when rendering is requested.
--   shots    gain a source: generate (LTX, as before) | clip (a window of a video
--            asset) | image (an image asset) | stock (a Pexels search). LTX's
--            frame and size rules now bind generated shots only.
--   fan-in   rendering queues assemble blocked; private.unblock_assemble releases
--            it when EVERY shot of the script is uploaded. (It used to release on
--            "nothing planned, queued or rendering", so a failed shot let assemble
--            start and fail.)

alter table storage_objects drop constraint storage_objects_kind_check,
  add constraint storage_objects_kind_check
  check (kind in ('shot','last_frame','final','style_ref','narration','other','idea_media','asset'));

create table assets (
  id          uuid primary key default gen_random_uuid(),
  user_id     text not null references "user"(id) on delete cascade,
  post_id     uuid not null references posts(id) on delete cascade,
  idea_id     uuid references ideas(id) on delete set null,
  n           int  not null check (n >= 1),        -- its number in the script writer's inventory
  kind        text not null check (kind in ('video','image')),
  origin      text not null,                       -- reddit, bluesky, mastodon, lemmy, youtube, article …
  source_url  text,                                -- the post or page it came from
  credit      text not null default '',
  license     text not null default 'third_party' check (license in ('third_party','pexels','cc0','ai')),
  rights      text not null default 'needs_review' check (rights in ('needs_review','approved','rejected')),
  -- Written by the workers: how to fetch it (the idea's item, the card preview as a
  -- fallback), the stored file and what it shows.
  fetch_from  jsonb not null default '{}'::jsonb,
  state       text not null default 'pending' check (state in ('pending','ready','failed')),
  key         text,
  w           int,
  h           int,
  seconds     numeric,
  has_audio   boolean,
  analysis    jsonb,
  error       text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (post_id, n)
);
create index assets_post on assets (post_id);
alter table assets enable row level security;
create policy own on assets
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true));
create trigger assets_touch before update on assets for each row execute function private.touch_updated_at();

alter table shots
  add column source      text not null default 'generate' check (source in ('generate','clip','image','stock')),
  add column asset_id    uuid references assets(id) on delete set null,
  add column clip_in     numeric,
  add column clip_out    numeric,
  add column layout      text check (layout in ('cover','blur_pad')),
  add column audio_mode  text not null default 'duck' check (audio_mode in ('duck','keep','mute')),
  add column stock_query text,
  add column credit      text;
alter table shots drop constraint shots_frames_legal, drop constraint shots_dims_legal;
alter table shots
  add constraint shots_frames_legal check (source <> 'generate' or num_frames % 8 = 1),
  add constraint shots_dims_legal   check (source <> 'generate' or (width % 64 = 0 and height % 64 = 0));

-- Who made what the reel shows, for the on-screen credit's companion lines in the
-- YouTube description and the Instagram caption. Filled at assembly.
alter table posts add column credits jsonb not null default '[]'::jsonb;

create or replace function private.unblock_assemble() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  if new.state in ('uploaded','skipped')
     and not exists (select 1 from public.shots
                      where script_id = new.script_id and state not in ('uploaded','skipped'))
  then
    update public.jobs
       set state = 'queued', not_before = now()
     where post_id = new.post_id
       and kind = 'assemble'
       and state = 'blocked'
       and payload->>'script_id' = new.script_id::text;
  end if;
  return new;
end $fn$;

-- Rendering, now in two kinds of work: generated shots on the GPU (render_post),
-- every other shot on the cpu lane (prepare_shot, one job each). Assemble waits,
-- blocked, for both.
create or replace function private.request_render(p_post_id uuid, p_actor text) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  p          public.posts;
  cap        int;
  n_shots    int;
  n_ready    int;
  n_rendered int;
  bad        int;
  sh         record;
  j          public.jobs;
  first_job  public.jobs;
begin
  select * into p from public.posts where id = p_post_id for update;
  if not found then
    raise exception 'post not found' using errcode = 'P0002';
  end if;
  if p.status not in ('approved','failed') or p.approved_script_id is null then
    raise exception 'only an approved post can be rendered (this one is %)', p.status
      using errcode = '55000';
  end if;
  if p_actor = 'system:auto' then
    select auto_spend_cap_paise_day into cap from public.app_settings where user_id = p.user_id;
    if cap is not null and private.spent_today_paise(p.user_id) >= cap then
      raise exception 'today''s automatic spending limit (₹%) is reached — render it by hand or raise the limit',
                      cap / 100 using errcode = '55000';
    end if;
  end if;
  -- A shot with a narration line waits for its recording; a clip that keeps its own
  -- sound has no line.
  select count(*),
         count(*) filter (where p.audio_source <> 'kokoro' or coalesce(narration, '') = ''
                                or narration_key is not null),
         count(*) filter (where state = 'uploaded')
    into n_shots, n_ready, n_rendered
    from public.shots where script_id = p.approved_script_id;
  if n_shots = 0 or n_ready < n_shots then
    raise exception 'shots are still being planned or voiced; try again in a moment'
      using errcode = '55000';
  end if;
  -- Third-party footage only with the owner's approval, and only once it is fetched.
  select min(s.idx) + 1 into bad
    from public.shots s left join public.assets a on a.id = s.asset_id
   where s.script_id = p.approved_script_id and s.source in ('clip','image') and s.state <> 'uploaded'
     and (a.id is null or a.rights <> 'approved' or a.state <> 'ready');
  if bad is not null then
    raise exception 'shot % uses footage that is not approved, or not fetched yet', bad
      using errcode = '55000';
  end if;

  if n_rendered = n_shots then
    update public.posts set status = 'rendered', error = null where id = p.id;
    perform private.log_post_event(p.id, p.status, 'rendered', p_actor, 'assembly retried');
    return private.enqueue_job(p.user_id, 'cpu', 'assemble',
                               format('assemble:%s', p.approved_script_id),
                               jsonb_build_object('script_id', p.approved_script_id), p.id,
                               p_max_attempts => 3, p_lease_seconds => 900);
  end if;

  update public.posts set status = 'queued_for_render', error = null where id = p.id;
  perform private.log_post_event(p.id, p.status, 'queued_for_render', p_actor, 'render requested');
  -- First, so that no shot can finish before there is an assemble to release.
  perform private.enqueue_job(p.user_id, 'cpu', 'assemble', format('assemble:%s', p.approved_script_id),
                              jsonb_build_object('script_id', p.approved_script_id), p.id,
                              p_max_attempts => 3, p_lease_seconds => 900, p_state => 'blocked');
  for sh in select id from public.shots
             where script_id = p.approved_script_id and source <> 'generate' and state <> 'uploaded'
             order by idx loop
    j := private.enqueue_job(p.user_id, 'cpu', 'prepare_shot', format('prepare_shot:%s', sh.id),
                             jsonb_build_object('shot_id', sh.id), p.id, sh.id,
                             p_priority => 45, p_max_attempts => 3, p_lease_seconds => 900);
    if first_job.id is null then
      first_job := j;
    end if;
  end loop;
  if not exists (select 1 from public.shots where script_id = p.approved_script_id
                    and source = 'generate' and state <> 'uploaded') then
    return first_job;
  end if;
  j := private.enqueue_job(p.user_id, 'gpu', 'render_post',
                           format('render_post:%s', p.approved_script_id),
                           jsonb_build_object('script_id', p.approved_script_id), p.id,
                           p_priority => 50, p_max_attempts => 40, p_lease_seconds => 600);
  update public.jobs set state = 'queued', not_before = now(), attempts = 0,
                         max_attempts = 40, error = null, finished_at = null
   where id = j.id and state in ('failed','dead','cancelled');
  select * into j from public.jobs where id = j.id;
  return j;
end $fn$;

-- An accepted idea's card media becomes the post's assets when the owner chose to
-- use it: approved (that choice is the approval), credited, fetched at full quality
-- by the ideas lane. The idea's item tells the worker where the original lives.
create or replace function private.adopt_idea_media(p_idea public.ideas, p_post_id uuid) returns int
language plpgsql security definer set search_path = '' as $fn$
declare
  m    jsonb;
  k    int := 0;
  aid  uuid;
  item jsonb;
begin
  for m in select value from jsonb_array_elements(coalesce(p_idea.media, '[]'::jsonb)) loop
    k := k + 1;
    item := (select it from jsonb_array_elements(coalesce(p_idea.items, '[]'::jsonb)) it
              where it->>'url' = m->>'source_url' limit 1);
    insert into public.assets (user_id, post_id, idea_id, n, kind, origin, source_url, credit, rights,
                               fetch_from, w, h, seconds, has_audio, analysis)
    values (p_idea.user_id, p_post_id, p_idea.id, k, m->>'type', coalesce(m->>'origin', 'article'),
            m->>'source_url', coalesce(m->>'credit', ''), 'approved',
            jsonb_build_object('item', coalesce(item, '{}'::jsonb), 'preview_key', m->>'key',
                               'poster_key', m->>'poster_key'),
            (m->>'w')::int, (m->>'h')::int, (m->>'seconds')::numeric, (m->>'has_audio')::boolean,
            case when m->>'type' = 'video' and p_idea.analysis ? 'video'
                 then jsonb_build_object('card', p_idea.analysis->'video') end)
    returning id into aid;
    perform private.enqueue_job(p_idea.user_id, 'ideas', 'fetch_asset', format('fetch_asset:%s', aid),
                                jsonb_build_object('asset_id', aid), p_post_id,
                                p_priority => 40, p_max_attempts => 2, p_lease_seconds => 900);
  end loop;
  return k;
end $fn$;

-- The swipe, now also saying whether the card's picture or video may be used.
drop function api.decide_idea_v2(uuid, boolean, timestamptz, text, text[]);
create function api.decide_idea_v2(p_idea_id uuid, p_accept boolean,
                                   p_publish_at timestamptz default null,
                                   p_reason text default null,
                                   p_platforms text[] default null,
                                   p_use_media boolean default false) returns public.ideas
language plpgsql security definer set search_path = '' as $fn$
declare
  i     public.ideas;
  f     public.formats;
  c     public.channels;
  s     public.app_settings;
  pid   uuid;
  mode  text;
  plats text[];
begin
  select * into i from public.ideas where id = p_idea_id and user_id = private.caller() for update;
  if not found then
    raise exception 'idea not found' using errcode = 'P0002';
  end if;
  if i.status <> 'new' then
    raise exception 'this idea was already %', i.status using errcode = '55000';
  end if;
  if not p_accept then
    update public.ideas set status = 'rejected', decided_at = now(),
                            reject_reason = nullif(btrim(coalesce(p_reason, '')), '')
     where id = i.id returning * into i;
    return i;
  end if;
  if p_publish_at is null then
    raise exception 'pick a date and time to schedule it' using errcode = '55000';
  end if;
  if p_platforms is not null and not (p_platforms <@ array['youtube','instagram']) then
    raise exception 'unknown platform in %', p_platforms using errcode = '22023';
  end if;
  select * into c from public.channels where id = i.channel_id;
  select * into f from public.formats where id = i.format_id;
  select * into s from public.app_settings where user_id = i.user_id;
  plats := coalesce(nullif(p_platforms, '{}'),
                    nullif(array(select platform from public.channel_accounts
                                  where channel_id = c.id and status = 'connected' order by platform), '{}'),
                    array['youtube']);
  insert into public.posts (user_id, channel_id, format_id, category_id, topic, brief, slot_date,
                            publish_tz, publish_at, audio_source, target_seconds, platforms)
  values (i.user_id, c.id, f.id, i.category_id, left(i.title, 300),
          concat_ws(E'\n\n', i.brief, nullif('Hook: ' || i.hook, 'Hook: '),
                    nullif('Why now: ' || i.why_now, 'Why now: ')),
          (p_publish_at at time zone c.timezone)::date, c.timezone, p_publish_at,
          coalesce(f.audio_source, s.default_audio_source, 'kokoro'), f.target_seconds, plats)
  returning id, pipeline_mode into pid, mode;
  update public.ideas set status = 'accepted', decided_at = now(), post_id = pid
   where id = i.id returning * into i;
  if p_use_media and i.media_state = 'ready' then
    update public.posts set media_choice = 'original' where id = pid;
    perform private.adopt_idea_media(i, pid);
  end if;
  if mode = 'auto' then
    perform private.generate_script(pid, 'system:auto');      -- waits for the footage, then writes
  end if;
  return i;
end $fn$;
