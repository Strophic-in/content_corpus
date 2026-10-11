-- Assemble while rendering.
--
-- Each narration line's word timings are measured once, when the line is voiced
-- (cpu/narrate, before anyone presses Render), instead of on the whole reel after
-- the GPU finishes. Each shot is then captioned and encoded by cpu/build_segment
-- as soon as it comes off the GPU, so the final assembly is a join, not an encode.

alter table shots
  -- [[start_s, end_s, word], ...] relative to the start of the narration WAV;
  -- the words are the script's (Whisper only supplies the timing).
  add column narration_words jsonb;
