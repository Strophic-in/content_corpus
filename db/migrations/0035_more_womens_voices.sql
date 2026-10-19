-- More women's voices switched on (owner, 2026-10-19: nearly every reel was read by
-- the same man). English prefers the free voices, and only one of those switched on
-- by default was a woman's (af_heart); Bella (bright, American) and Emma (warm,
-- British) join her. Jev now also varies the narrator across a channel's posts.

alter table app_settings alter column voices_enabled set default
  '{openai:marin,openai:cedar,openai:ash,openai:sage,openai:onyx,kokoro:am_michael,kokoro:bm_george,kokoro:af_heart,kokoro:af_bella,kokoro:bf_emma,kokoro:hf_alpha,kokoro:hm_omega}';

update app_settings
   set voices_enabled = array(select distinct unnest(voices_enabled || '{kokoro:af_bella,kokoro:bf_emma}'::text[]));
