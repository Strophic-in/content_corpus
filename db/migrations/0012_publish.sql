-- Publishing: post a finished reel to its channel's YouTube and Instagram.
--
-- One publish-lane job per (post, platform), keyed publish:<post>:<platform>, with
-- not_before = when to post (now, or the scheduled time). The worker writes each
-- step to publish_attempts before taking it (0002), so a crash mid-upload is
-- resumed or reconciled on the next run instead of posting the reel twice.
--
-- The post's status follows its publish jobs through a trigger, so every path
-- that moves a job — a click, a cancel, the worker finishing, the reaper — keeps
-- it right:
--   a job waiting or running       → scheduled
--   otherwise, one needs a human   → needs_review
--   otherwise, a platform has it   → published
--   otherwise                      → ready

create or replace function private.settle_publish(p_post_id uuid) returns void
language plpgsql security definer set search_path = '' as $fn$
declare
  p    public.posts;
  next text;
begin
  select * into p from public.posts where id = p_post_id for update;
  if not found or p.status not in ('ready','scheduled','published','needs_review') then
    return;
  end if;
  next := case
    when exists (select 1 from public.jobs where post_id = p.id and lane = 'publish'
                  and state in ('queued','claimed','blocked')) then 'scheduled'
    when exists (select 1 from public.jobs where post_id = p.id and lane = 'publish'
                  and state = 'needs_review') then 'needs_review'
    when exists (select 1 from public.publish_attempts where post_id = p.id and state = 'live')
      then 'published'
    else 'ready' end;
  if next <> p.status then
    update public.posts set status = next where id = p.id;
    perform private.log_post_event(p.id, p.status, next, 'system', case next
      when 'scheduled'    then 'publishing scheduled'
      when 'published'    then 'published'
      when 'needs_review' then 'could not confirm the post went out — check the platform'
      else 'publishing stopped' end);
  end if;
end $fn$;

create or replace function private.publish_job_changed() returns trigger
language plpgsql security definer set search_path = '' as $fn$
begin
  if new.post_id is not null then
    perform private.settle_publish(new.post_id);
  end if;
  return null;
end $fn$;

create trigger jobs_publish_settle
  after insert or update of state on public.jobs
  for each row when (new.lane = 'publish')
  execute function private.publish_job_changed();

-- Post now (p_at null or past) or at p_at, to each platform in p_platforms. YouTube
-- visibility is p_youtube_privacy, else the owner's setting (app_settings).
create or replace function api.request_publish(p_post_id uuid, p_platforms text[],
                                               p_at timestamptz default null,
                                               p_youtube_privacy text default null)
returns setof public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  p    public.posts := private.owned_post(p_post_id);
  at_  timestamptz := greatest(coalesce(p_at, now()), now());
  pf   text;
  name text;
  key  text;
  j    public.jobs;
begin
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
    -- Already scheduled: move it to the new time. Waiting for a human after an
    -- unknown outcome, or done without a live post: run again — the worker checks
    -- what reached the platform before it uploads anything.
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
  perform private.log_post_event(p.id, p.status, p.status, 'user:' || private.caller(),
    format('%s to %s', case when at_ <= now() + interval '1 minute' then 'posting now'
                            else 'scheduled' end,
           array_to_string(array(select case x when 'youtube' then 'YouTube' else 'Instagram' end
                                   from unnest(p_platforms) x), ' and ')),
    jsonb_build_object('platforms', p_platforms, 'at', at_));
end $fn$;

-- Stop a post that has not started yet. One already uploading cannot be recalled.
create or replace function api.cancel_publish(p_post_id uuid, p_platform text) returns void
language plpgsql security definer set search_path = '' as $fn$
declare
  p public.posts := private.owned_post(p_post_id);
  n int;
begin
  update public.jobs set state = 'cancelled', cancel_requested_at = now(), finished_at = now()
   where dedupe_key = format('publish:%s:%s', p.id, p_platform) and state = 'queued';
  get diagnostics n = row_count;
  if n = 0 then
    raise exception 'nothing is waiting to be posted there — it may be uploading already'
      using errcode = '55000';
  end if;
  perform private.log_post_event(p.id, p.status, p.status, 'user:' || private.caller(),
    format('cancelled posting to %s', case p_platform when 'youtube' then 'YouTube' else 'Instagram' end));
end $fn$;
