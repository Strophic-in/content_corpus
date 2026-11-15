# Instagram Trending Music Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Model routing (owner, 2026-11-15):** Opus plans and reviews; **Haiku implements**.
> Dispatch every implementer with `Agent(subagent_type="general-purpose", model="haiku")`
> and paste the task's full text, the Global Constraints, and the spec path into its
> prompt. Reviews of each task and the final whole-branch review run on Opus (the
> session model). Browser checks (Task 9) also go to a Haiku agent with the
> claude-in-chrome tools. Do not fork for implementers — forks ignore `model`.

**Goal:** Instagram Reels go out with a trending Instagram song picked for the reel by OpenAI's Decisions API, through a Unified Login connection; YouTube keeps the Freesound bed.

**Architecture:** A new `channel_accounts.api` column says which Instagram API an account uses; the Instagram module takes its Graph host per account. Assembly writes a second, music-free reel for Unified accounts. At publish time `corpus/ig_music.py` gathers candidates from `/ig_audio`, asks `POST /v1/decisions` to choose, and the REELS container carries `audio_configuration`. The web connect flow sends the owner through Unified Login.

**Tech Stack:** Python 3.11 worker (httpx, psycopg, pytest with `httpx.MockTransport`), Postgres migrations (plain SQL), Next.js 16 web app (TypeScript, no web test suite — `npm run lint` + `npx tsc --noEmit`).

**Spec:** `docs/superpowers/specs/2026-11-15-instagram-trending-music-design.md`

## Global Constraints

- Tests run ONLY through `bash db/dev/test.sh …` (pins the throwaway test DB). Never run `python db/migrate.py` bare or pytest without that script — the repo `.env` is PRODUCTION.
- Commits show only the owner: **no `Co-Authored-By` line**, no Claude attribution.
- Unified Graph host: `https://graph.facebook.com/v27.0`. Instagram Login host stays `https://graph.instagram.com/v23.0`.
- Decisions: `POST https://api.openai.com/v1/decisions`, `model: "gpt-6-luna"`, called with raw `httpx` (the installed `openai` SDK has no `decisions`).
- Volumes: narrated → `audio_volume 25, video_volume 100`; not narrated → `audio_volume 100, video_volume 40`. Narrated means `posts.audio_source == 'kokoro'`.
- Never reuse a song from the channel's last **20** Instagram posts. Candidate cap **40**.
- Always attach a song when `/ig_audio` returned any candidate; never post a silent reel.
- `channel_accounts.api` values: `'instagram_login'` (default) and `'unified'`.
- New env vars: `META_APP_ID`, `META_APP_SECRET`, `META_IG_CONFIG_ID`.
- Unified Login only for the owner (`memberships.role = 'owner'`); members keep Instagram Login.
- Code style: match the surrounding file — module docstrings explain why, short comments, no new dependencies.

## Review Focus

1. A Unified account must never hit `ig_refresh_token` (renewal or upkeep) — it would be marked expired. → Task 1 test.
2. `/ig_audio` failing or returning `[]` must publish `final_key` (with Freesound), not a silent `final_ig_key`. → Task 6 test.
3. Instagram refusing `audio_configuration` must retry once without it and still go live, not fail the post. → Task 2 test.
4. A retry of a publish job must reuse the saved `posts.ig_music` choice, not pick a different song. → Task 6 test.
5. Owner reconnecting to a different Instagram account than the one stored must be stopped with a clear message, not create a mismatch. → Task 7 (manual check in Task 9).

Also: a song refused *during processing* (container status `ERROR`) is handled like one refused at creation (Task 2); the web role must be granted the new `channel_accounts.api` column or the callback fails in production only (Task 1 access test).

## Facts read from the APIs (2026-11-15) — do not re-guess

- Unified login URL: `https://www.facebook.com/dialog/oauth?client_id&config_id&redirect_uri&response_type=code` (+ our `state`).
- Code exchange: `GET https://graph.facebook.com/v27.0/oauth/access_token?client_id&client_secret&code` — send `redirect_uri` too (the manual Facebook login flow requires it to match the dialog's).
- Accounts: `GET https://graph.facebook.com/v27.0/me/assigned_instagram_accounts?fields=id,username` → `{"data": [{"id", "username"}], "paging": …}`.
- Decisions `choice` question: **2–255 choices**, unique values. Answers in question order; any can be `{"type": "refusal", "name"}`. Reply has `usage.input_tokens` and `usage.input_tokens_details.cached_tokens`; output is free.
- `vault.secret(user_id, name)` returns `None` when the key isn't stored.
- Web-role column grants live in `db/access.sql` (re-applied after every migrate), not in migrations.

---

### Task 0: Branch

- [ ] Create `feat/ig-trending-music` from `main` (the spec and plan commits are on local `main`, unpushed): `git switch -c feat/ig-trending-music`. All tasks commit there.

### Task 1: Migration 0043 and per-account Graph host

**Files:**
- Create: `db/migrations/0043_ig_music.sql`
- Modify: `worker/corpus/publish/instagram.py` (host constant + `host()`; every function that builds a URL takes `graph`)
- Modify: `worker/corpus/handlers/publish_post.py:197-266` (`_instagram_token`, `upkeep`)
- Modify: `worker/corpus/stats.py:63-79`
- Modify: `db/access.sql:166-174` (add `api` to the web role's `select`, `insert` and `update` column lists on `channel_accounts`; `posts` is already `grant select` on the whole table)
- Test: `worker/tests/test_publish.py`, `db/tests/test_access.py` (next to the channel_accounts test at ~line 377)

**Interfaces:**
- Produces: `instagram.GRAPH_UNIFIED = "https://graph.facebook.com/v27.0"`; `instagram.host(api: str | None) -> str` (`'unified'` → `GRAPH_UNIFIED`, anything else → `GRAPH`); `instagram.publish(..., graph: str = GRAPH)` and `instagram.comment(..., graph: str = GRAPH)`; private helpers (`_create`, `_create_images`, `_status`, `_wait_until_processed`, `_find_published`, `_result`) gain a `graph` parameter. Columns `channel_accounts.api`, `posts.final_ig_key`, `posts.ig_music`.

- [ ] **Step 1: Write the migration**

```sql
-- Trending Instagram music (spec 2026-11-15): which Instagram API an account is
-- connected through — the Audio API exists only on Unified Login — the reel's
-- music-free copy for Instagram, and the song picked for it.
alter table channel_accounts
  add column api text not null default 'instagram_login' check (api in ('instagram_login', 'unified'));
alter table posts
  add column final_ig_key text,
  add column ig_music jsonb;
```

- [ ] **Step 2: Write the failing tests** (in `test_publish.py`, Instagram section)

```python
def test_instagram_host_follows_the_account_api():
    assert instagram.host("unified") == "https://graph.facebook.com/v27.0"
    assert instagram.host("instagram_login") == instagram.GRAPH
    assert instagram.host(None) == instagram.GRAPH

def test_instagram_publishes_through_the_unified_host(video):
    fake = FakeInstagram(version="v27.0")
    out = instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK, caption="A reel",
                            attempt={}, save=lambda **f: None, sleep=lambda s: None,
                            graph=instagram.GRAPH_UNIFIED)
    assert out["remote_id"] == "m1" and fake.published == 1

def _due_unified(owner, user, pid):
    """An account due for renewal by its dates — but on Unified Login."""
    owner.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, token_ciphertext,
                                                   token_expires_at, api, updated_at)
                     select %s, channel_id, 'instagram', '178', %s, now() + interval '2 days', 'unified',
                            now() - interval '3 days' from posts where id = %s""", (user, encrypt("tok"), pid))
    return owner.execute("select * from channel_accounts where external_id = '178'").fetchone()

def test_upkeep_never_renews_a_unified_token(owner, user, monkeypatch):
    _due_unified(owner, user, _ready_post(owner, user))
    calls = []
    monkeypatch.setattr(publish_post.instagram, "refresh", lambda *a: calls.append(a) or ("new", 5_184_000))
    monkeypatch.setattr(publish_post, "_last_upkeep", -1e18)      # upkeep's hourly gate is open
    monkeypatch.setattr(publish_post, "_last_stats", 1e18)        # no stats round
    publish_post.upkeep()
    assert calls == []
    assert owner.execute("select status from channel_accounts where external_id = '178'").fetchone()["status"] == "connected"

def test_publishing_never_renews_a_unified_token(owner, user, monkeypatch):
    acc = _due_unified(owner, user, _ready_post(owner, user))
    calls = []
    monkeypatch.setattr(publish_post.instagram, "refresh", lambda *a: calls.append(a) or ("new", 5_184_000))
    assert publish_post._instagram_token(httpx.Client(), acc) == "tok" and calls == []
```

And in `db/tests/test_access.py`, beside the existing channel_accounts test: the web role can insert and update a row with `api = 'unified'` and read `api` back (follow that test's connection helpers).

Change `FakeInstagram.__init__` to take `version: str = "v23.0"` and match paths against `f"/{self.version}/178/media"` etc. instead of the hard-coded `/v23.0/…`.

- [ ] **Step 3: Run to see them fail**

Run: `bash db/dev/test.sh worker/tests/test_publish.py -k "host or unified" -q`
Expected: FAIL (`host` / `GRAPH_UNIFIED` / `graph=` not defined).

- [ ] **Step 4: Implement**

- `instagram.py`: add `GRAPH_UNIFIED`, `host()`, thread `graph` through every URL; `refresh()` stays on `graph.instagram.com` (Instagram Login only).
- `publish_post.py`: in `run`, pass `graph=instagram.host(acc.get("api"))` to `instagram.publish` and to `instagram.comment` (the first-comment path ~line 152). `_instagram_token`: when `acc.get("api") == "unified"` return the decrypted token with only the expiry check (no renewal). `upkeep` query: add `and api = 'instagram_login'`.
- `stats.py`: select `token_ciphertext, api`, call `f"{instagram.host(acc['api'])}/{x['remote_id']}"`.
- `db/access.sql`: add `api` to the three column lists named under Files.
- Update the module docstring of `instagram.py`: both APIs, which host each uses.

- [ ] **Step 5: Run the publish suite**

Run: `bash db/dev/test.sh worker/tests/test_publish.py -q`
Expected: all pass (old tests still green with default `version="v23.0"`).

- [ ] **Step 6: Commit**

```bash
git add db/migrations/0043_ig_music.sql db/access.sql db/tests/test_access.py worker/corpus/publish/instagram.py worker/corpus/handlers/publish_post.py worker/corpus/stats.py worker/tests/test_publish.py
git commit -m "Instagram accounts know their API: Unified Login on graph.facebook.com, never refreshed like the old tokens"
```

---

### Task 2: Audio on the Reel container, with one retry without it

**Files:**
- Modify: `worker/corpus/publish/instagram.py` (`publish`, `_create`)
- Test: `worker/tests/test_publish.py`

**Interfaces:**
- Consumes: Task 1's `graph` parameter.
- Produces: `instagram.publish(..., audio: dict | None = None, fallback_video_url: str | None = None)`. `audio` is `{"audio_id": str, "audio_volume": int, "video_volume": int}` sent as `audio_configuration=json.dumps(audio)` on the REELS container. If **either** creating the container with `audio` **or** waiting for it to process (status `ERROR`) raises `Rejected`, it makes one new container **without** `audio_configuration` from `fallback_video_url or video_url` (saving its id over the old one) and waits for that; the returned dict then has `"audio_dropped": "<Instagram's message>"`. Otherwise the returned dict has `"audio_id": audio["audio_id"]` when audio was sent. A `Rejected` from the song-less container propagates as today.

- [ ] **Step 1: Write the failing tests**

```python
def test_instagram_attaches_the_song_to_the_reel(video):
    fake = FakeInstagram()
    out = instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK, caption="A reel",
                            attempt={}, save=lambda **f: None, sleep=lambda s: None,
                            audio={"audio_id": "587", "audio_volume": 25, "video_volume": 100})
    assert json.loads(fake.audio) == {"audio_id": "587", "audio_volume": 25, "video_volume": 100}
    assert out["audio_id"] == "587" and "audio_dropped" not in out

def test_instagram_posts_without_the_song_when_it_is_refused(video):
    fake = FakeInstagram(refuse_audio=True)
    out = instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK + "&ig", caption="A reel",
                            attempt={}, save=lambda **f: None, sleep=lambda s: None,
                            audio={"audio_id": "587", "audio_volume": 25, "video_volume": 100},
                            fallback_video_url=LINK)
    assert out["remote_id"] == "m1" and "audio" in out["audio_dropped"]
    assert fake.video_url == LINK and fake.audio == ""        # second container: bed version, no song
```

```python
def test_instagram_posts_without_the_song_when_processing_fails_on_it(video):
    fake = FakeInstagram(audio_breaks_processing=True)
    out = instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK + "&ig", caption="A reel",
                            attempt={}, save=lambda **f: None, sleep=lambda s: None,
                            audio={"audio_id": "587", "audio_volume": 25, "video_volume": 100},
                            fallback_video_url=LINK)
    assert out["remote_id"] == "m1" and out["audio_dropped"] and fake.created == 2 and fake.audio == ""
```

Extend `FakeInstagram`: `refuse_audio: bool = False`, `audio_breaks_processing: bool = False`; record `self.audio = form.get("audio_configuration", [""])[0]` on every container create; when `refuse_audio` and `audio_configuration` is present, return `400 {"error": {"message": "Invalid audio", "code": 100}}`; when `audio_breaks_processing`, a container created **with** audio reports `status_code: "ERROR"` (`status: "Error: audio unavailable"`) and one without reports `FINISHED`. Give the two containers different ids (`c1`, `c2`) and accept `media_publish` / status checks for either.

- [ ] **Step 2: Run to see them fail**

Run: `bash db/dev/test.sh worker/tests/test_publish.py -k "song" -q`
Expected: FAIL (unexpected keyword `audio`).

- [ ] **Step 3: Implement** in `instagram.py` as the Interfaces block says. The retry happens only in the create step of a new container; a resumed container (`_container_of`) is published as it is.

- [ ] **Step 4: Run the publish suite**

Run: `bash db/dev/test.sh worker/tests/test_publish.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add worker/corpus/publish/instagram.py worker/tests/test_publish.py
git commit -m "Reels can carry an Instagram song; a refused song is dropped, never the post"
```

---

### Task 3: Song candidates from `/ig_audio`

**Files:**
- Create: `worker/corpus/ig_music.py`
- Test: `worker/tests/test_ig_music.py` (new; pure unit tests, no DB)

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class Track:
      audio_id: str; title: str; artist: str; duration_ms: int
      trending_rank: int | None   # 1-based position in the no-query list, None if not there
      found_by: str               # "trending" or the search text that found it
      @property
      def label(self) -> str      # "Title — Artist"
  CAP = 40
  TRENDING_SLOTS = 15         # the no-query list may fill at most this many, so searches always get room
  RECENT = 20
  MOOD_SEARCHES: dict[str, list[str]]   # mood → [hindi search, english search]
  MEME_SEARCHES = ["viral meme song", "phonk"]
  def searches(mood: str | None) -> list[str]
  def candidates(client: httpx.Client, *, graph: str, token: str, ig_user_id: str,
                 mood: str | None, exclude: set[str]) -> list[Track]
  def rule_pick(tracks: list[Track], mood: str | None) -> Track
  def volumes(narrated: bool) -> dict
  ```
- `searches(mood)` returns, in order: `"hindi trending"`, `"bollywood"`, the mood's Hindi search, `MEME_SEARCHES…`, the mood's English search (unknown/None mood → `neutral-corporate`'s). `MOOD_SEARCHES` covers the 8 moods in `corpus/music.py` `MOODS`; the builder chooses the words (e.g. `somber` → `["sad hindi song", "emotional piano"]`, `energetic-hype` → `["bollywood party", "hype beat"]`).
- `candidates`: first `GET {graph}/ig_audio?audio_type=music&user_id={ig_user_id}&access_token=…` (trending; ranks 1..n), then one request per search with `search_query`. Each reply is `{"audio": [...]}` with `audio_id, title, display_artist, duration_in_ms`. Take at most `TRENDING_SLOTS` tracks from the trending list (ranks are their positions in the full list), then fill from the searches in order. De-duplicate by `audio_id` keeping the first sighting but keeping its trending rank if any; drop `exclude`; stop at `CAP`. A failing search (non-200 or bad JSON) is skipped; if the trending call and every search fail, return `[]`. Auth errors (`code 190` / HTTP 401) raise `instagram.AuthExpired`.
- `rule_pick`: the best-ranked track found by a search for this mood (Hindi first), else the best trending rank, else the first.
- `volumes(True) == {"audio_volume": 25, "video_volume": 100}`; `volumes(False) == {"audio_volume": 100, "video_volume": 40}`.

- [ ] **Step 1: Write the failing tests**

```python
def fake_audio(replies: dict):          # search_query or "" → list of audio dicts, or an int status
    def handler(req):
        assert req.url.path == "/v27.0/ig_audio" and req.url.params["audio_type"] == "music"
        r = replies.get(req.url.params.get("search_query", ""), [])
        return httpx.Response(r, json={"error": {"message": "x", "code": 2}}) if isinstance(r, int) \
            else httpx.Response(200, json={"audio": r})
    return httpx.Client(transport=httpx.MockTransport(handler))

def a(i, title="Song", artist="Artist", ms=30000):
    return {"audio_id": str(i), "title": f"{title} {i}", "display_artist": artist, "duration_in_ms": ms}

def test_candidates_rank_trending_then_add_searches_without_repeats():
    c = fake_audio({"": [a(1), a(2)], "hindi trending": [a(2), a(3)], "bollywood": [a(4)]})
    got = ig_music.candidates(c, graph=GRAPH, token="t", ig_user_id="178", mood="somber", exclude={"4"})
    assert [t.audio_id for t in got] == ["1", "2", "3"]
    assert [t.trending_rank for t in got] == [1, 2, None]
    assert got[2].found_by == "hindi trending"

def test_trending_leaves_room_for_searches_and_the_cap_holds():
    c = fake_audio({"": [a(i) for i in range(50)], "hindi trending": 500,
                    "bollywood": [a(100 + i) for i in range(50)]})
    got = ig_music.candidates(c, graph=GRAPH, token="t", ig_user_id="178", mood=None, exclude=set())
    assert len(got) == 40
    assert sum(t.found_by == "trending" for t in got) == 15
    assert sum(t.found_by == "bollywood" for t in got) == 25         # the failing search was skipped

def test_candidates_are_empty_when_instagram_has_nothing():
    c = fake_audio({"": 500})
    assert ig_music.candidates(c, graph=GRAPH, token="t", ig_user_id="178", mood="playful", exclude=set()) == []

def test_searches_put_hindi_first_and_include_meme_sounds():
    s = ig_music.searches("somber")
    assert s[:2] == ["hindi trending", "bollywood"] and "viral meme song" in s
    assert ig_music.searches("no-such-mood") == ig_music.searches("neutral-corporate")

def test_rule_pick_prefers_the_moods_search_then_trending():
    t1 = ig_music.Track("1", "A", "x", 1, 1, "trending")
    t2 = ig_music.Track("2", "B", "y", 1, None, ig_music.MOOD_SEARCHES["somber"][0])
    assert ig_music.rule_pick([t1, t2], "somber").audio_id == "2"
    assert ig_music.rule_pick([t1], "somber").audio_id == "1"

def test_volumes():
    assert ig_music.volumes(True) == {"audio_volume": 25, "video_volume": 100}
    assert ig_music.volumes(False) == {"audio_volume": 100, "video_volume": 40}
```
(`GRAPH = "https://graph.facebook.com/v27.0"` at the top of the test file.)

- [ ] **Step 2: Run to see them fail**

Run: `bash db/dev/test.sh worker/tests/test_ig_music.py -q` → FAIL (no module `corpus.ig_music`).

- [ ] **Step 3: Implement** `worker/corpus/ig_music.py` per the Interfaces block, with a module docstring stating the owner's rules (Hindi first, Gen-Z/meme welcome, always a song, Decisions API picks — Task 4).

- [ ] **Step 4: Run** `bash db/dev/test.sh worker/tests/test_ig_music.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add worker/corpus/ig_music.py worker/tests/test_ig_music.py
git commit -m "Song candidates from Instagram: trending first, then Hindi, meme and mood searches"
```

---

### Task 4: The pick, by OpenAI's Decisions API

**Files:**
- Modify: `worker/corpus/ig_music.py`
- Test: `worker/tests/test_ig_music.py`

**Interfaces:**
- Consumes: Task 3's `Track`, `rule_pick`.
- Produces:
  ```python
  DECISIONS = "https://api.openai.com/v1/decisions"
  MODEL = "gpt-6-luna"
  INSTRUCTIONS: str
  def decide(client: httpx.Client | None, api_key: str | None, reel: dict, tracks: list[Track]
             ) -> tuple[Track, float | None, Usage | None, str]
  ```
  `reel` keys: `title, hook, category, mood, narrated`. Returns `(track, confidence, usage, picked_by)` with `picked_by` one of `"decisions"`, `"rule"`, `"only"`.
  - One candidate → `(it, None, None, "only")`, no call (a choice needs 2–255 options; never more than `CAP` here).
  - No key, an HTTP error, a `refusal` answer, or a `choice` value not among the labels → `(rule_pick(tracks, reel["mood"]), None, usage_or_None, "rule")`; return the usage whenever the reply carried one. On a non-200, `log.warning` the status and the first 300 characters of the body (a permanent 400 must be visible, not silently covered by the rule pick). `Usage` is `corpus.script.llm.Usage(model=MODEL, input_tokens=…, output_tokens=0, cached_input_tokens=…)` from the reply's `usage.input_tokens` and `usage.input_tokens_details.cached_tokens`.
- Request body:
  ```python
  {"model": MODEL,
   "input": [{"role": "user", "content": [
       {"type": "input_text", "text": <reel as lines: title, hook, category, mood, narrated yes/no>},
       {"type": "input_json", "data": {"songs": [{"song": t.label, "artist": t.artist,
           "trending_rank": t.trending_rank, "found_by": t.found_by,
           "seconds": round(t.duration_ms / 1000)} for t in tracks]}}]}],
   "questions": [{"type": "choice", "name": "song", "instructions": INSTRUCTIONS,
                  "choices": [{"value": label, "description": f"trending #{rank}" or "not in trending" + f"; found by: {found_by}"} ...]}]}
  ```
  Labels must be unique: when two tracks share `label`, suffix ` (2)`, ` (3)`.
- `INSTRUCTIONS` (exact copy, from the owner's rules):
  "Pick the song that best suits this Instagram reel. Prefer Hindi songs. A song in another language is fine when it sounds great and suits the reel. Gen-Z, meme and viral sounds are good for light, funny or surprising stories. For death, disaster or tragedy pick the closest calm or emotional song, never a comic or party one. When songs fit equally, prefer the more trending one."

- [ ] **Step 1: Write the failing tests**

```python
TRACKS = [ig_music.Track("1", "Party Song", "DJ", 30000, 1, "trending"),
          ig_music.Track("2", "Dil Udaas", "Arijit", 40000, None, ig_music.MOOD_SEARCHES["somber"][0])]
REEL = {"title": "Flood kills 12", "hook": "…", "category": "News", "mood": "somber", "narrated": True}

def fake_decisions(reply, seen):
    def handler(req):
        seen.append(json.loads(req.content)); assert req.url == ig_music.DECISIONS
        assert req.headers["authorization"] == "Bearer sk"
        return httpx.Response(200, json=reply) if isinstance(reply, dict) else httpx.Response(reply)
    return httpx.Client(transport=httpx.MockTransport(handler))

def test_decide_sends_one_choice_question_and_returns_the_pick():
    seen = []
    c = fake_decisions({"answers": [{"type": "choice", "name": "song", "choice": "Dil Udaas — Arijit",
                                     "confidence": 0.8}],
                        "usage": {"input_tokens": 900, "input_tokens_details": {"cached_tokens": 0}}}, seen)
    track, conf, usage, by = ig_music.decide(c, "sk", REEL, TRACKS)
    assert track.audio_id == "2" and conf == 0.8 and by == "decisions"
    assert usage.input_tokens == 900 and usage.output_tokens == 0
    body = seen[0]
    assert body["model"] == "gpt-6-luna" and body["questions"][0]["type"] == "choice"
    assert [ch["value"] for ch in body["questions"][0]["choices"]] == ["Party Song — DJ", "Dil Udaas — Arijit"]
    assert "Prefer Hindi songs" in body["questions"][0]["instructions"]

def test_decide_falls_back_to_the_rule_pick():
    for reply in (500, {"answers": [{"type": "refusal", "name": "song"}]},
                  {"answers": [{"type": "choice", "name": "song", "choice": "Not offered"}]}):
        track, conf, _, by = ig_music.decide(fake_decisions(reply, []), "sk", REEL, TRACKS)
        assert track.audio_id == "2" and conf is None and by == "rule"
    assert ig_music.decide(None, None, REEL, TRACKS)[0].audio_id == "2"     # no key: no call at all
    assert ig_music.decide(None, "sk", REEL, TRACKS[:1])[3] == "only"       # one song: nothing to decide

def test_duplicate_labels_are_made_unique():
    twins = [ig_music.Track("1", "Same", "A", 1, 1, "trending"), ig_music.Track("2", "Same", "A", 1, 2, "trending")]
    seen = []
    ig_music.decide(fake_decisions({"answers": [{"type": "choice", "name": "song", "choice": "Same — A (2)",
                                                 "confidence": 0.5}]}, seen), "sk", REEL, twins)
    assert [ch["value"] for ch in seen[0]["questions"][0]["choices"]] == ["Same — A", "Same — A (2)"]
```

- [ ] **Step 2: Run to see them fail** — `bash db/dev/test.sh worker/tests/test_ig_music.py -k decide -q` → FAIL.
- [ ] **Step 3: Implement** `decide` per the Interfaces block (timeout 20 s; `Authorization: Bearer {api_key}`).
- [ ] **Step 4: Run** `bash db/dev/test.sh worker/tests/test_ig_music.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add worker/corpus/ig_music.py worker/tests/test_ig_music.py
git commit -m "OpenAI Decisions picks the reel's song; a refusal or outage falls back to the mood's best match"
```

---

### Task 5: A music-free reel for Instagram

**Files:**
- Modify: `worker/corpus/handlers/assemble.py:47-77`
- Test: `worker/tests/test_render_pipeline.py` (next to `test_render_then_assemble_to_a_ready_reel`, line ~381)

**Interfaces:**
- Produces: `posts.final_ig_key` set by assembly when the post's channel has a `channel_accounts` row with `platform='instagram' and status='connected' and api='unified'`:
  - with a Freesound track: a second `media.join_segments(..., music=None, ...)` into `final.ig.mp4`, stored at `f"{prefix}/final/{script_id}.ig.mp4"` with `kind="final"`;
  - without a track: `final_ig_key = final_key` (same file, no second join).
  - no Unified account: `final_ig_key` stays null.
- Helper `_wants_ig_copy(channel_id) -> bool` in `assemble.py`.
- Every assembly also clears a stale choice: the final `update posts` sets `ig_music = null` (a re-assembled reel gets a fresh pick) and `final_ig_key` to the new value or null.

- [ ] **Step 1: Write the failing tests** (in `test_render_pipeline.py`; reuse that file's imports — `media` there is the module whose `join_segments` assembly calls; import `corpus.handlers.assemble as assemble_handler` and `corpus.music as music` if not already)

```python
def _render_and_assemble(owner, user, pid):
    cpu_all().tick()
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    assert gpu_lane().tick()
    drain(cpu_all())

def _with_tone_and_spy(monkeypatch, tmp_path):
    tone = tmp_path / "tone.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", str(tone)],
                   check=True)
    monkeypatch.setattr(assemble_handler, "_music", lambda post, script_id, work: assemble_handler._Track(
        music.Track(1, "Tone", "me", "https://example.test/tone", tone), "uplifting"))
    joins, real = [], media.join_segments
    def spy(segments, out, **kw):
        joins.append(kw.get("music") is not None)
        return real(segments, out, **kw)
    monkeypatch.setattr(media, "join_segments", spy)
    return joins

def test_assemble_keeps_a_music_free_copy_for_unified_instagram(s3, owner, user, gpu, tmp_path, segment_cache,
                                                                monkeypatch):
    pid, sid = approved_narrated_post(owner, user)
    owner.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, token_ciphertext, api)
                     select %s, channel_id, 'instagram', '178', 'x', 'unified' from posts where id = %s""", (user, pid))
    owner.execute("update posts set ig_music = '{\"audio_id\": \"old\"}' where id = %s", (pid,))
    joins = _with_tone_and_spy(monkeypatch, tmp_path)
    _render_and_assemble(owner, user, pid)
    row = owner.execute("select final_key, final_ig_key, ig_music from posts where id = %s", (pid,)).fetchone()
    assert row["final_ig_key"].endswith(".ig.mp4") and row["final_ig_key"] != row["final_key"]
    assert joins == [True, False] and row["ig_music"] is None

def test_assemble_makes_one_reel_without_unified_instagram(s3, owner, user, gpu, tmp_path, segment_cache,
                                                           monkeypatch):
    pid, sid = approved_narrated_post(owner, user)
    joins = _with_tone_and_spy(monkeypatch, tmp_path)
    _render_and_assemble(owner, user, pid)
    assert joins == [True]
    assert owner.execute("select final_ig_key from posts where id = %s", (pid,)).fetchone()["final_ig_key"] is None
```
(If `join_segments` is called positionally with more than two arguments in `assemble.py`, make the spy `def spy(*a, **kw)` and read `music` from `kw`.)

- [ ] **Step 2: Run to see it fail** — `bash db/dev/test.sh worker/tests/test_render_pipeline.py -k ig -q` → FAIL.
- [ ] **Step 3: Implement** in `assemble.run`; add `final_ig_key` to the final `update posts …` statement; log `"instagram copy without music"` in the assemble log line.
- [ ] **Step 4: Run** `bash db/dev/test.sh worker/tests/test_render_pipeline.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add worker/corpus/handlers/assemble.py worker/tests/test_render_pipeline.py
git commit -m "Assembly keeps a music-free copy of the reel for Instagram's own songs"
```

---

### Task 6: Publishing wires the song in

**Files:**
- Modify: `worker/corpus/ig_music.py` (add `choose`)
- Modify: `worker/corpus/handlers/publish_post.py:86-105`
- Test: `worker/tests/test_publish.py` (handler section, next to `test_handler_posts_to_instagram_from_a_signed_link`)

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  ```python
  def choose(client: httpx.Client, *, post: dict, acc: dict, token: str, job_id=None) -> dict | None
  ```
  Returns the saved `posts.ig_music` dict `{audio_id, title, artist, confidence, trending_rank, found_by, picked_by, audio_volume, video_volume}` or `None` when there are no candidates. Steps: if `post["ig_music"]` has a `dropped` key → return `None` (Instagram refused that song; post with the bed). If it has an `audio_id` → return it unchanged (retry reuse). Else read `music_mood` from `scripts` (`post["approved_script_id"]`), the category name, the 20 most recent `ig_music->>'audio_id'` of posts on the same channel; `candidates(...)` with `graph=instagram.host("unified")`; `[]` → `None`. Else `decide(client, vault.secret(user_id, "openai"), reel, tracks)`; record usage with `costs.record_llm(usage, user_id=…, kind="music_pick", post_id=…, channel_id=…, job_id=job_id, note="Instagram song")` when usage is not None; save to `posts.ig_music` and return it.
- Handler, Instagram reel branch (not slides): when `acc["api"] == "unified"` and `post["final_ig_key"]`:
  - `pick = ig_music.choose(...)` (any exception from it → log a warning, `pick = None`; `AuthExpired` still propagates);
  - with a pick: `video_url = signed(final_ig_key)`, `audio = {audio_id, audio_volume, video_volume}`, `fallback_video_url = signed(final_key)`, and the caption's credits drop every entry starting with `"Music:"`;
  - no pick: today's path (`final_key`, no audio).
  - After publishing, if `out` has `audio_dropped`: update `posts.ig_music` with `"dropped": out["audio_dropped"]` and log a post event `"posted to Instagram without its song"`.

- [ ] **Step 1: Write the failing tests**

```python
def _unified(owner, user, pid):
    owner.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, token_ciphertext, api)
                     select %s, channel_id, 'instagram', '178', %s, 'unified' from posts where id = %s""",
                  (user, encrypt("tok"), pid))
    owner.execute("update posts set final_ig_key = 'u/p/final.ig.mp4', credits = %s where id = %s",
                  (json.dumps(["Music: “x” by y (Freesound, CC0)"]), pid))

SONG = {"audio_id": "587", "title": "Dil", "display_artist": "A", "duration_in_ms": 30000}

def _publish_unified(owner, user, fake_http, monkeypatch, fake, ig_music=None):
    fake_http(fake)
    monkeypatch.setattr(publish_post.storage, "signed_url", lambda key, seconds: f"{LINK}&key={key}")
    monkeypatch.setattr(publish_post.instagram, "POLL_S", 0)
    pid = _ready_post(owner, user)
    _unified(owner, user, pid)
    if ig_music is not None:
        owner.execute("update posts set ig_music = %s where id = %s", (json.dumps(ig_music), pid))
    _request(owner, user, pid, ("instagram",))
    assert Runner("publish", {"publish_post": publish_post.HANDLER}).tick()
    job = owner.execute("select state, error from jobs where dedupe_key = %s", (f"publish:{pid}:instagram",)).fetchone()
    assert job["state"] == "succeeded", job["error"]
    return pid

def test_handler_attaches_a_picked_song_from_the_music_free_copy(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[SONG])
    pid = _publish_unified(owner, user, fake_http, monkeypatch, fake)
    assert fake.video_url.endswith("key=u/p/final.ig.mp4")
    assert json.loads(fake.audio) == {"audio_id": "587", "audio_volume": 100, "video_volume": 40}  # not narrated
    assert "Freesound" not in fake.caption
    saved = owner.execute("select ig_music from posts where id = %s", (pid,)).fetchone()["ig_music"]
    assert saved["audio_id"] == "587" and saved["picked_by"] == "only"

def test_handler_keeps_the_bed_version_when_instagram_has_no_songs(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[])
    pid = _publish_unified(owner, user, fake_http, monkeypatch, fake)
    assert fake.video_url.endswith("key=u/p/final.mp4") and fake.audio == ""
    assert owner.execute("select ig_music from posts where id = %s", (pid,)).fetchone()["ig_music"] is None

def test_a_retry_reuses_the_saved_song(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[{**SONG, "audio_id": "999"}])
    _publish_unified(owner, user, fake_http, monkeypatch, fake,
                     ig_music={"audio_id": "587", "audio_volume": 25, "video_volume": 100})
    assert json.loads(fake.audio)["audio_id"] == "587" and fake.audio_searches == 0

def test_a_refused_song_is_not_tried_again(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[SONG])
    _publish_unified(owner, user, fake_http, monkeypatch, fake,
                     ig_music={"audio_id": "587", "dropped": "Invalid audio"})
    assert fake.video_url.endswith("key=u/p/final.mp4") and fake.audio == "" and fake.audio_searches == 0
```

Extend `FakeInstagram`: `audio_list: list | None = None`; `GET /{version}/ig_audio` returns `{"audio": audio_list or []}` for every query and counts `self.audio_searches += 1`. `_ready_post` makes a post with `audio_source = 'ltx_native'` (not narrated) — check it, and adjust the expected volumes if it doesn't. `vault.secret` returns `None` here (no OpenAI key stored), so `decide` never calls OpenAI — no Decisions fake is needed.

- [ ] **Step 2: Run to see them fail** — `bash db/dev/test.sh worker/tests/test_publish.py -k "song or bed_version" -q` → FAIL.
- [ ] **Step 3: Implement** `choose` and the handler branch per the Interfaces block.
- [ ] **Step 4: Run** `bash db/dev/test.sh -q` (whole worker + db suite) → all pass.
- [ ] **Step 5: Commit**

```bash
git add worker/corpus/ig_music.py worker/corpus/handlers/publish_post.py worker/tests/test_publish.py
git commit -m "Instagram reels go out with a trending song picked for them; YouTube keeps Freesound"
```

---

### Task 7: Unified Login connect flow (web)

**Files:**
- Modify: `apps/web/lib/oauth.ts`
- Modify: `apps/web/app/api/connect/[platform]/start/route.ts`
- Modify: `apps/web/app/api/connect/[platform]/callback/route.ts`
- Modify: `.env.example` (three new vars, commented)

**Interfaces:**
- Produces in `oauth.ts`:
  ```ts
  export type IgApi = "unified" | "instagram_login";
  export function unifiedConfigured(): boolean            // META_APP_ID && META_APP_SECRET && META_IG_CONFIG_ID
  export function configured(p: Platform): boolean        // instagram: old vars OR unifiedConfigured()
  export function newState(userId, channelId, p, api?: IgApi)   // State gains `a?: IgApi`
  export function authorizeUrl(p: Platform, state: string, api?: IgApi): string
  export async function exchange(p: Platform, code: string, api?: IgApi, keepId?: string | null): Promise<Connected>
  // Connected gains `api: IgApi | null`
  ```
- Unified authorize URL: `https://www.facebook.com/dialog/oauth?client_id=META_APP_ID&config_id=META_IG_CONFIG_ID&redirect_uri=…&response_type=code&state=…`.
- Unified exchange: `GET https://graph.facebook.com/v27.0/oauth/access_token?client_id&client_secret&redirect_uri&code` → `access_token`, optional `expires_in` (absent/0 → `expiresAt: null`). Then `GET https://graph.facebook.com/v27.0/me/assigned_instagram_accounts?fields=id,username&access_token=…` → `data[].id`; pick the id equal to `keepId` when given, else the first; if `keepId` is given and absent from `data`, throw `Error("That isn't the Instagram account this channel was connected to — log in with @<handle> or disconnect first.")` (handle passed in the message by the callback). Profile: `GET https://graph.facebook.com/v27.0/{id}?fields=username,name,profile_picture_url&access_token=…`. `scopes`: `[]` (the token's permissions come from the configuration).
- Start route: look up `memberships.role` for the session user (reuse `membership()` from `lib/session.ts`); `api = (p === "instagram" && unifiedConfigured() && role === "owner") ? "unified" : "instagram_login"`; if `api === "instagram_login"` and the old `INSTAGRAM_APP_*` vars are missing, send back "Instagram isn't set up on the server yet."
- Callback: read `state.a`; for Unified, fetch the channel's current Instagram row (`external_id, handle, api`) and pass `keepId = row?.api === "instagram_login" ? row.external_id : null` to `exchange`; insert/update `api` along with the other columns.

- [ ] **Step 1: Implement** the three files per the Interfaces block.
- [ ] **Step 2: Typecheck and lint**

Run: `cd apps/web && npx tsc --noEmit && npm run lint`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/lib/oauth.ts "apps/web/app/api/connect/[platform]/start/route.ts" "apps/web/app/api/connect/[platform]/callback/route.ts" .env.example
git commit -m "The owner connects Instagram through Unified Login; members keep Instagram Login"
```

---

### Task 8: Show the song and the reconnect prompt (web)

**Files:**
- Modify: `apps/web/lib/posts.ts:22,96` (select and type `ig_music`)
- Modify: `apps/web/app/(app)/posts/[id]/page.tsx:339-342,646-649`
- Modify: `apps/web/app/(app)/channels/channel-forms.tsx` (`AccountData` gains `api`; `ConnectionCard` gains `owner: boolean`)
- Modify: `apps/web/app/(app)/channels/[id]/page.tsx:68-70` (select `api`; pass `owner`)
- Modify: `apps/web/lib/channels.ts` if it holds the accounts query (add `api`)

**Interfaces:**
- `ig_music: { audio_id: string; title: string; artist: string; trending_rank: number | null; dropped?: string } | null`.
- Post page, beside the existing Freesound line: `Instagram song: “{title}” by {artist}{trending_rank ? ` · trending #${trending_rank}` : ""}`; when `dropped`: `Instagram refused the song — posted with the background track.` Existing Freesound line text becomes `YouTube music: …` when `ig_music` is set.
- Connection card: when `platform === "instagram" && owner && connected && account.api !== "unified"`, show a note `Reconnect to get trending Instagram music.` above the buttons.

- [ ] **Step 1: Implement** per the Interfaces block, matching the existing classes on those lines.
- [ ] **Step 2: Typecheck and lint** — `cd apps/web && npx tsc --noEmit && npm run lint` → no errors.
- [ ] **Step 3: Commit**

```bash
git add apps/web
git commit -m "Post page shows the Instagram song; the owner is asked to reconnect for it"
```

---

### Task 9: Owner setup, deploy and the live check

**Files:**
- Modify: `docs/DEPLOY.md` (an "Instagram Unified Login" section: the five owner setup steps from the spec, verbatim)

- [ ] **Step 1: Write the DEPLOY.md section and commit**

```bash
git add docs/DEPLOY.md
git commit -m "Deploy notes: Instagram Unified Login setup"
```

- [ ] **Step 2: Whole-branch review on Opus** (superpowers:requesting-code-review), fix findings.
- [ ] **Step 3: Owner does the Meta App Dashboard setup** and adds `META_APP_ID`, `META_APP_SECRET`, `META_IG_CONFIG_ID` on the server. Blocked until the owner reports done.
- [ ] **Step 4: Apply migration 0043 to production and deploy** — only with the owner's explicit go-ahead, following `docs/DEPLOY.md`.
- [ ] **Step 5: Owner reconnects Instagram** on one channel (the owner logs in and consents — never an agent). A Haiku browser agent (claude-in-chrome, new tab) then only verifies: the card shows the handle and no reconnect note.
- [ ] **Step 6: Make a fresh reel on that channel** — it must be assembled *after* the reconnect (older reels have no `final_ig_key` and will correctly go out with the bed, which looks like a failure but isn't).
- [ ] **Step 7: Owner approves the live post explicitly**, then it is published. The Haiku browser agent verifies: the post page shows "Instagram song: …"; `posts.ig_music->>'picked_by'` is `decisions` (a read-only query; `rule` means the Decisions call failed — check the worker log); the reel's permalink shows the song. GIF named `ig_trending_music_check.gif`.
- [ ] **Step 8: Update memory** (`ig-trending-music.md`, `build-progress.md`) with the live result.
