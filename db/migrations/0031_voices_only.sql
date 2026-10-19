-- Voices only: the ready-made voice styles are gone. Jev picks a voice; an AI
-- (OpenAI) voice is told how to sound by a short direction written from the
-- script itself, kept in posts.voice_style so a retry reads the same way. Free
-- (Kokoro) voices are preferred for English, AI voices for Hindi.

alter table app_settings
  drop column voice_styles_enabled,
  drop column fixed_voice_style;

-- Old style ids ("somber", "breaking_news") are not directions: written afresh.
update posts set voice_style = null where voice_style is not null and position(' ' in voice_style) = 0;

comment on column posts.voice_style is
  'How an AI voice was told to read this post, written from its script; null for a free voice.';
