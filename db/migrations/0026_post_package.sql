-- What a finished reel goes out with (worker/corpus/packaging.py): its title, caption,
-- hashtags, first comment, sources and cover. Made by the package_post job when the
-- reel is ready (or by publish_post, if missing); the post page shows it.
--
-- posts.package: {title, hook_line, caption, hashtags[], first_comment, thumbnail_text,
--                 kicker, sources[{site, title, url}], thumbnail_key, script_id, model, made_at}

alter table posts add column package jsonb;

-- "Write it again" on the post page: a fresh package for a finished reel.
create or replace function api.request_package(p_post_id uuid) returns public.jobs
language plpgsql security definer set search_path = '' as $fn$
declare
  p public.posts := private.owned_post(p_post_id);
begin
  if p.status not in ('ready','needs_review','scheduled') or p.final_key is null then
    raise exception 'the caption and cover are written once the reel is finished' using errcode = '55000';
  end if;
  perform private.check_quota(private.caller());
  return private.enqueue_job(p.user_id, 'cpu', 'package_post',
                             format('package_post:%s:%s', p.id, extract(epoch from now())::bigint),
                             jsonb_build_object('force', true), p.id,
                             p_max_attempts => 2, p_lease_seconds => 300);
end $fn$;
