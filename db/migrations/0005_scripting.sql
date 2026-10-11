-- Milestone 2: what the script writer needs to know about the channel, and which
-- model writes. All of it is intent the owner edits (granted in db/access.sql).

alter table app_settings
  add column channel_name       text,
  add column channel_niche      text,
  add column channel_audience   text,
  add column channel_voice      text,
  add column script_language    text not null default 'English',
  -- Target reel length for new posts. Shots are 5-20 s each (LTX-2.5's range per
  -- generation), so this decides roughly how many shots a script plans.
  add column default_reel_seconds int not null default 24
                                  check (default_reel_seconds between 5 and 90),
  -- Chosen from openai_models, which is the list the key itself reported when it
  -- was saved (and validated) in Settings — never a guessed model name.
  add column script_model       text,
  add column openai_models      text[] not null default '{}';
