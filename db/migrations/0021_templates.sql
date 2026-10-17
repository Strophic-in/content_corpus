-- Templates: 22 ways to make a post, and categories that use several of them.
--
--   templates  the registry's keys (prompts/templates/<id>.json holds the rest:
--              structure, assets, music, cost, render defaults). A format is one
--              template plus the owner's prompts and `params` (fonts, colours,
--              caption position, transitions, music mode, slides). Its content
--              type — video, carousel or image — follows the template.
--   categories now allow several formats (`format_ids`, empty = any of the
--              channel's); the idea agent picks one per idea and the owner can
--              change it on the swipe. Ideas per batch default to 2.
--   posts      of a carousel or image format are made as slides (Instagram) plus a
--              slideshow Short (YouTube): `posts.slides`, `scripts.slides`; no shots.
--   shots      carry their on-screen fields (role, text, label, layout,
--              transition, panel, focus, timelapse) in `extras`; a "plain" shot is
--              the format's background colour, drawn on the server.
--   audio      'none' joins 'kokoro' and 'ltx_native': no voice — text, music and
--              the pictures' own sound.
--   uploads    the owner's own videos and photos (api.start_upload →
--              a signed PUT straight to R2 → api.finish_upload): owned, approved,
--              uncredited, normalised and analysed like any footage.

-- ── the registry's keys ───────────────────────────────────────────────────────
create table templates (
  template_id  text primary key check (template_id ~ '^[a-z0-9_]{3,60}$'),
  content_type text not null check (content_type in ('video','carousel','image')),
  display_name text not null
);
insert into templates (template_id, content_type, display_name) values
  ('cinematic_3d_explainer',       'video',    'Cinematic 3D Explainer'),
  ('full_screen_text_overlay',     'video',    'Full-Screen Video With Text Overlay'),
  ('top_bottom_split_screen',      'video',    'Top/Bottom Split Screen'),
  ('educational_carousel',         'carousel', 'Educational Carousel'),
  ('animated_infographic',         'video',    'Animated Infographic / Data Story'),
  ('documentary_storytelling',     'video',    'Documentary-Style Storytelling'),
  ('podcast_interview_clip',       'video',    'Podcast / Interview Clip'),
  ('pov_immersive_scenario',       'video',    'POV / Immersive Scenario'),
  ('transformation_match_cut',     'video',    'Transformation / Match-Cut Reveal'),
  ('photo_dump_collage',           'carousel', 'Photo Dump / Collage Carousel'),
  ('before_after_comparison',      'video',    'Before vs. After Comparison'),
  ('myth_vs_fact',                 'video',    'Myth vs. Fact'),
  ('ranked_countdown',             'video',    'Ranked List / Countdown'),
  ('screen_recording_tutorial',    'video',    'Screen Recording / Tutorial Walkthrough'),
  ('kinetic_typography',           'video',    'Kinetic Typography / Text-Only Motion'),
  ('mini_news_explainer',          'video',    'Mini News Explainer'),
  ('question_answer_demo',         'video',    'Question → Answer → Demonstration'),
  ('satisfying_process_timelapse', 'video',    'Satisfying Process / Timelapse'),
  ('reaction_commentary',          'video',    'Reaction / Commentary With Context'),
  ('seamless_loop',                'video',    'Looping Reel / Seamless Loop'),
  ('picture_above_text_below',     'image',    'Picture Above, Text Below'),
  ('character_dialogue',           'video',    'Characters Speak');

-- ── formats are made from a template ──────────────────────────────────────────
alter table formats
  add column template_id  text not null default 'cinematic_3d_explainer' references templates(template_id),
  add column content_type text not null default 'video' check (content_type in ('video','carousel','image')),
  add column params       jsonb not null default '{}'::jsonb
    check (jsonb_typeof(params) = 'object' and octet_length(params::text) <= 8000);
alter table formats drop constraint formats_audio_source_check,
  add constraint formats_audio_source_check check (audio_source in ('ltx_native','kokoro','none'));

-- What the existing formats were made as (before versioning learns the new columns,
-- so this is not a new version of anyone's format).
update formats set template_id = case
    when audio_source = 'ltx_native' then 'character_dialogue'
    when idea_prompt like 'You are the news desk%' then 'mini_news_explainer'
    else 'cinematic_3d_explainer' end;

-- The content type follows the template; slides have no voice. (Fires before
-- formats_versioning: triggers run in name order.)
create or replace function private.format_template() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  select t.content_type into new.content_type from public.templates t where t.template_id = new.template_id;
  if new.content_type <> 'video' then
    new.audio_source := 'none';
  end if;
  return new;
end $fn$;
create trigger formats_template before insert or update of template_id, audio_source on formats
  for each row execute function private.format_template();

create or replace function private.format_versioning() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  if (new.idea_prompt, new.script_prompt, new.visual_style, new.audio_source, new.target_seconds,
      new.template_id, new.params)
     is distinct from
     (old.idea_prompt, old.script_prompt, old.visual_style, old.audio_source, old.target_seconds,
      old.template_id, old.params) then
    insert into public.format_versions (format_id, version, snapshot)
    values (old.id, old.version, jsonb_build_object(
              'idea_prompt', old.idea_prompt, 'script_prompt', old.script_prompt,
              'visual_style', old.visual_style, 'audio_source', old.audio_source,
              'target_seconds', old.target_seconds, 'template_id', old.template_id, 'params', old.params))
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
         target_seconds = (v->>'target_seconds')::int,
         template_id = coalesce(v->>'template_id', f.template_id),     -- versions from before templates
         params = coalesce(v->'params', f.params)
   where id = f.id
  returning * into f;
  return f;
end $fn$;

-- ── categories use several formats ────────────────────────────────────────────
alter table categories add column format_ids uuid[] not null default '{}';
update categories set format_ids = array[format_id] where format_id is not null;
alter table categories alter column ideas_per_batch set default 2;
update categories set ideas_per_batch = 2 where ideas_per_batch = 6;

-- Only the category's own channel's formats, each once.
create or replace function private.category_formats() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  new.format_ids := coalesce(array(select distinct f from unnest(new.format_ids) f where f is not null), '{}');
  if exists (select 1 from unnest(new.format_ids) f
              where not exists (select 1 from public.formats x where x.id = f and x.channel_id = new.channel_id)) then
    raise exception 'that format is not one of this channel''s' using errcode = '42501';
  end if;
  return new;
end $fn$;
create trigger categories_formats before insert or update of format_ids, channel_id on categories
  for each row execute function private.category_formats();

-- A deleted format leaves the categories that allowed it.
create or replace function private.format_left() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  update public.categories set format_ids = array_remove(format_ids, old.id) where old.id = any(format_ids);
  return old;
end $fn$;
create trigger formats_left after delete on formats for each row execute function private.format_left();

-- ── every channel gets a carousel and a picture card ──────────────────────────
-- An empty script prompt means "the template's shipped prompt" (and tracks its
-- improvements) until the owner edits it; the idea prompt and the look are the
-- channel's own, from its default format.
insert into formats (user_id, channel_id, name, description, audio_source, target_seconds, idea_prompt,
                     script_prompt, visual_style, template_id)
select d.user_id, d.channel_id, x.name, x.description, 'none', x.seconds, d.idea_prompt, '', d.visual_style, x.t
  from formats d
  cross join (values ('Carousel', 'Swipeable slides: a cover hook, one idea per slide, a summary.', 30,
                      'educational_carousel'),
                     ('Picture card', 'One picture on top, a bold headline and a few lines below.', 8,
                      'picture_above_text_below')) as x(name, description, seconds, t)
 where d.is_default
   and not exists (select 1 from formats y where y.channel_id = d.channel_id and y.template_id = x.t)
on conflict (channel_id, name) do nothing;
-- Categories that named their format keep it first and may also use the new two.
update categories k set format_ids = k.format_ids || array(
         select f.id from formats f
          where f.channel_id = k.channel_id
            and f.template_id in ('educational_carousel', 'picture_above_text_below')
            and not f.id = any(k.format_ids) order by f.created_at)
 where cardinality(k.format_ids) > 0;

-- ── ideas: the format the agent chose, and why ────────────────────────────────
alter table ideas add column format_why text not null default '';

-- ── posts, scripts, shots ─────────────────────────────────────────────────────
alter table posts drop constraint posts_format_check,
  add constraint posts_format_check check (format in ('reel','longform','carousel','image'));
alter table posts drop constraint posts_audio_source_check,
  add constraint posts_audio_source_check check (audio_source in ('ltx_native','kokoro','none'));
-- Carousel and image posts: the rendered slides Instagram gets, in order:
-- [{"key", "sha256", "bytes", "w", "h"}]. The slideshow for YouTube is final_key.
alter table posts add column slides jsonb;
alter table app_settings drop constraint app_settings_default_audio_source_check,
  add constraint app_settings_default_audio_source_check check (default_audio_source in ('ltx_native','kokoro','none'));

-- A post's kind follows its format: a reel, or a carousel / image (no voice).
create or replace function private.post_kind() returns trigger
language plpgsql security definer set search_path = '' as $fn$
declare
  ct text;
begin
  if new.format_id is not null then
    select content_type into ct from public.formats where id = new.format_id;
    if ct is not null then
      new.format := case ct when 'video' then 'reel' else ct end;
      if ct <> 'video' then
        new.audio_source := 'none';
      end if;
    end if;
  end if;
  return new;
end $fn$;
create trigger posts_kind before insert or update of format_id, audio_source on posts
  for each row execute function private.post_kind();

-- What a carousel or card says, slide by slide (the writer's output); shot_plan is [].
alter table scripts add column slides jsonb;

alter table shots add column extras jsonb not null default '{}'::jsonb;
alter table shots drop constraint shots_source_check,
  add constraint shots_source_check check (source in ('generate','clip','image','stock','chart','plain'));

-- ── uploads: the owner's own footage ──────────────────────────────────────────
alter table assets drop constraint assets_license_check,
  add constraint assets_license_check check (license in ('third_party','pexels','cc0','ai','owned'));
alter table assets drop constraint assets_state_check,
  add constraint assets_state_check check (state in ('uploading','pending','ready','failed'));
alter table assets add column file_name text, add column bytes bigint;

-- Room for one upload: an asset row (owned, approved, no credit) and its storage
-- reserved under the cap. The web signs a PUT for the returned key.
create or replace function api.start_upload(p_post_id uuid, p_kind text, p_bytes bigint, p_ext text,
                                            p_name text default null) returns public.assets
language plpgsql security definer set search_path = '' as $fn$
declare
  p   public.posts := private.owned_post(p_post_id);
  a   public.assets;
  k   int;
  ok  boolean;
  max_bytes bigint := case p_kind when 'video' then 300000000 else 25000000 end;
begin
  if p_kind not in ('video','image') then
    raise exception 'upload a video or a picture' using errcode = '22023';
  end if;
  if coalesce(p_ext, '') !~ (case p_kind when 'video' then '^(mp4|mov|m4v|webm)$' else '^(jpg|jpeg|png|webp)$' end) then
    raise exception 'that kind of file isn''t supported — use MP4, MOV or WebM video, or JPEG, PNG or WebP pictures'
      using errcode = '22023';
  end if;
  if p_bytes is null or p_bytes <= 0 or p_bytes > max_bytes then
    raise exception 'files are limited to % MB', max_bytes / 1000000 using errcode = '22023';
  end if;
  if p.status not in ('draft','awaiting_approval','approved','failed') then
    raise exception 'footage can be added before the post is made, not while it is %', p.status
      using errcode = '55000';
  end if;
  if (select count(*) from public.assets where post_id = p.id and origin = 'upload') >= 12 then
    raise exception 'a post holds at most 12 uploads' using errcode = '54000';
  end if;
  perform pg_advisory_xact_lock(hashtext('assets:' || p.id::text));
  select coalesce(max(n), 0) + 1 into k from public.assets where post_id = p.id;
  insert into public.assets (user_id, post_id, n, kind, origin, credit, license, rights, state, file_name, bytes)
  values (p.user_id, p.id, k, p_kind, 'upload', '', 'owned', 'approved', 'uploading',
          left(nullif(btrim(coalesce(p_name, '')), ''), 200), p_bytes)
  returning * into a;
  select r.ok into ok from private.reserve_storage(
    format('u/%s/p/%s/uploads/%s.%s', p.user_id, p.id, a.id, p_ext), p_bytes, 'asset', p.user_id, p.id) r;
  if not ok then
    raise exception 'storage is full — delete old posts or wait for finished ones to be cleaned up'
      using errcode = '53100';
  end if;
  update public.assets set fetch_from = jsonb_build_object('upload_key',
           format('u/%s/p/%s/uploads/%s.%s', p.user_id, p.id, a.id, p_ext))
   where id = a.id returning * into a;
  return a;
end $fn$;

-- The file is in R2: normalise it (H.264 video / JPEG picture), then analyse it.
create or replace function api.finish_upload(p_asset_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  a public.assets;
begin
  select * into a from public.assets where id = p_asset_id and user_id = private.caller() for update;
  if not found or a.state <> 'uploading' then
    raise exception 'that upload is not waiting to finish' using errcode = 'P0002';
  end if;
  update public.assets set state = 'pending' where id = a.id;
  return private.enqueue_job(a.user_id, 'ideas', 'fetch_asset', format('fetch_asset:%s', a.id),
                             jsonb_build_object('asset_id', a.id), a.post_id,
                             p_priority => 30, p_max_attempts => 2, p_lease_seconds => 1800);
end $fn$;

-- Remove one of the owner's uploads (its files are swept: no asset row points at them).
create or replace function api.delete_upload(p_asset_id uuid) returns void
language plpgsql security definer set search_path = '' as $fn$
declare
  a public.assets;
  p public.posts;
begin
  select * into a from public.assets where id = p_asset_id and user_id = private.caller() and origin = 'upload';
  if not found then
    raise exception 'upload not found' using errcode = 'P0002';
  end if;
  p := private.owned_post(a.post_id);
  if p.status in ('queued_for_render','rendering','rendered','post_processing') then
    raise exception 'the post is being made from it — wait until it is done' using errcode = '55000';
  end if;
  delete from public.assets where id = a.id;
end $fn$;

-- ── the swipe chooses the format ──────────────────────────────────────────────
-- p_format_id: the owner's pick on the swipe (one of the channel's formats);
-- otherwise the one the idea agent chose.
drop function api.decide_idea_v2(uuid, boolean, timestamptz, text, text[], boolean, text);
create function api.decide_idea_v2(p_idea_id uuid, p_accept boolean,
                                   p_publish_at timestamptz default null,
                                   p_reason text default null,
                                   p_platforms text[] default null,
                                   p_use_media boolean default false,
                                   p_media text default null,
                                   p_format_id uuid default null) returns public.ideas
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
  if p_format_id is not null then
    select * into f from public.formats where id = p_format_id and channel_id = c.id;
    if not found then
      raise exception 'that format is not one of this channel''s' using errcode = '22023';
    end if;
  else
    select * into f from public.formats where id = i.format_id;
  end if;
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
  update public.ideas set status = 'accepted', decided_at = now(), post_id = pid, format_id = f.id
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

-- ── rendering a carousel or a card: slides, then the slideshow ────────────────
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

  if p.format in ('carousel','image') then
    if exists (select 1 from jsonb_array_elements(coalesce(
                 (select slides from public.scripts where id = p.approved_script_id), '[]'::jsonb)) e
                left join public.assets a on a.post_id = p.id and a.n = nullif(e->'visual'->>'asset', '')::int
               where e->'visual'->>'source' = 'asset'
                 and (a.id is null or a.rights <> 'approved' or a.state <> 'ready')) then
      raise exception 'a slide uses a picture that is not approved, or not fetched yet' using errcode = '55000';
    end if;
    update public.posts set status = 'queued_for_render', error = null where id = p.id;
    perform private.log_post_event(p.id, p.status, 'queued_for_render', p_actor, 'slides requested');
    j := private.enqueue_job(p.user_id, 'cpu', 'render_slides', format('render_slides:%s', p.approved_script_id),
                             jsonb_build_object('script_id', p.approved_script_id), p.id,
                             p_priority => 45, p_max_attempts => 3, p_lease_seconds => 900);
    update public.jobs set state = 'queued', not_before = now(), attempts = 0, error = null, finished_at = null
     where id = j.id and state in ('failed','dead','cancelled');
    select * into j from public.jobs where id = j.id;
    return j;
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
