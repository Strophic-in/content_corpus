-- Caption styles (prompts/caption_styles/: the words on screen) and cover styles
-- (prompts/thumb_styles/: the thumbnail's layout). The owner switches them on in
-- Settings → Styles; Jev picks one of each per post from the video's story, title and
-- footage (plan_shots for the captions, packaging for the cover). Meme and ad styles
-- start switched off: they are for meme and ad formats.

alter table app_settings
  add column caption_styles_enabled text[] not null default
    '{bold_pop,news_box,tiktok_box,clean_minimal,karaoke_green,neon_glow,documentary_serif,big_word,subtitle_classic,highlight_dim}',
  add column thumb_styles_enabled text[] not null default
    '{classic,breaking_bar,top_headline,big_number,question_hook,circle_arrow,side_panel,before_now,minimal_center,boxed_words,documentary}';

alter table posts
  add column caption_preset text,
  add column caption_why text;
