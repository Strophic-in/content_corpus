-- Phase 4 (TrendCaster parity), baseline:
--
--   research   an accepted idea's sources are read in full (the article text, not the
--              feed's two lines) plus a few other outlets' reports of the same story,
--              by the ideas lane; the script waits for them and writes from them.
--   music      the script picks a mood; assembly lays a CC0 track from Freesound
--              under the reel (quietly), never repeating the owner's last 20.
--   stats      how published reels did (views, likes, comments), read back daily and
--              shown to the idea agent.
--   health     the workers' own checks of what they depend on, for the Health page.

alter table posts
  add column research       jsonb,
  add column research_state text check (research_state in ('pending','ready','none')),
  add column music          jsonb;

alter table scripts add column music_mood text;

-- A chart shot (source 'chart'): {title, labels, values, unit}, drawn by the cpu lane.
alter table shots drop constraint shots_source_check,
  add constraint shots_source_check check (source in ('generate','clip','image','stock','chart')),
  add column chart jsonb;

create table post_stats (
  post_id    uuid not null references posts(id) on delete cascade,
  user_id    text not null references "user"(id) on delete cascade,
  platform   text not null check (platform in ('youtube','instagram')),
  views      bigint,
  likes      bigint,
  comments   bigint,
  fetched_at timestamptz not null default now(),
  primary key (post_id, platform)
);
alter table post_stats enable row level security;
create policy own on post_stats using (user_id = current_setting('app.user_id', true));

-- Workers' checks (no secrets in `detail`): one row per check, replaced each run.
create table health_checks (
  name       text primary key,
  ok         boolean not null,
  detail     text not null default '',
  checked_at timestamptz not null default now()
);

-- An idea accepted → its post's research is queued (before any script is asked for,
-- so a script requested at once — Automatic mode — waits for it).
create or replace function private.research_accepted_idea() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  if new.status = 'accepted' and new.post_id is not null and old.status is distinct from 'accepted' then
    update public.posts set research_state = 'pending' where id = new.post_id and research_state is null;
    perform private.enqueue_job(new.user_id, 'ideas', 'research_post', format('research_post:%s', new.post_id),
                                jsonb_build_object('post_id', new.post_id, 'idea_id', new.id), new.post_id,
                                p_priority => 35, p_max_attempts => 2, p_lease_seconds => 600);
  end if;
  return new;
end $fn$;

create trigger ideas_research_on_accept after update of status on ideas
  for each row execute function private.research_accepted_idea();
