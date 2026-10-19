-- Autopilot for one post (the Discover sheet's switch, the post page's switch): it is
-- written, approved, voiced, rendered, captioned and posted at its planned time with
-- no stop for the owner. Built from what exists: posts.go_ahead (0024) takes it to a
-- finished reel; posts.pipeline_mode = 'auto' makes the worker post it when it is
-- ready (auto.request_publish, at publish_at, to posts.platforms).
--
-- Off: back to the owner's hands (manual), wherever it is.

create or replace function api.autopilot(p_post_id uuid, p_on boolean) returns text
language plpgsql security definer set search_path = '' as $fn$
declare
  p    public.posts := private.owned_post(p_post_id);
  what text;
begin
  if not p_on then
    update public.posts set go_ahead = false, pipeline_mode = 'manual' where id = p.id;
    return 'off';
  end if;
  update public.posts set pipeline_mode = 'auto' where id = p.id;
  if p.status in ('ready', 'needs_review') then
    -- Finished already: post it at its time (or now, if that has passed).
    perform private.request_publish(p.id, coalesce(p.platforms, array['youtube']), greatest(p.publish_at, now()),
                                    null, 'user:' || private.caller());
    return 'will be posted at its time';
  end if;
  if p.status in ('scheduled', 'published') then
    return 'already on its way';
  end if;
  begin
    what := api.go_ahead(p.id);
  exception when sqlstate '55000' then
    what := 'on autopilot';
  end;
  return what;
end $fn$;
