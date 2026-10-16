-- Categories, Reddit and media on idea cards, the cost ledger, Manual/Automatic.
--
-- A channel now has categories (World, Tech, Crime…), each with its own sources:
-- Reddit communities, news sites, RSS feeds, keyword searches, Google Trends,
-- Wikipedia. Idea batches run per category, on a new "ideas" lane: the only
-- worker that contacts Reddit or arbitrary URLs, so its rate-limit waits and
-- media downloads never hold up scripts, segments or assembly.
--
-- Ideas carry the media of the posts they came from (a preview video or image,
-- stored under the idea_media storage kind, which has its own budget so card
-- previews can never starve a paid render of space).
--
-- Every model call and GPU minute is written to `costs`, so a reel's real cost —
-- OpenAI in dollars, GPU in rupees, with the exchange rate frozen per row — can
-- be shown per post and per month.
--
-- Manual/Automatic: a post snapshots the owner's pipeline mode when it is
-- created (the same rule as auto_approve, 0002: flipping the setting must never
-- retroactively ship posts). In automatic mode the worker drives render and
-- publish itself, so request_render/request_publish/generate_script are split
-- into a private core taking an actor, and api wrappers that check ownership.

-- ── the ideas lane ────────────────────────────────────────────────────────────
alter table jobs        drop constraint jobs_lane_check,
                        add  constraint jobs_lane_check check (lane in ('cpu','gpu','publish','ideas'));
alter table workers     drop constraint workers_lane_check,
                        add  constraint workers_lane_check check (lane in ('cpu','gpu','publish','ideas'));
alter table lane_config drop constraint lane_config_lane_check,
                        add  constraint lane_config_lane_check check (lane in ('cpu','gpu','publish','ideas'));
insert into lane_config (lane) values ('ideas') on conflict do nothing;
-- Batches queued for the old cpu handler move to the ideas worker.
update jobs set lane = 'ideas' where kind = 'suggest_ideas' and state in ('queued','blocked');

-- ── storage: card media has its own budget ────────────────────────────────────
alter table storage_objects drop constraint storage_objects_kind_check,
  add constraint storage_objects_kind_check
  check (kind in ('shot','last_frame','final','style_ref','narration','other','idea_media'));
alter table storage_config
  add column idea_media_cap_bytes bigint not null default 1500000000 check (idea_media_cap_bytes >= 0);

-- idea_media must fit its own budget; everything else must fit what is left of
-- the cap after that budget. So a full deck of previews can never make a render
-- fail at upload. Only a refusal for real media raises the "storage full" alert.
create or replace function private.reserve_storage(
  p_key     text,
  p_bytes   bigint,
  p_kind    text,
  p_user_id text default null,
  p_post_id uuid default null,
  p_shot_id uuid default null
) returns table (ok boolean, used_bytes bigint, cap_bytes bigint)
language plpgsql security definer set search_path = '' as $fn$
declare
  cap   bigint;
  ideas bigint;
  used  bigint;
  limit_bytes bigint;
begin
  perform pg_advisory_xact_lock(hashtext('corpus.storage_quota'));
  select c.cap_bytes, c.idea_media_cap_bytes into cap, ideas from public.storage_config c;

  select coalesce(sum(s.bytes), 0) into used from public.storage_objects s
   where s.state in ('reserved','stored') and s.key <> p_key
     and (s.kind = 'idea_media') = (p_kind = 'idea_media');
  limit_bytes := case when p_kind = 'idea_media' then ideas else greatest(cap - ideas, 0) end;

  if used + p_bytes > limit_bytes then
    if p_kind <> 'idea_media' then
      update public.storage_config set full_since = coalesce(full_since, now());
    end if;
    return query select false, used, limit_bytes;
    return;
  end if;

  insert into public.storage_objects (key, user_id, kind, post_id, shot_id, bytes, state)
  values (p_key, p_user_id, p_kind, p_post_id, p_shot_id, p_bytes, 'reserved')
  on conflict (key) do update set
      bytes = excluded.bytes, state = 'reserved', kind = excluded.kind,
      user_id = excluded.user_id, post_id = excluded.post_id, shot_id = excluded.shot_id,
      sha256 = null, stored_at = null, deleted_at = null;
  return query select true, used + p_bytes, limit_bytes;
end $fn$;

-- ── categories and their sources ──────────────────────────────────────────────
-- A category may point at a format of the same channel (enforced by the composite
-- key); deleting the format clears the pointer, not the category.
alter table formats add constraint formats_channel_id_id_key unique (channel_id, id);

create table categories (
  id              uuid primary key default gen_random_uuid(),
  user_id         text not null references "user"(id) on delete cascade,
  channel_id      uuid not null references channels(id) on delete cascade,
  name            text not null check (length(name) between 1 and 60),
  color           text not null default '#818cf8' check (color ~ '^#[0-9a-fA-F]{6}$'),
  -- The editorial brief: what this category covers, what to take and what to refuse.
  brief           text not null default '',
  keywords        text not null default '',
  format_id       uuid,
  ideas_per_batch int  not null default 6 check (ideas_per_batch between 1 and 30),
  enabled         boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (channel_id, name),
  foreign key (channel_id, format_id) references formats (channel_id, id) on delete set null (format_id)
);
create index categories_channel on categories (channel_id);

create table category_sources (
  id              uuid primary key default gen_random_uuid(),
  user_id         text not null references "user"(id) on delete cascade,
  category_id     uuid not null references categories(id) on delete cascade,
  -- reddit: a community name · site: a domain (its feeds are discovered) · rss: a
  -- feed URL · search: news search terms · google_trends: a 2-letter country ·
  -- wikipedia: a language code.
  kind            text not null check (kind in ('reddit','site','rss','search','google_trends','wikipedia')),
  value           text not null check (length(value) between 1 and 500),
  options         jsonb not null default '{}'::jsonb,
  enabled         boolean not null default true,
  -- Written by the ideas worker only.
  status          text not null default 'new' check (status in ('new','ok','error')),
  checked_at      timestamptz,
  last_fetched_at timestamptz,
  last_items      int,
  last_error      text,
  fail_count      int not null default 0,
  next_try_at     timestamptz,
  created_at      timestamptz not null default now(),
  unique (category_id, kind, value),
  check (kind <> 'reddit' or value ~ '^[A-Za-z0-9_]{2,21}$'),
  check (kind <> 'google_trends' or value ~ '^[A-Z]{2}$'),
  -- Reddit is reached only through the rate-limited reddit source, never as a feed.
  check (kind not in ('rss','site') or value !~* '(^|[./])reddit\.com([/:]|$)')
);

alter table categories       enable row level security;
alter table category_sources enable row level security;
create policy own on categories
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true)
              and exists (select 1 from channels c where c.id = categories.channel_id
                            and c.user_id = current_setting('app.user_id', true)));
create policy own on category_sources
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true)
              and exists (select 1 from categories k where k.id = category_sources.category_id
                            and k.user_id = current_setting('app.user_id', true)));

create trigger categories_touch before update on categories
  for each row execute function private.touch_updated_at();

-- An old-style source ({name, url}) as a category source.
create or replace function private.source_from_url(p_url text, p_name text,
                                                   out kind text, out value text, out options jsonb)
language plpgsql immutable set search_path = '' as $fn$
declare m text[];
begin
  m := regexp_match(p_url, '^https?://(?:www\.|old\.)?reddit\.com/r/([A-Za-z0-9_+]+)(?:/(hot|new|top|rising))?', 'i');
  if m is not null then
    kind := 'reddit'; value := m[1];
    options := jsonb_build_object('sort', coalesce(lower(m[2]), 'top'),
                                  't', coalesce(substring(p_url from '[?&]t=([a-z]+)'), 'day'));
    return;
  end if;
  m := regexp_match(p_url, 'trends\.google\.[a-z.]+/trending/rss\?(?:[^#]*&)?geo=([A-Za-z]{2})', 'i');
  if m is not null then
    kind := 'google_trends'; value := upper(m[1]); options := '{}'::jsonb;
    return;
  end if;
  if p_url ~* '^https?://api\.wikimedia\.org/feed/' then
    kind := 'wikipedia'; value := coalesce(substring(p_url from 'wikipedia/([a-z]{2,3})/'), 'en');
    options := '{}'::jsonb;
    return;
  end if;
  kind := 'rss'; value := p_url; options := jsonb_build_object('name', coalesce(p_name, ''));
end $fn$;

-- Copy a format's old-style sources into a category (communities split on '+').
create or replace function private.adopt_sources(p_category_id uuid, p_sources jsonb) returns void
language sql security definer set search_path = '' as $fn$
  insert into public.category_sources (user_id, category_id, kind, value, options)
  select k.user_id, k.id, s.kind, v, s.options
    from public.categories k
   cross join lateral jsonb_array_elements(coalesce(p_sources, '[]'::jsonb)) e
   cross join lateral private.source_from_url(e->>'url', e->>'name') s
   cross join lateral unnest(case when s.kind = 'reddit' then string_to_array(s.value, '+')
                                  else array[s.value] end) v
   where k.id = p_category_id and e->>'url' is not null
  on conflict do nothing;
$fn$;

-- Existing data: one category per format (the default one is "General"), its
-- sources carried over, and every idea tagged with its format's category.
insert into categories (user_id, channel_id, name, format_id, ideas_per_batch)
select f.user_id, f.channel_id, case when f.is_default then 'General' else f.name end, f.id,
       least(f.ideas_per_batch, 30)
  from formats f
on conflict (channel_id, name) do nothing;
select private.adopt_sources(k.id, f.sources)
  from categories k join formats f on f.id = k.format_id;

-- Every channel always has a category: its first format brings a "General" one,
-- with that format's starting sources.
create or replace function private.ensure_category() returns trigger
language plpgsql security definer set search_path = '' as $fn$
declare cid uuid;
begin
  if not exists (select 1 from public.categories where channel_id = new.channel_id) then
    insert into public.categories (user_id, channel_id, name, format_id)
    values (new.user_id, new.channel_id, 'General', new.id)
    on conflict do nothing
    returning id into cid;
    if cid is not null then
      perform private.adopt_sources(cid, new.sources);
    end if;
  end if;
  return null;
end $fn$;
create trigger formats_ensure_category after insert on formats
  for each row execute function private.ensure_category();

-- Sources and batch size now live on categories: a format's versions track only
-- what shapes the video and the idea prompt.
create or replace function private.format_versioning() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  if (new.idea_prompt, new.script_prompt, new.visual_style, new.audio_source, new.target_seconds)
     is distinct from
     (old.idea_prompt, old.script_prompt, old.visual_style, old.audio_source, old.target_seconds) then
    insert into public.format_versions (format_id, version, snapshot)
    values (old.id, old.version, jsonb_build_object(
              'idea_prompt', old.idea_prompt, 'script_prompt', old.script_prompt,
              'visual_style', old.visual_style, 'audio_source', old.audio_source,
              'target_seconds', old.target_seconds))
    on conflict do nothing;
    new.version := old.version + 1;
  end if;
  new.updated_at := now();
  return new;
end $fn$;

create or replace function api.restore_format_version(p_format_id uuid, p_version int)
returns public.formats
language plpgsql security definer set search_path = '' as $fn$
declare
  f public.formats := private.owned_format(p_format_id);
  v jsonb;
begin
  select snapshot into v from public.format_versions where format_id = f.id and version = p_version;
  if not found then
    raise exception 'that version does not exist' using errcode = 'P0002';
  end if;
  update public.formats
     set idea_prompt = v->>'idea_prompt', script_prompt = v->>'script_prompt',
         visual_style = v->>'visual_style', audio_source = v->>'audio_source',
         target_seconds = (v->>'target_seconds')::int
   where id = f.id
  returning * into f;
  return f;
end $fn$;

-- ── ideas carry their posts and media ─────────────────────────────────────────
alter table ideas
  add column category_id  uuid references categories(id) on delete set null,
  -- The trend items the idea came from: [{url, title, source, subreddit, author, published, rank}]
  add column items        jsonb not null default '[]'::jsonb,
  -- [{type: image|video, key, poster_key, w, h, seconds, origin, source_url, credit}]
  add column media        jsonb not null default '[]'::jsonb,
  add column media_state  text not null default 'none'
                          check (media_state in ('pending','ready','none','expired')),
  -- Vision description of the media, logo/watermark flags, moderation result.
  add column analysis     jsonb,
  add column batch_job_id uuid;
update ideas i set category_id = k.id from categories k where k.format_id = i.format_id;
create index ideas_category on ideas (category_id, status);

-- ── posts: category, Manual/Automatic snapshot, media choice ──────────────────
alter table posts
  add column category_id   uuid references categories(id) on delete set null,
  add column pipeline_mode text not null default 'manual' check (pipeline_mode in ('manual','auto')),
  add column media_choice  text check (media_choice in ('original','ai','none'));

alter table app_settings
  add column pipeline_mode            text not null default 'manual'
                                      check (pipeline_mode in ('manual','auto')),
  -- Automatic mode stops starting renders once today's spend reaches this (paise).
  add column auto_spend_cap_paise_day int default 50000 check (auto_spend_cap_paise_day >= 0),
  add column vision_model             text,
  add column usd_inr_override         numeric check (usd_inr_override > 0);

create or replace function private.snapshot_auto_approve() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  select coalesce(s.auto_approve, false), coalesce(s.pipeline_mode, 'manual')
    into new.auto_approve, new.pipeline_mode
    from public.app_settings s where s.user_id = new.user_id;
  new.pipeline_mode := coalesce(new.pipeline_mode, 'manual');
  new.auto_approve := coalesce(new.auto_approve, false) or new.pipeline_mode = 'auto';
  return new;
end $fn$;

-- ── the cost ledger ───────────────────────────────────────────────────────────
create table costs (
  id          bigserial primary key,
  user_id     text not null references "user"(id) on delete cascade,
  channel_id  uuid references channels(id) on delete set null,
  category_id uuid references categories(id) on delete set null,
  post_id     uuid references posts(id) on delete set null,
  job_id      uuid,
  kind        text not null check (kind in ('llm','vision','moderation','image','tts','gpu','pod_storage')),
  provider    text not null,
  model       text,
  -- tokens {input, cached_input, output}, images, seconds, pod id… whatever was billed.
  quantity    jsonb not null default '{}'::jsonb,
  usd_micros  bigint,          -- null: the model's price is unknown
  inr_paise   bigint,
  fx_usd_inr  numeric,         -- the rate on the day, frozen with the row
  note        text,
  created_at  timestamptz not null default now()
);
create index costs_user_time on costs (user_id, created_at desc);
create index costs_post on costs (post_id) where post_id is not null;
alter table costs enable row level security;
create policy own on costs using (user_id = current_setting('app.user_id', true));

-- What each model costs, per user (a SaaS user's prices are their own business).
create table prices (
  user_id           text not null references "user"(id) on delete cascade,
  model             text not null check (length(model) between 1 and 100),
  input_per_m       numeric check (input_per_m >= 0),        -- USD per 1M input tokens
  cached_input_per_m numeric check (cached_input_per_m >= 0),
  output_per_m      numeric check (output_per_m >= 0),
  per_image         numeric check (per_image >= 0),          -- USD per image (vision input or generated)
  updated_at        timestamptz not null default now(),
  primary key (user_id, model)
);
alter table prices enable row level security;
create policy own on prices
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true));

-- USD→INR by day (ECB reference rate), for converting OpenAI dollars.
create table fx_rates (
  day        date primary key,
  usd_inr    numeric not null check (usd_inr > 0),
  source     text not null,
  fetched_at timestamptz not null default now()
);

-- Today's spend in paise, in the owner's timezone.
create or replace function private.spent_today_paise(p_user_id text) returns bigint
language sql stable security definer set search_path = '' as $fn$
  with tz as (select coalesce((select timezone from public.app_settings where user_id = p_user_id),
                              'Asia/Kolkata') as z)
  select coalesce(sum(coalesce(c.inr_paise, 0)
                      + coalesce(c.usd_micros, 0) * coalesce(c.fx_usd_inr, 85) / 10000), 0)::bigint
    from public.costs c, tz
   where c.user_id = p_user_id
     and c.created_at >= (date_trunc('day', now() at time zone tz.z) at time zone tz.z);
$fn$;

-- ── private cores + api wrappers ──────────────────────────────────────────────

create or replace function private.generate_script(p_post_id uuid, p_actor text) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  p   public.posts;
  nxt int;
begin
  select * into p from public.posts where id = p_post_id for update;
  if not found then
    raise exception 'post not found' using errcode = 'P0002';
  end if;
  if p.status not in ('draft','awaiting_approval','failed') then
    raise exception 'cannot (re)write the script of a post in status %', p.status
      using errcode = '55000';
  end if;
  select coalesce(max(version), 0) + 1 into nxt from public.scripts where post_id = p.id;
  update public.posts set status = 'scripting', error = null where id = p.id;
  perform private.log_post_event(p.id, p.status, 'scripting', p_actor, 'script requested');
  return private.enqueue_job(p.user_id, 'cpu', 'write_script',
                             format('write_script:%s:v%s', p.id, nxt),
                             jsonb_build_object('version', nxt), p.id,
                             p_max_attempts => 3, p_lease_seconds => 300);
end $fn$;

create or replace function api.generate_script(p_post_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
begin
  perform private.owned_post(p_post_id);
  return private.generate_script(p_post_id, 'user:' || private.caller());
end $fn$;

-- Render (or, when every shot is already rendered, re-assemble). An automatic
-- request (actor 'system:auto') stops at the owner's daily spending cap.
create or replace function private.request_render(p_post_id uuid, p_actor text) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  p          public.posts;
  cap        int;
  n_shots    int;
  n_ready    int;
  n_rendered int;
  j          public.jobs;
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
  select count(*),
         count(*) filter (where p.audio_source <> 'kokoro' or narration_key is not null),
         count(*) filter (where state = 'uploaded')
    into n_shots, n_ready, n_rendered
    from public.shots where script_id = p.approved_script_id;
  if n_shots = 0 or n_ready < n_shots then
    raise exception 'shots are still being planned or voiced; try again in a moment'
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

create or replace function api.request_render(p_post_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
begin
  perform private.owned_post(p_post_id);
  return private.request_render(p_post_id, 'user:' || private.caller());
end $fn$;

create or replace function private.request_publish(p_post_id uuid, p_platforms text[],
                                                   p_at timestamptz, p_youtube_privacy text,
                                                   p_actor text)
returns setof public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  p    public.posts;
  at_  timestamptz := greatest(coalesce(p_at, now()), now());
  pf   text;
  name text;
  key  text;
  j    public.jobs;
begin
  select * into p from public.posts where id = p_post_id;
  if not found then
    raise exception 'post not found' using errcode = 'P0002';
  end if;
  if p.final_key is null or p.status not in ('ready','scheduled','published','needs_review') then
    raise exception 'only a finished reel can be posted (this one is %)', p.status
      using errcode = '55000';
  end if;
  if coalesce(cardinality(p_platforms), 0) = 0 then
    raise exception 'choose where to post it' using errcode = '22023';
  end if;
  if p_youtube_privacy is not null and p_youtube_privacy not in ('private','unlisted','public') then
    raise exception 'YouTube visibility must be private, unlisted or public' using errcode = '22023';
  end if;
  if at_ > now() + interval '180 days' then
    raise exception 'schedule it within the next 180 days' using errcode = '22023';
  end if;

  foreach pf in array p_platforms loop
    if pf not in ('youtube','instagram') then
      raise exception 'unknown platform %', pf using errcode = '22023';
    end if;
    name := case pf when 'youtube' then 'YouTube' else 'Instagram' end;
    key := format('publish:%s:%s', p.id, pf);
    if not exists (select 1 from public.channel_accounts
                    where channel_id = p.channel_id and platform = pf and status = 'connected') then
      raise exception 'connect % to this channel first', name using errcode = '55000';
    end if;
    if exists (select 1 from public.publish_attempts
                where post_id = p.id and platform = pf and state = 'live') then
      raise exception 'it is already posted on %', name using errcode = '55000';
    end if;
    if exists (select 1 from public.jobs where dedupe_key = key and state = 'claimed') then
      raise exception 'it is being posted to % right now', name using errcode = '55000';
    end if;

    j := private.enqueue_job(p.user_id, 'publish', 'publish_post', key,
                             jsonb_strip_nulls(jsonb_build_object(
                               'platform', pf,
                               'privacy', case when pf = 'youtube' then p_youtube_privacy end)), p.id,
                             p_priority => 50, p_max_attempts => 3, p_lease_seconds => 900,
                             p_not_before => at_);
    update public.jobs
       set state = 'queued', not_before = at_, attempts = 0, max_attempts = 3,
           payload = jsonb_strip_nulls(jsonb_build_object(
             'platform', pf, 'privacy', case when pf = 'youtube' then p_youtube_privacy end)),
           error = null, result = null, claimed_by = null, claimed_at = null,
           lease_expires_at = null, finished_at = null
     where id = j.id and state in ('queued','needs_review','succeeded');
    select * into j from public.jobs where id = j.id;
    return next j;
  end loop;

  update public.posts
     set publish_at = at_, slot_date = (at_ at time zone p.publish_tz)::date
   where id = p.id;
  perform private.log_post_event(p.id, p.status, p.status, p_actor,
    format('%s to %s', case when at_ <= now() + interval '1 minute' then 'posting now'
                            else 'scheduled' end,
           array_to_string(array(select case x when 'youtube' then 'YouTube' else 'Instagram' end
                                   from unnest(p_platforms) x), ' and ')),
    jsonb_build_object('platforms', p_platforms, 'at', at_));
end $fn$;

create or replace function api.request_publish(p_post_id uuid, p_platforms text[],
                                               p_at timestamptz default null,
                                               p_youtube_privacy text default null)
returns setof public.jobs
language plpgsql security definer set search_path = '' as $fn$
begin
  perform private.owned_post(p_post_id);
  return query select * from private.request_publish(p_post_id, p_platforms, p_at, p_youtube_privacy,
                                                     'user:' || private.caller());
end $fn$;

-- ── idea batches per category ─────────────────────────────────────────────────

create or replace function private.owned_category(p_category_id uuid) returns public.categories
language plpgsql stable security definer set search_path = '' as $fn$
declare k public.categories;
begin
  select * into k from public.categories where id = p_category_id and user_id = private.caller();
  if not found then
    raise exception 'category not found' using errcode = 'P0002';
  end if;
  return k;
end $fn$;

create or replace function private.queue_category_ideas(k public.categories, p_trigger text,
                                                        p_key text, p_not_before timestamptz,
                                                        p_priority int)
returns public.jobs
language sql security definer set search_path = '' as $fn$
  select private.enqueue_job(k.user_id, 'ideas', 'suggest_ideas', p_key,
                             jsonb_build_object('category_id', k.id, 'channel_id', k.channel_id,
                                                'trigger', p_trigger), null,
                             p_priority => p_priority, p_max_attempts => 2, p_lease_seconds => 900,
                             p_not_before => p_not_before);
$fn$;

-- [More ideas] for one category. Double-taps within a minute share one job.
create or replace function api.request_category_ideas(p_category_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare k public.categories := private.owned_category(p_category_id);
begin
  return private.queue_category_ideas(k, 'manual',
    format('suggest_ideas:cat:%s:%s', k.id, to_char(now(), 'YYYYMMDDHH24MI')), now(), 60);
end $fn$;

-- [More ideas] for every enabled category of a channel. Returns how many were queued.
create or replace function api.request_channel_ideas(p_channel_id uuid) returns int
language plpgsql security definer set search_path = '' as $fn$
declare
  c public.channels := private.owned_channel(p_channel_id);
  k public.categories;
  n int := 0;
begin
  for k in select * from public.categories where channel_id = c.id and enabled order by created_at loop
    perform private.queue_category_ideas(k, 'manual',
      format('suggest_ideas:cat:%s:%s', k.id, to_char(now(), 'YYYYMMDDHH24MI')), now(), 60);
    n := n + 1;
  end loop;
  return n;
end $fn$;

-- The old per-format button, kept working while an older web app is still running.
create or replace function api.request_ideas(p_format_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  f   public.formats := private.owned_format(p_format_id);
  cid uuid;
begin
  select id into cid from public.categories where channel_id = f.channel_id and enabled
   order by (format_id = f.id) desc nulls last, created_at limit 1;
  if cid is null then
    raise exception 'this channel has no enabled category' using errcode = '55000';
  end if;
  return api.request_category_ideas(cid);
end $fn$;

-- Daily: every enabled category of every channel with daily ideas, staggered by
-- three minutes so they don't all wait on Reddit's one-request-a-minute limit at once.
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
            where c.ideas_daily loop
    d := (now() at time zone r.timezone)::date;
    k := format('suggest_ideas:cat:%s:daily:%s', r.id, d);
    -- On the day this migration lands, a channel's old per-format batch may
    -- already exist: don't run a second one.
    if exists (select 1 from public.jobs j join public.formats f
                 on j.dedupe_key = format('suggest_ideas:%s:daily:%s', f.id, d)
                where f.channel_id = r.channel_id) then
      continue;
    end if;
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

-- A swipe, with the platforms to post to. Right: the post is created at that
-- moment, in the idea's category; in automatic mode its script starts at once.
create or replace function api.decide_idea_v2(p_idea_id uuid, p_accept boolean,
                                              p_publish_at timestamptz default null,
                                              p_reason text default null,
                                              p_platforms text[] default null) returns public.ideas
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
  if mode = 'auto' then
    perform private.generate_script(pid, 'system:auto');
  end if;
  return i;
end $fn$;

-- The old 4-argument swipe, kept working while an older web app is still running.
create or replace function api.decide_idea(p_idea_id uuid, p_accept boolean,
                                           p_publish_at timestamptz default null,
                                           p_reason text default null) returns public.ideas
language plpgsql security definer set search_path = '' as $fn$
begin
  return api.decide_idea_v2(p_idea_id, p_accept, p_publish_at, p_reason, null);
end $fn$;

-- Check a category's sources now (after adding some), and ask the agent which
-- communities and sites suit it. Both run on the ideas lane, the only worker
-- that contacts Reddit; the answers land in the job's result and on the sources.
create or replace function api.check_category_sources(p_category_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare k public.categories := private.owned_category(p_category_id);
begin
  return private.enqueue_job(k.user_id, 'ideas', 'check_sources',
                             format('check_sources:%s:%s', k.id, to_char(now(), 'YYYYMMDDHH24MI')),
                             jsonb_build_object('category_id', k.id), null,
                             p_priority => 50, p_max_attempts => 1, p_lease_seconds => 900);
end $fn$;

create or replace function api.suggest_category_sources(p_category_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare k public.categories := private.owned_category(p_category_id);
begin
  return private.enqueue_job(k.user_id, 'ideas', 'suggest_sources',
                             format('suggest_sources:%s:%s', k.id, to_char(now(), 'YYYYMMDDHH24MI')),
                             jsonb_build_object('category_id', k.id), null,
                             p_priority => 50, p_max_attempts => 1, p_lease_seconds => 900);
end $fn$;
