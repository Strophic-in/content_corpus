-- Narrated mode: one voice-over narrator for the whole reel (text-to-speech),
-- over visuals that carry sound effects only. posts.audio_source already models
-- the choice ('ltx_native' = the video model voices on-screen characters;
-- 'kokoro' = TTS narration); this lets each channel pick its default.

alter table app_settings
  add column default_audio_source text not null default 'ltx_native'
    check (default_audio_source in ('ltx_native','kokoro'));
