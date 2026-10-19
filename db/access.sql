-- Access control — who may touch what. NOT a migration: db/migrate.py re-applies
-- this whole file after every run, and every statement in it is idempotent.
--
-- Why repeatable: VibeDB backs a project up by dumping it and restoring into
-- Neon with --no-owner --no-acl, and restores a backup into a new project the
-- same way. Data, schema and RLS policies survive; grants do not, by design. A
-- restored database gets its permissions back from one `migrate.py` run, and
-- until then the web role can reach nothing — it fails closed, never open.
--
-- The rule: the signed-in owner may read their rows and write the *intent*
-- columns, but lifecycle columns are reachable only through `api` functions.
-- This is not paranoia about a single-user app — `posts.status` is the approval
-- gate, and a role that can set status='queued_for_render' has bypassed script
-- approval and can ship unreviewed content to a real channel.
--
-- Roles: workers and migrations connect as the database owner. The web app
-- connects as `corpus_web`. On VibeDB that role is created by the control plane
-- (`vibedb role create <project> corpus_web --exact`), because the project owner
-- may not create roles; locally, a CREATEROLE owner creates it here.

do $access$
begin
  if not exists (select 1 from pg_roles where rolname = 'corpus_web') then
    if (select rolcreaterole from pg_roles where rolname = current_user) then
      create role corpus_web nologin;   -- local dev: migrate.py sets LOGIN + password
    else
      raise exception 'role corpus_web does not exist'
        using hint = 'On VibeDB run: sudo vibedb role create <project> corpus_web --exact';
    end if;
  end if;
end $access$;

-- ─────────────────────────────────────────────────────────────────────────────
-- Functions are executable by PUBLIC by default, and these are SECURITY DEFINER
-- with the owner's rights. Without this revoke, any role could call
-- private.finish_job or private.enqueue_job directly and skip every gate.
-- ─────────────────────────────────────────────────────────────────────────────

revoke all on schema private from public;
revoke execute on all functions in schema private from public;
revoke execute on all functions in schema api from public;
alter default privileges in schema private revoke execute on functions from public;
alter default privileges in schema api revoke execute on functions from public;

-- ─────────────────────────────────────────────────────────────────────────────
-- VibeDB gives every project an `<db>_app` role with default privileges on
-- everything the owner creates: DML on all tables, USAGE on all schemas and
-- EXECUTE on all functions — including the SECURITY DEFINER ones above and
-- Better Auth's session/password tables. content_corpus does not use it, so it
-- gets nothing. (A no-op where that role does not exist.)
-- ─────────────────────────────────────────────────────────────────────────────

do $access$
declare app text := current_database() || '_app';
begin
  if exists (select 1 from pg_roles where rolname = app) then
    execute format('revoke all on all tables in schema public, private, api from %I', app);
    execute format('revoke all on all sequences in schema public, private, api from %I', app);
    execute format('revoke all on all functions in schema public, private, api from %I', app);
    execute format('revoke all on schema private, api from %I', app);
    execute format('alter default privileges revoke all on tables from %I', app);
    execute format('alter default privileges revoke all on sequences from %I', app);
    execute format('alter default privileges revoke all on functions from %I', app);
    execute format('alter default privileges revoke all on schemas from %I', app);
    execute format('alter default privileges revoke all on types from %I', app);
  end if;
end $access$;

-- ─────────────────────────────────────────────────────────────────────────────
-- corpus_web
-- ─────────────────────────────────────────────────────────────────────────────

grant usage on schema public, api to corpus_web;
grant execute on all functions in schema api to corpus_web;

-- Better Auth's tables. The library needs global lookups (by email, by session
-- token) before any user is known, so these are not under RLS.
grant select, insert, update, delete on "user", "session", "account", "verification"
  to corpus_web;

-- Read access; rows are scoped by the RLS policies in 0004_rls.sql.
grant select on app_settings, caption_styles, render_batches, posts, scripts, shots,
                jobs, publish_attempts, post_events, workers, lane_config,
                storage_objects, storage_config, channels, formats, format_versions, ideas,
                categories, category_sources, costs, prices, fx_rates, templates
  to corpus_web;

-- Settings rows are created by api.ensure_settings(); the form edits intent only.
grant update (timezone, auto_approve, default_publish_time, youtube_category_id,
              youtube_privacy, caption_style_id, gpu_autopause, channel_name,
              channel_niche, channel_audience, channel_voice, script_language,
              default_reel_seconds, script_model, openai_models, default_audio_source,
              narrator_voice, narrator_speed, pipeline_mode, auto_spend_cap_paise_day,
              vision_model, usd_inr_override, image_model, image_quality,
              voice_mode, voices_enabled, voice_styles_enabled, fixed_voice, fixed_voice_style)
  on app_settings to corpus_web;

-- Key vault: write-only from the web's point of view. The ciphertext column is
-- not selectable, so even a SQL injection in the web app cannot read secrets
-- back out; the UI shows only which keys exist and when they changed.
grant select (user_id, name, updated_at) on user_keys to corpus_web;
grant insert (user_id, name, ciphertext, updated_at) on user_keys to corpus_web;
grant update (ciphertext, updated_at) on user_keys to corpus_web;
grant delete on user_keys to corpus_web;

-- One's own membership (role, status, limit); everything else about accounts goes
-- through the owner's api.admin_* functions.
grant select on memberships to corpus_web;

-- How published reels did, and the workers' health checks: read-only.
grant select on post_stats, health_checks to corpus_web;

-- A post's footage: the owner may withdraw (or restore) permission to show it.
-- Everything else about an asset is the workers'.
grant select on assets to corpus_web;
grant update (rights) on assets to corpus_web;

grant insert, delete on caption_styles to corpus_web;
grant update (name, font_family, font_size_px, primary_color, accent_color,
              outline_px, shadow_px, position_y, words_per_group, active_scale,
              uppercase)
  on caption_styles to corpus_web;

-- The whole point of this file. `status`, `auto_approve`, `approved_script_id`,
-- `render_batch_id`, `final_*` and `error` are absent, so only api functions and
-- workers can advance a post's lifecycle.
grant insert (user_id, format, topic, brief, slot_date, publish_tz, publish_at,
              audio_source, target_seconds, platforms, captions_enabled,
              caption_style_id, channel_id, format_id)
  on posts to corpus_web;
grant update (format, topic, brief, slot_date, publish_tz, publish_at,
              audio_source, target_seconds, platforms, captions_enabled,
              caption_style_id, channel_id, format_id)
  on posts to corpus_web;
grant delete on posts to corpus_web;

-- Prompt library: the owner edits what a format makes. `version` and `is_default`
-- are absent: versions are kept by a trigger, the default is switched by
-- api.set_default_format, and history is restored by api.restore_format_version.
-- `content_type` follows `template_id` (a trigger), so it is not the web's to set.
grant insert (user_id, channel_id, name, description, audio_source, target_seconds, idea_prompt,
              script_prompt, visual_style, sources, ideas_per_batch, template_id, params)
  on formats to corpus_web;
grant update (name, description, audio_source, target_seconds, idea_prompt,
              script_prompt, visual_style, sources, ideas_per_batch, template_id, params)
  on formats to corpus_web;
grant delete on formats to corpus_web;
-- ideas are read-only: a swipe goes through api.decide_idea, a batch through api.request_ideas.

-- Channels: the profile is the owner's to edit; the default is switched by
-- api.set_default_channel.
grant insert (user_id, name, niche, audience, voice, language, timezone, default_publish_time,
              ideas_daily, ideas_daily_at, video_look)
  on channels to corpus_web;
grant update (name, niche, audience, voice, language, timezone, default_publish_time,
              ideas_daily, ideas_daily_at, updated_at, video_look)
  on channels to corpus_web;
grant delete on channels to corpus_web;

-- Connected accounts: the OAuth callback (web) stores the token encrypted; like
-- the key vault, token_ciphertext is write-only, so the web can never read a token
-- back. Publishing workers decrypt it as the owner role.
grant select (id, user_id, channel_id, platform, external_id, handle, display_name, avatar_url,
              token_expires_at, scopes, status, connected_at, updated_at)
  on channel_accounts to corpus_web;
grant insert (user_id, channel_id, platform, external_id, handle, display_name, avatar_url,
              token_ciphertext, token_expires_at, scopes, status, updated_at)
  on channel_accounts to corpus_web;
grant update (external_id, handle, display_name, avatar_url, token_ciphertext, token_expires_at,
              scopes, status, updated_at)
  on channel_accounts to corpus_web;
grant delete on channel_accounts to corpus_web;

-- Categories and their sources: the owner edits what a category covers and where
-- it looks. A source's status, fetch times and errors are the ideas worker's.
grant insert (user_id, channel_id, name, color, brief, keywords, format_id, format_ids, ideas_per_batch,
              enabled)
  on categories to corpus_web;
grant update (name, color, brief, keywords, format_id, format_ids, ideas_per_batch, enabled)
  on categories to corpus_web;
grant delete on categories to corpus_web;
grant insert (user_id, category_id, kind, value, options, enabled) on category_sources to corpus_web;
grant update (kind, value, options, enabled) on category_sources to corpus_web;
grant delete on category_sources to corpus_web;

-- Model prices are the owner's to set; the cost ledger and exchange rates are
-- written by workers only (a role that could edit `costs` could hide spending).
grant insert (user_id, model, input_per_m, cached_input_per_m, output_per_m, per_image, updated_at)
  on prices to corpus_web;
grant update (input_per_m, cached_input_per_m, output_per_m, per_image, updated_at) on prices to corpus_web;
grant delete on prices to corpus_web;

-- Scripts: text fields of a draft only. `state` is excluded, so approval cannot
-- be self-served — it goes through api.approve_script.
grant update (title, hook, description, hashtags, intended_dialogue, shot_plan,
              style_prompt)
  on scripts to corpus_web;

-- shots, jobs, publish_attempts, post_events, workers, lane_config and the
-- storage tables are read-only to the web. A role that can UPDATE jobs can set
-- its own job to 'queued' past max_attempts, or re-queue a publish that already
-- went out.
