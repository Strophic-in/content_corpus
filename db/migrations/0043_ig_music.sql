-- Trending Instagram music (spec 2026-11-15): which Instagram API an account is
-- connected through — the Audio API exists only on Unified Login — the reel's
-- music-free copy for Instagram, and the song picked for it.
alter table channel_accounts
  add column api text not null default 'instagram_login' check (api in ('instagram_login', 'unified'));
alter table posts
  add column final_ig_key text,
  add column ig_music jsonb;

-- The song pick is one OpenAI call, costed like the others (kind 'music_pick').
alter table costs drop constraint costs_kind_check,
  add constraint costs_kind_check check (kind in ('llm','vision','moderation','image','tts','gpu','pod_storage','music_pick'));
