-- "Make it": the owner's go-ahead to take a post all the way to a finished video
-- (the Library table's row and bulk actions).
--
-- posts.go_ahead: set by api.go_ahead. While it is set, the worker takes the next
-- step itself, as in Automatic mode, for this one post: a written script is approved
-- (write_script), and once its shots are planned and voiced the render starts
-- (auto.request_render, actor 'system:go_ahead'). The render is the owner's own
-- request, so the automatic daily spending cap does not stop it; the account's
-- monthly limit still does. Cleared when the render starts, and by any refusal.

alter table posts add column go_ahead boolean not null default false;

-- Takes the post's next step now and leaves the flag for the steps that must wait:
--   draft / failed before a script  → write the script
--   awaiting approval                → approve the script
--   approved / failed after approval → render (or, if the shots are not ready yet,
--                                      render as soon as they are)
-- Returns what it did, in a few words.
create or replace function api.go_ahead(p_post_id uuid) returns text
language plpgsql security definer set search_path = '' as $fn$
declare
  p     public.posts := private.owned_post(p_post_id);
  actor text := 'user:' || private.caller();
  s     uuid;
begin
  perform private.check_quota(private.caller());
  select * into p from public.posts where id = p.id for update;
  if p.status in ('draft') or (p.status = 'failed' and p.approved_script_id is null) then
    update public.posts set go_ahead = true where id = p.id;
    perform private.generate_script(p.id, actor);
    return 'writing the script';
  end if;
  if p.status = 'awaiting_approval' then
    select id into s from public.scripts
     where post_id = p.id and state = 'awaiting_approval' order by version desc limit 1;
    if s is null then
      raise exception 'no script is waiting for approval' using errcode = '55000';
    end if;
    update public.posts set go_ahead = true where id = p.id;
    perform private.approve_script(s, actor);
    return 'approved';
  end if;
  if p.status in ('approved','failed') then
    update public.posts set go_ahead = true where id = p.id;
    begin
      perform private.request_render(p.id, actor);
      update public.posts set go_ahead = false where id = p.id;
      return 'rendering';
    exception when sqlstate '55000' then
      -- Shots still being planned or voiced: the worker starts the render when they are.
      if sqlerrm like 'shots are still being planned%' then
        return 'will render when its shots are ready';
      end if;
      raise;
    end;
  end if;
  if p.status = 'scripting' then
    update public.posts set go_ahead = true where id = p.id;
    return 'will be approved and rendered once written';
  end if;
  raise exception 'nothing to do: it is %', replace(p.status, '_', ' ') using errcode = '55000';
end $fn$;

-- Any way out of the pipeline (or a failure) drops the go-ahead, so a later rewrite by hand never
-- renders on its own.
create or replace function private.drop_go_ahead() returns trigger
language plpgsql set search_path = '' as $fn$
begin
  if new.go_ahead and new.status in ('cancelled','failed','needs_review','queued_for_render','rendering',
                                     'rendered','post_processing','ready','scheduled','published') then
    new.go_ahead := false;
  end if;
  return new;
end $fn$;
create trigger posts_drop_go_ahead before update of status on posts
  for each row execute function private.drop_go_ahead();

