# Instagram trending music on Reels — design

Date: 2026-11-15 · Status: draft for the owner's approval

## Intent

Reels that go to Instagram should carry a **trending song from Instagram's own
catalogue that suits the reel's theme**, attached through Meta's Audio API
(`/ig_audio` + `audio_configuration` on the REELS container). Trending audio is
what Instagram's audience — and its ranking — rewards; a CC0 bed from Freesound
does neither. Once this works on a real post, Instagram stops getting Freesound
altogether. YouTube Shorts keep the Freesound bed (YouTube's API can't attach
music, and silent Shorts do worse).

## Owner's decisions (2026-11-15)

- Move the Instagram connection to **Instagram API with Unified Login** — the
  Audio API is not available on Instagram Login, which the app uses today.
- On Instagram, the trending song **replaces** Freesound. YouTube keeps Freesound.
- The song is chosen by **OpenAI's Decisions API** (`POST /v1/decisions`,
  model `gpt-6-luna`, typed `choice` answers) — not the Responses API, not Jev.
- **Always attach a song.** No "none fits": take the closest match, or simply a
  good-sounding one — Gen-Z, meme and viral sounds are welcome.
- **Hindi songs by default**; another language is fine when the sound is cool
  and suits the reel.

## Goals

1. Connect Instagram through Unified Login; publish, comment and read stats on
   `graph.facebook.com` with the new token.
2. Every reel gets a second, music-free final file for Instagram.
3. At publish time, choose the Instagram `music` track that best suits the reel
   (always one) and attach it.
4. Show the chosen song (title, artist, reason) on the post page.

## Non-goals

- Music on carousels or single pictures (the API attaches audio to Reels only).
- Previewing the reel with the song (the API cannot).
- `original_sound` audio (other creators' sounds) — music only.
- Ads audio swap (`product=ADS`).
- A manual song picker in the UI (v1 shows the choice; owner can't override yet).

## Anti-goals (a failure even if it technically works)

- A comic or party track under a tragedy or death story (the closest calm or
  emotional track goes there instead).
- A silent Instagram reel.
- Two music tracks stacked in one Instagram reel.
- A post failing to go out because the song couldn't be attached.
- YouTube Shorts losing their music.
- Breaking the current Instagram connection before the new one is proven.

## Constraints (from Meta's docs, read 2026-11-15)

- Audio API: Facebook Login or Unified Login only; not Instagram Login.
- `GET /ig_audio?audio_type=music&user_id={ig-id}[&search_query=…]` — with no
  query it returns trending music. Fields: `audio_id`, `title`, `display_artist`,
  `duration_in_ms`, `download_url` (expires ~1.5 days), `is_ads_eligible`, …
- `audio_configuration={"audio_id", "audio_volume" 1–100, "video_volume" 1–100}`
  on `POST /{ig-id}/media` with `media_type=REELS`. No ducking; 1 is the minimum.
- Only music licensed for third parties is returned; may differ from the app.
- Unified Login: login URL with a `config_id`; code exchanged at
  `graph.facebook.com/v27.0/oauth/access_token` with the **Meta** app id/secret;
  a Business Integration System User token (expiry set by the configuration);
  account ids from `GET /me/assigned_instagram_accounts`; host `graph.facebook.com`;
  permissions `instagram_basic`, `instagram_content_publish` (+ `instagram_manage_comments`
  for the first comment, `instagram_manage_insights` for stats).
- That account id equals the `user_id` we already store as
  `channel_accounts.external_id` (oauth.ts reads `me.user_id`) — no data migration.
- Standard Access is enough for people with a role on the app (the owner).
  Other sign-ups need Advanced Access (App Review) and Live mode.
- Shared free-tier limits: R2 is capped at 9 GB; a second final per reel is a
  few MB, acceptable.

## Approaches considered

- **A. OpenAI picks from a shortlist — chosen.** Trending list + a few searches
  from the reel's mood/topic/language → ~30–40 candidates → one OpenAI
  Decisions request picks one. Respects both "trending" and "fits the theme".
- B. Rules (most trending track matching mood keywords) — cheap, but blind to
  meaning; would put a love song on a flood report.
- C. OpenAI writes one search query, take the top hit — ignores trending.

## Design

### 1. Unified Login connection (web)

- `oauth.ts`: Instagram's authorize URL becomes the Unified Login URL
  (`https://www.facebook.com/v27.0/dialog/oauth` with `client_id=META_APP_ID`,
  `config_id=META_IG_CONFIG_ID`, `response_type=code`, `redirect_uri`, `state`).
  `exchange` swaps the code with `META_APP_ID`/`META_APP_SECRET`, then reads
  `/me/assigned_instagram_accounts` (and the profile fields of the account) to
  fill `externalId`, `handle`, `displayName`, `avatarUrl`. Expiry: whatever the
  token reply says (`expires_in` absent or 0 → `null`, never expires).
- If several accounts are shared, take the one whose id matches the channel's
  current `external_id`; else the first. (Owner-only v1 — one account.)
- The first reconnect must confirm the Unified account id equals the stored
  `external_id`; on a mismatch, stop and report rather than store it.
- `channel_accounts` gains `api text not null default 'instagram_login'`
  (`'unified'` for new connections) — migration **0043**. Old connections keep
  working until reconnected (Meta: both coexist).
- New env vars: `META_APP_ID`, `META_APP_SECRET`, `META_IG_CONFIG_ID`.
  `configured('instagram')` is true when either the old or new set is present;
  new connections use Unified Login whenever its vars are set.
- Channel page: an Instagram account still on the old login shows
  "Reconnect to get trending music".

### 2. Publishing (worker)

- `publish/instagram.py`: the host is per account —
  `graph.facebook.com/v27.0` for `api='unified'`, `graph.instagram.com/v23.0`
  otherwise — passed in (no module-level `GRAPH` use in publish/comment/stats).
- Token renewal (`_instagram_token`, `upkeep`) applies only to
  `api='instagram_login'`; a Unified token is never sent to `ig_refresh_token`.
  A Unified token that stops working → `AuthExpired` → account `expired`, owner
  reconnects (existing behaviour).
- `stats.py` reads `like_count` etc. through the account's host.
- `_create` accepts an optional `audio_configuration` and sends it as JSON.

### 3. A music-free reel for Instagram (assemble)

- `handlers/assemble.py` joins the segments twice when the post's channel has
  Instagram connected via Unified Login: once with the Freesound bed (today's
  `final_key`, for YouTube) and once with `music=None` → stored at
  `…/final/{script_id}.ig.mp4`, recorded in new column `posts.final_ig_key`
  (migration 0043). The second join reuses the built segments (no GPU, ~seconds).
- Without a Unified Instagram connection nothing changes (one file).
- Publishing to Instagram uses `final_ig_key` when a track was attached, else
  `final_key` (the bed version — the fallback keeps today's sound).

### 4. Choosing the song (worker, new `corpus/ig_music.py`)

Runs inside `publish_post` for Instagram reels, just before the container:

1. **Candidates.** `GET /ig_audio?audio_type=music` with no query (trending),
   plus searches: Hindi first ("hindi trending", "bollywood", and a Hindi/
   Bollywood search for the mood, e.g. `somber` → "sad hindi song",
   `energetic-hype` → "bollywood party"), one Gen-Z/meme search ("viral meme
   song", "phonk"), and one from the mood in English. De-duplicate by
   `audio_id`; drop tracks used on this channel's last 20 Instagram posts; keep
   each track's trending rank (its position in the no-query list, if present)
   and which search found it. Cap ~40. Short tracks are fine (Instagram loops
   or trims; reels are ≤45 s).
2. **Decision — OpenAI Decisions API.** One `POST /v1/decisions`,
   `model: "gpt-6-luna"`, with the owner's OpenAI key (`vault.secret(…,
   "openai")`):
   - `input`: a user message with the reel as text (title, hook, category,
     `music_mood`, narrated or not) and the candidates as `input_json`
     (title, artist, trending rank, found-by search, duration).
   - one `choice` question, `name: "song"`, choices = candidates; `value` a
     meaningful label ("Title — Artist", made unique), `description` its
     trending rank and the search that found it. Instructions: pick the song
     that best suits this reel; prefer Hindi songs; another language when it
     sounds great and fits; Gen-Z, meme and viral sounds are good for light or
     funny stories; for death, disaster or tragedy pick the closest calm or
     emotional track, never a comic or party one; between similar fits, prefer
     the more trending.
   - The answer's `choice` is the song; its `confidence` is saved. A `refusal`
     answer → take the top trending candidate whose found-by search matches the
     mood (rule fallback), so a song is still attached.
   - Cost recorded via `costs` (kind `music_pick`, model `gpt-6-luna`;
     input tokens only — Decisions output is free).
3. **Attach.** `audio_volume`: 60 when narrated, 100 when not; `video_volume`:
   100 when narrated, 40 otherwise (clips' own sound under the song).
4. **Save** on the post: `posts.ig_music` jsonb
   `{audio_id, title, artist, confidence, trending_rank, found_by,
   audio_volume, video_volume}` (migration 0043). On a retry, reuse it.

### 5. Fallbacks — a post always goes out

| Situation | What goes out |
|---|---|
| Account on old Instagram Login | `final_key` (Freesound bed), as today |
| Decisions refuses or errors, or no OpenAI key | rule pick: the top trending candidate matching the mood — still a song |
| `/ig_audio` fails or returns nothing | `final_key` with its Freesound bed (no song is possible; never silent) |
| Container refused because of `audio_configuration` | retry once without it, using `final_key`; note on the post |
| Carousel / picture | slides, no music |

The refused-audio case must never surface as `Rejected` for the post.

### 6. Credits and caption

- When an Instagram song is attached, the Freesound credit is dropped from the
  Instagram caption (the IG file has no Freesound in it). Instagram shows the
  song itself; no extra credit line. YouTube's description is unchanged.

### 7. Post page

- Under the Instagram publish status: "Music: *Title* — Artist · trending #N",
  or "No Instagram song: <why> — posted with the background track". Read-only in v1.

### 8. Freesound on Instagram

Every normal Instagram reel gets a trending song and no Freesound. Freesound
reaches Instagram only in the two technical-failure rows above (Instagram's
music list unavailable, or the song refused), so a reel is never silent. It
stays on every YouTube Short. Freesound becomes YouTube-only by construction —
no switch to flip.

### 9. Who gets Unified Login (builder's call, confirmed with owner)

Until App Review grants Advanced Access, Unified Login works only for people
with a role on the Meta app. So the owner connects through Unified Login; other
users keep Instagram Login (and no trending music) until App Review is done.
The "Reconnect to get trending music" prompt shows only to the owner.

## Owner's setup steps (outside the code)

1. Make sure the Meta app is owned by a business portfolio.
2. App Dashboard → Instagram → **API setup with Unified login** → create a
   configuration with `instagram_basic`, `instagram_content_publish`,
   `instagram_manage_comments`, `instagram_manage_insights`; choose a
   non-expiring token if offered; set the redirect URL to
   `https://<site>/api/connect/instagram/callback`; copy the `config_id`.
3. Add `META_APP_ID`, `META_APP_SECRET`, `META_IG_CONFIG_ID` to the server env.
4. Reconnect Instagram on each channel.
5. Publish one reel; confirm the song is on it in the Instagram app.

## Testing

- Unit tests with recorded fixtures: `/ig_audio` replies, the picker's prompt
  and parsing, volume rules, every fallback row, host selection per `api`,
  renewal skipping Unified tokens, caption credits.
- Assemble test: two finals when Unified is connected, one otherwise.
- Tests run against the test DB URL, never the local `.env` (which is prod).
- Not testable here: real Meta calls. First live post is the real check.

## Left to the builder

- Exact search words per mood; candidate cap; prompt wording.
- File naming, function boundaries, migration details beyond the columns named.
