-- Row-level security on every user-owned table.
--
-- RLS scopes *rows* to `app.user_id`, which the web app sets per transaction
-- (apps/web/lib/db.ts). Which *columns* the web role may touch is granted in
-- db/access.sql — RLS alone would let the owner update any column of their own
-- row, including posts.status, which is the approval gate.
--
-- The policies name no role (they apply to PUBLIC, i.e. every role that is not
-- the table owner). That is deliberate: VibeDB backs a project up by dumping it
-- and restoring into Neon with --no-owner --no-acl, where `corpus_web` does not
-- exist, so a policy that named it would fail every backup. Applying to PUBLIC
-- loses nothing: the workers connect as the owner, which is exempt (no FORCE),
-- and any other role still has to hold a grant from db/access.sql to reach a
-- table at all.

alter table app_settings     enable row level security;
alter table user_keys        enable row level security;
alter table caption_styles   enable row level security;
alter table render_batches   enable row level security;
alter table posts            enable row level security;
alter table scripts          enable row level security;
alter table shots            enable row level security;
alter table jobs             enable row level security;
alter table publish_attempts enable row level security;
alter table post_events      enable row level security;
alter table workers          enable row level security;
alter table lane_config      enable row level security;
alter table storage_objects  enable row level security;
alter table storage_config   enable row level security;

-- Owned directly.
create policy own on app_settings
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true));
create policy own on user_keys
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true));
create policy own on caption_styles
  using (user_id = current_setting('app.user_id', true))
  with check (user_id = current_setting('app.user_id', true));
create policy own on render_batches for select
  using (user_id = current_setting('app.user_id', true));
create policy own on jobs for select
  using (user_id = current_setting('app.user_id', true));
create policy own on storage_objects for select
  using (user_id = current_setting('app.user_id', true));

-- Posts: read and create your own; edit only while nothing is in flight; delete
-- only before the GPU or the publisher has touched it. Deleting a post mid-flight
-- would orphan claimed jobs and, worse, could delete the row a publish attempt
-- is about to reference. Cancel first.
create policy own_read on posts for select
  using (user_id = current_setting('app.user_id', true));
create policy own_insert on posts for insert
  with check (user_id = current_setting('app.user_id', true));
create policy own_update on posts for update
  using (user_id = current_setting('app.user_id', true)
         and status not in ('rendering','post_processing','scheduled','published'))
  with check (user_id = current_setting('app.user_id', true));
create policy own_delete on posts for delete
  using (user_id = current_setting('app.user_id', true)
         and status in ('draft','scripting','awaiting_approval','approved','failed',
                        'cancelled'));

-- Children are scoped through their post rather than carrying a user_id, so
-- there is exactly one place the ownership of a post is defined.
create policy own_read on scripts for select
  using (exists (select 1 from posts p where p.id = scripts.post_id
                  and p.user_id = current_setting('app.user_id', true)));
-- Edit the text of a draft and nothing else; never once it is approved.
create policy own_edit on scripts for update
  using (state in ('draft','awaiting_approval')
         and exists (select 1 from posts p where p.id = scripts.post_id
                      and p.user_id = current_setting('app.user_id', true)));
create policy own_read on shots for select
  using (exists (select 1 from posts p where p.id = shots.post_id
                  and p.user_id = current_setting('app.user_id', true)));
create policy own_read on publish_attempts for select
  using (exists (select 1 from posts p where p.id = publish_attempts.post_id
                  and p.user_id = current_setting('app.user_id', true)));
create policy own_read on post_events for select
  using (exists (select 1 from posts p where p.id = post_events.post_id
                  and p.user_id = current_setting('app.user_id', true)));

-- Worker liveness drives the "GPU online / offline" badge and the storage
-- meter needs the cap. Nothing user-specific or secret in either.
create policy read_all on workers        for select using (true);
create policy read_all on lane_config    for select using (true);
create policy read_all on storage_config for select using (true);
