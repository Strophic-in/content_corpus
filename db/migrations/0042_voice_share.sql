-- Most reels go without a narrator (owner, 2026-10-20: "the narrator voice makes this
-- more AI ... give more priority to no voice, only captions, and sometimes voice"):
-- the share of a channel's reels that may have a voice, in percent. When a format is
-- picked for an idea, a narrated one past this share becomes the channel's
-- captions-only reel (worker/corpus/ideas/voice.py). The owner can still choose any
-- format when they accept a card.

alter table channels
  add column voice_share int not null default 25 check (voice_share between 0 and 100);
