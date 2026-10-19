-- Narrator voices and voice styles (prompts/voices/catalog.json, prompts/voice_styles/):
-- the owner switches voices and styles on in Settings → Voices; for each narrated
-- post Jev picks the best enabled voice for the channel's language and the best
-- style (somber for a tragedy, breaking news for big events…) — or, in "fixed"
-- mode, the one voice the owner chose. The pick is kept on the post.
--
-- voice ids are engine:voice ("openai:marin", "kokoro:am_michael").

alter table app_settings
  add column voice_mode text not null default 'auto' check (voice_mode in ('auto', 'fixed')),
  add column voices_enabled text[] not null default
    '{openai:marin,openai:cedar,openai:ash,openai:sage,openai:onyx,kokoro:am_michael,kokoro:bm_george,kokoro:af_heart,kokoro:hf_alpha,kokoro:hm_omega}',
  add column voice_styles_enabled text[] not null default
    '{breaking_news,calm_explainer,documentary,somber,energetic,storyteller,conversational,hindi_anchor}',
  add column fixed_voice text,
  add column fixed_voice_style text;

-- The owner's current single voice stays what "fixed" mode uses, and stays switched on.
update app_settings set fixed_voice = 'kokoro:' || narrator_voice,
                        voices_enabled = array(select distinct unnest(voices_enabled || ('kokoro:' || narrator_voice)));

alter table posts
  add column voice_id text,
  add column voice_style text,
  add column voice_why text;
