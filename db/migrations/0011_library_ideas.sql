-- Channels, the prompt library ("formats"), the idea feed, connected accounts,
-- and many posts per day.
--
-- A channel is one YouTube/Instagram presence with its own identity (niche,
-- audience, voice, language, timezone). The existing channel profile in
-- app_settings becomes each user's first channel.
--
-- A format is a kind of video a channel makes ("3D explainer", "Meme"), holding
-- every prompt that shapes it: the idea agent's, the script writer's, the visual
-- style added to every shot, and the trend sources the agent reads. Saving a
-- format keeps its previous version in format_versions, so any edit can be undone.
--
-- Ideas are the agent's suggestions, swiped in the app. Accepting one schedules a
-- post at a date and time (many per day now); rejecting one, with a reason, steers
-- the next batch.
--
-- channel_accounts hold the OAuth connections (YouTube, Instagram). Their tokens
-- are encrypted like user_keys and, like them, write-only from the web.

create table channels (
  id                   uuid primary key default gen_random_uuid(),
  user_id              text not null references "user"(id) on delete cascade,
  name                 text not null check (length(name) between 1 and 80),
  niche                text not null default '',
  audience             text not null default '',
  voice                text not null default '',
  language             text not null default 'English',
  timezone             text not null default 'Asia/Kolkata',
  default_publish_time time not null default '18:00',
  ideas_daily          boolean not null default true,
  ideas_daily_at       time not null default '08:00',
  is_default           boolean not null default false,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (user_id, name)
);
create unique index channels_one_default on channels (user_id) where is_default;

insert into channels (user_id, name, niche, audience, voice, language, timezone, is_default)
select user_id, coalesce(nullif(btrim(channel_name), ''), 'My channel'), coalesce(channel_niche, ''),
       coalesce(channel_audience, ''), coalesce(channel_voice, ''),
       coalesce(nullif(script_language, ''), 'English'), timezone, true
  from app_settings;

create table formats (
  id              uuid primary key default gen_random_uuid(),
  user_id         text not null references "user"(id) on delete cascade,
  channel_id      uuid not null references channels(id) on delete cascade,
  name            text not null check (length(name) between 1 and 60),
  description     text not null default '',
  is_default      boolean not null default false,
  audio_source    text not null default 'kokoro' check (audio_source in ('ltx_native','kokoro')),
  target_seconds  int  not null default 40 check (target_seconds between 5 and 300),
  idea_prompt     text not null,
  script_prompt   text not null,
  visual_style    text not null default '',
  -- [{"name": "...", "url": "..."}]: RSS/Atom feeds or known JSON feeds.
  sources         jsonb not null default '[]'::jsonb,
  ideas_per_batch int  not null default 10 check (ideas_per_batch between 1 and 30),
  version         int  not null default 1,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (channel_id, name)
);
create unique index formats_one_default on formats (channel_id) where is_default;

create table format_versions (
  format_id uuid not null references formats(id) on delete cascade,
  version   int  not null,
  snapshot  jsonb not null,
  saved_at  timestamptz not null default now(),
  primary key (format_id, version)
);

-- What a format makes changed: keep the old version first and bump the number.
create or replace function private.format_versioning() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  if (new.idea_prompt, new.script_prompt, new.visual_style, new.sources, new.audio_source,
      new.target_seconds, new.ideas_per_batch)
     is distinct from
     (old.idea_prompt, old.script_prompt, old.visual_style, old.sources, old.audio_source,
      old.target_seconds, old.ideas_per_batch) then
    insert into public.format_versions (format_id, version, snapshot)
    values (old.id, old.version, jsonb_build_object(
              'idea_prompt', old.idea_prompt, 'script_prompt', old.script_prompt,
              'visual_style', old.visual_style, 'sources', old.sources,
              'audio_source', old.audio_source, 'target_seconds', old.target_seconds,
              'ideas_per_batch', old.ideas_per_batch))
    on conflict do nothing;
    new.version := old.version + 1;
  end if;
  new.updated_at := now();
  return new;
end $fn$;
create trigger formats_versioning before update on formats
  for each row execute function private.format_versioning();

-- Many posts a day, each at its own time (publish_at). The calendar groups by
-- slot_date, the day in the channel's timezone.
alter table posts drop constraint posts_user_id_slot_date_key;
alter table posts add column channel_id uuid references channels(id) on delete set null,
                  add column format_id  uuid references formats(id) on delete set null;
update posts p set channel_id = c.id from channels c where c.user_id = p.user_id and c.is_default;
create index posts_user_publish on posts (user_id, publish_at);

-- Which format (and version of it) wrote a script.
alter table scripts add column format_id uuid references formats(id) on delete set null,
                    add column format_version int;

create table ideas (
  id            uuid primary key default gen_random_uuid(),
  user_id       text not null references "user"(id) on delete cascade,
  channel_id    uuid not null references channels(id) on delete cascade,
  format_id     uuid references formats(id) on delete set null,
  title         text not null,
  hook          text not null default '',
  brief         text not null,
  why_now       text not null default '',
  sources       jsonb not null default '[]'::jsonb,   -- [{"title": "...", "url": "..."}]
  status        text not null default 'new' check (status in ('new','accepted','rejected')),
  reject_reason text,
  post_id       uuid references posts(id) on delete set null,
  created_at    timestamptz not null default now(),
  decided_at    timestamptz
);
create index ideas_channel_status on ideas (channel_id, status, created_at desc);

create table channel_accounts (
  id               uuid primary key default gen_random_uuid(),
  user_id          text not null references "user"(id) on delete cascade,
  channel_id       uuid not null references channels(id) on delete cascade,
  platform         text not null check (platform in ('youtube','instagram')),
  external_id      text not null,          -- YouTube channel id / Instagram user id
  handle           text,
  display_name     text,
  avatar_url       text,
  -- YouTube: the refresh token. Instagram: the long-lived access token. AES-GCM
  -- under APP_ENCRYPTION_KEY (lib/crypto.ts, corpus/crypto.py); never selectable.
  token_ciphertext text not null,
  token_expires_at timestamptz,
  scopes           text[] not null default '{}',
  status           text not null default 'connected' check (status in ('connected','expired','revoked')),
  connected_at     timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (channel_id, platform)
);

-- ── row-level security (policies name no role: see 0004) ──────────────────────
alter table channels         enable row level security;
alter table formats          enable row level security;
alter table format_versions  enable row level security;
alter table ideas            enable row level security;
alter table channel_accounts enable row level security;
create policy own on channels
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true));
create policy own on formats
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true)
              and exists (select 1 from channels c where c.id = formats.channel_id
                            and c.user_id = current_setting('app.user_id', true)));
create policy own on format_versions
  using (exists (select 1 from formats f where f.id = format_versions.format_id
                   and f.user_id = current_setting('app.user_id', true)));
create policy own on ideas
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true));
create policy own on channel_accounts
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true)
              and exists (select 1 from channels c where c.id = channel_accounts.channel_id
                            and c.user_id = current_setting('app.user_id', true)));

-- ── api ───────────────────────────────────────────────────────────────────────

create or replace function private.owned_format(p_format_id uuid) returns public.formats
language plpgsql stable security definer set search_path = '' as $fn$
declare f public.formats;
begin
  select * into f from public.formats where id = p_format_id and user_id = private.caller();
  if not found then
    raise exception 'format not found' using errcode = 'P0002';
  end if;
  return f;
end $fn$;

create or replace function private.owned_channel(p_channel_id uuid) returns public.channels
language plpgsql stable security definer set search_path = '' as $fn$
declare c public.channels;
begin
  select * into c from public.channels where id = p_channel_id and user_id = private.caller();
  if not found then
    raise exception 'channel not found' using errcode = 'P0002';
  end if;
  return c;
end $fn$;

-- [Find ideas]: a batch for this format, now. Double-taps within a minute share one job.
create or replace function api.request_ideas(p_format_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare f public.formats := private.owned_format(p_format_id);
begin
  return private.enqueue_job(f.user_id, 'cpu', 'suggest_ideas',
                             format('suggest_ideas:%s:%s', f.id, to_char(now(), 'YYYYMMDDHH24MI')),
                             jsonb_build_object('format_id', f.id, 'trigger', 'manual'), null,
                             p_priority => 60, p_max_attempts => 2, p_lease_seconds => 600);
end $fn$;

-- A swipe. Right: schedule it, creating the post at that moment. Left: keep the
-- reason, so the agent learns what not to suggest.
create or replace function api.decide_idea(p_idea_id uuid, p_accept boolean,
                                           p_publish_at timestamptz default null,
                                           p_reason text default null) returns public.ideas
language plpgsql security definer set search_path = '' as $fn$
declare
  i   public.ideas;
  f   public.formats;
  c   public.channels;
  s   public.app_settings;
  pid uuid;
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
  select * into c from public.channels where id = i.channel_id;
  select * into f from public.formats where id = i.format_id;
  select * into s from public.app_settings where user_id = i.user_id;
  insert into public.posts (user_id, channel_id, format_id, topic, brief, slot_date, publish_tz,
                            publish_at, audio_source, target_seconds)
  values (i.user_id, c.id, f.id, left(i.title, 300),
          concat_ws(E'\n\n', i.brief, nullif('Hook: ' || i.hook, 'Hook: '),
                    nullif('Why now: ' || i.why_now, 'Why now: ')),
          (p_publish_at at time zone c.timezone)::date, c.timezone, p_publish_at,
          coalesce(f.audio_source, s.default_audio_source, 'kokoro'), f.target_seconds)
  returning id into pid;
  update public.ideas set status = 'accepted', decided_at = now(), post_id = pid
   where id = i.id returning * into i;
  return i;
end $fn$;

create or replace function api.set_default_format(p_format_id uuid) returns void
language plpgsql security definer set search_path = '' as $fn$
declare f public.formats := private.owned_format(p_format_id);
begin
  update public.formats set is_default = false
   where channel_id = f.channel_id and is_default and id <> f.id;
  update public.formats set is_default = true where id = f.id;
end $fn$;

create or replace function api.set_default_channel(p_channel_id uuid) returns void
language plpgsql security definer set search_path = '' as $fn$
declare c public.channels := private.owned_channel(p_channel_id);
begin
  update public.channels set is_default = false
   where user_id = c.user_id and is_default and id <> c.id;
  update public.channels set is_default = true where id = c.id;
end $fn$;

-- Put an earlier version back (the current one is kept as a version too).
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
         visual_style = v->>'visual_style', sources = v->'sources',
         audio_source = v->>'audio_source', target_seconds = (v->>'target_seconds')::int,
         ideas_per_batch = (v->>'ideas_per_batch')::int
   where id = f.id
  returning * into f;
  return f;
end $fn$;

-- The cpu worker calls this on every tick: one daily idea batch per channel, for
-- its default format, at ideas_daily_at in the channel's timezone. Only creates
-- today's job if none exists, so a failed batch is not retried in a loop.
create or replace function private.schedule_daily_ideas() returns int
language plpgsql security definer set search_path = '' as $fn$
declare
  r   record;
  d   date;
  k   text;
  n   int := 0;
begin
  for r in select c.user_id, c.timezone, c.ideas_daily_at, f.id as format_id
             from public.channels c
             join public.formats f on f.channel_id = c.id and f.is_default
            where c.ideas_daily loop
    d := (now() at time zone r.timezone)::date;
    k := format('suggest_ideas:%s:daily:%s', r.format_id, d);
    if not exists (select 1 from public.jobs where dedupe_key = k) then
      perform private.enqueue_job(r.user_id, 'cpu', 'suggest_ideas', k,
                                  jsonb_build_object('format_id', r.format_id, 'trigger', 'daily'), null,
                                  p_priority => 90, p_max_attempts => 2, p_lease_seconds => 600,
                                  p_not_before => (d + r.ideas_daily_at) at time zone r.timezone);
      n := n + 1;
    end if;
  end loop;
  return n;
end $fn$;
