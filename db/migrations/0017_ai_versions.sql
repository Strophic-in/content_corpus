-- Phase 3: AI versions. When accepting an idea, the owner can choose an AI version
-- of its media instead of the original — for footage they'd rather not publish.
--
--   picture  OpenAI draws a new picture of the same scene from its description, in
--            the channel's look (app_settings.image_model / image_quality). It is a
--            new asset (origin 'ai', credited "AI illustration", made_from the
--            original); the original is fetched and described but never shown.
--   video    the original is fetched and logged but never shown; the script writer
--            recreates its moments as generated shots, labelled "AI reconstruction".
--
-- Any picture the reel may show (an approved original, or an AI one) can also be
-- animated on the GPU: a generated shot with a first-frame guide (LTX image-to-
-- video). shots.guide_key is that picture in R2.

alter table app_settings
  add column image_model   text not null default 'gpt-image-1-mini',
  add column image_quality text not null default 'medium' check (image_quality in ('low','medium','high'));

alter table assets add column made_from uuid references assets(id) on delete set null;

alter table shots add column guide_key text;

-- adopt_idea_media gains the choice: 'original' (approved: the swipe is the
-- approval) or 'ai' (the original only informs; a picture gets an AI twin).
drop function private.adopt_idea_media(public.ideas, uuid);
create function private.adopt_idea_media(p_idea public.ideas, p_post_id uuid, p_choice text default 'original')
returns int
language plpgsql security definer set search_path = '' as $fn$
declare
  m    jsonb;
  k    int := 0;
  aid  uuid;
  twin uuid;
  item jsonb;
begin
  for m in select value from jsonb_array_elements(coalesce(p_idea.media, '[]'::jsonb)) loop
    k := k + 1;
    item := (select it from jsonb_array_elements(coalesce(p_idea.items, '[]'::jsonb)) it
              where it->>'url' = m->>'source_url' limit 1);
    insert into public.assets (user_id, post_id, idea_id, n, kind, origin, source_url, credit, rights,
                               fetch_from, w, h, seconds, has_audio, analysis)
    values (p_idea.user_id, p_post_id, p_idea.id, k, m->>'type', coalesce(m->>'origin', 'article'),
            m->>'source_url', coalesce(m->>'credit', ''),
            case when p_choice = 'original' then 'approved' else 'needs_review' end,
            jsonb_build_object('item', coalesce(item, '{}'::jsonb), 'preview_key', m->>'key',
                               'poster_key', m->>'poster_key'),
            (m->>'w')::int, (m->>'h')::int, (m->>'seconds')::numeric, (m->>'has_audio')::boolean,
            case when m->>'type' = 'video' and p_idea.analysis ? 'video'
                 then jsonb_build_object('card', p_idea.analysis->'video') end)
    returning id into aid;
    perform private.enqueue_job(p_idea.user_id, 'ideas', 'fetch_asset', format('fetch_asset:%s', aid),
                                jsonb_build_object('asset_id', aid), p_post_id,
                                p_priority => 40, p_max_attempts => 2, p_lease_seconds => 900);
    if p_choice = 'ai' and m->>'type' = 'image' then
      -- Its AI twin: drawn once the original has been described (analyze_asset).
      k := k + 1;
      insert into public.assets (user_id, post_id, idea_id, n, kind, origin, credit, license, rights, made_from)
      values (p_idea.user_id, p_post_id, p_idea.id, k, 'image', 'ai', 'AI illustration', 'ai', 'approved', aid)
      returning id into twin;
    end if;
  end loop;
  return k;
end $fn$;

-- The swipe: p_media is 'none' | 'original' | 'ai' (p_use_media, the older yes/no,
-- still means 'original').
drop function api.decide_idea_v2(uuid, boolean, timestamptz, text, text[], boolean);
create function api.decide_idea_v2(p_idea_id uuid, p_accept boolean,
                                   p_publish_at timestamptz default null,
                                   p_reason text default null,
                                   p_platforms text[] default null,
                                   p_use_media boolean default false,
                                   p_media text default null) returns public.ideas
language plpgsql security definer set search_path = '' as $fn$
declare
  i      public.ideas;
  f      public.formats;
  c      public.channels;
  s      public.app_settings;
  pid    uuid;
  mode   text;
  plats  text[];
  choice text := coalesce(p_media, case when p_use_media then 'original' else 'none' end);
begin
  if choice not in ('none','original','ai') then
    raise exception 'unknown media choice %', choice using errcode = '22023';
  end if;
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
  if choice <> 'none' and i.media_state = 'ready' then
    update public.posts set media_choice = choice where id = pid;
    perform private.adopt_idea_media(i, pid, choice);
  end if;
  if mode = 'auto' then
    perform private.generate_script(pid, 'system:auto');      -- waits for the footage, then writes
  end if;
  return i;
end $fn$;

-- Rendering: a picture a generated shot starts from must be approved and fetched,
-- like any footage the reel shows.
create or replace function private.footage_problem(p_script_id uuid) returns int
language sql stable security definer set search_path = '' as $fn$
  select min(s.idx) + 1
    from public.shots s left join public.assets a on a.id = s.asset_id
   where s.script_id = p_script_id and s.state <> 'uploaded'
     and (s.source in ('clip','image') or s.asset_id is not null)
     and (a.id is null or a.rights <> 'approved' or a.state <> 'ready');
$fn$;

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
  bad := private.footage_problem(p.approved_script_id);
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
