-- More places a category can follow, now that Reddit is closing its public feeds
-- (RSS ends 2026-11-13; Reddit sources stay, and say so when they stop answering).
-- All are read by the ideas worker only, through public, keyless APIs — except
-- YouTube's chart, which takes a YouTube Data API key the owner adds in Settings
-- (user_keys 'youtube_api_key'; a Google Cloud API key, not their login).
--
--   bluesky     'whats-hot' · 'trending' · https://bsky.app/profile/<who>/feed/<id>
--   mastodon    an instance ('mastodon.social') · a hashtag on one ('#science@mastodon.social')
--   lemmy       an instance ('lemmy.world') · a community on one ('technology@lemmy.world')
--   hackernews  'front_page' · search terms
--   youtube     a country's most-popular chart ('IN'), or one category of it ('IN:28')

alter table category_sources drop constraint category_sources_kind_check,
  add constraint category_sources_kind_check check (kind in (
    'reddit','site','rss','search','google_trends','wikipedia',
    'bluesky','mastodon','lemmy','hackernews','youtube'));

alter table category_sources add constraint category_sources_open_value check (
      (kind <> 'bluesky' or value ~ '^(whats-hot|trending|https://bsky\.app/profile/[A-Za-z0-9.:_-]+/feed/[A-Za-z0-9_-]+)$')
  and (kind <> 'mastodon' or value ~ '^(#[A-Za-z0-9_]{1,100}@)?[a-z0-9-]+(\.[a-z0-9-]+)+$')
  and (kind <> 'lemmy' or value ~ '^([A-Za-z0-9_]{1,50}@)?[a-z0-9-]+(\.[a-z0-9-]+)+$')
  and (kind <> 'hackernews' or length(value) <= 200)
  and (kind <> 'youtube' or value ~ '^[A-Z]{2}(:[0-9]{1,3})?$'));
