"""The Instagram song for a reel: candidates from Instagram's own music library.

The owner's rules: a Hindi song by default; Gen-Z, meme and viral sounds are welcome;
a reel always gets a song. Instagram's trending list comes first (the sounds people
are actually using right now), then Hindi and meme searches, then the mood's own
searches. The Decisions API picker chooses among these (Task 4), and rule_pick
is the fallback when that call is unavailable.

Instagram only lets a Reel carry a song from its library, so these are the only
candidates. A song Instagram refuses later is dropped by the publisher, never the post.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from psycopg.types.json import Jsonb

from . import costs, db, vault
from .publish import instagram
from .script.llm import Usage

log = logging.getLogger("corpus.ig_music")

DECISIONS = "https://api.openai.com/v1/decisions"
MODEL = "gpt-6-luna"
INSTRUCTIONS = (
    "Pick the song that best suits this Instagram reel. Prefer Hindi songs. A song in another "
    "language is fine when it sounds great and suits the reel. Gen-Z, meme and viral sounds are "
    "good for light, funny or surprising stories. For death, disaster or tragedy pick the closest "
    "calm or emotional song, never a comic or party one. When songs fit equally, prefer the more "
    "trending one."
)

CAP = 40                 # candidates handed to the picker
TRENDING_SLOTS = 15      # the no-query list may fill at most this many, so searches always get room
RECENT = 20              # songs in the owner's last reels are skipped by the caller's exclude set
MOOD_SEARCHES: dict[str, list[str]] = {
    "breaking-tension": ["dramatic hindi bgm", "tense suspense beat"],
    "somber": ["sad hindi song", "emotional piano"],
    "uplifting": ["happy hindi song", "uplifting piano"],
    "energetic-hype": ["bollywood party", "hype beat"],
    "neutral-corporate": ["hindi lofi", "lofi chill"],
    "playful": ["fun hindi song", "playful ukulele"],
    "cinematic": ["filmi instrumental", "epic cinematic"],
    "curious": ["mysterious hindi", "mystery ambient"],
}
MEME_SEARCHES = ["viral meme song", "phonk"]
FALLBACK = "neutral-corporate"       # the mood an unknown or missing mood is treated as
HINDI_FIRST = ["hindi trending", "bollywood"]


@dataclass
class Track:
    audio_id: str
    title: str
    artist: str
    duration_ms: int
    trending_rank: int | None   # 1-based position in the no-query list, None if not there
    found_by: str               # "trending" or the search text that found it

    @property
    def label(self) -> str:
        return f"{self.title} — {self.artist}"


def searches(mood: str | None) -> list[str]:
    """The search texts after trending, in the order they are asked."""
    hindi, english = MOOD_SEARCHES.get(mood or "", MOOD_SEARCHES[FALLBACK])
    return [*HINDI_FIRST, hindi, *MEME_SEARCHES, english]


def _audio(client: httpx.Client, *, graph: str, token: str, ig_user_id: str,
           search: str | None) -> list[dict] | None:
    """One ig_audio call: its audio list, or None when this request failed.
    An expired token raises instagram.AuthExpired, since every later call would fail too."""
    params = {"audio_type": "music", "user_id": ig_user_id, "access_token": token}
    if search is not None:
        params["search_query"] = search
    try:
        r = client.get(f"{graph}/ig_audio", params=params, timeout=20)
    except httpx.HTTPError:
        return None
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    if r.status_code == 401 or err.get("code") == 190:
        raise instagram.AuthExpired("Instagram access has expired or was removed")
    if r.status_code != 200 or not isinstance(body.get("audio"), list):
        return None
    return [x for x in body["audio"] if isinstance(x, dict) and x.get("audio_id") is not None]


def _track(x: dict, rank: int | None, found_by: str) -> Track:
    try:
        duration_ms = int(x.get("duration_in_ms") or 0)
    except (TypeError, ValueError):
        duration_ms = 0
    return Track(audio_id=str(x["audio_id"]), title=str(x.get("title") or ""),
                 artist=str(x.get("display_artist") or ""), duration_ms=duration_ms,
                 trending_rank=rank, found_by=found_by)


def candidates(client: httpx.Client, *, graph: str, token: str, ig_user_id: str,
               mood: str | None, exclude: set[str]) -> list[Track]:
    """Songs to pick from: the top of the trending list, then each search in order,
    de-duplicated by audio_id (the first sighting wins), at most CAP. Songs in `exclude`
    are skipped before they count toward TRENDING_SLOTS or CAP, so they never use up room.
    Returns [] when Instagram answers nothing at all."""
    out: dict[str, Track] = {}
    trending = _audio(client, graph=graph, token=token, ig_user_id=ig_user_id, search=None) or []
    trending_kept = 0
    for rank, x in enumerate(trending, start=1):
        if trending_kept >= TRENDING_SLOTS:
            break
        if str(x["audio_id"]) in exclude:
            continue
        t = _track(x, rank, "trending")
        if t.audio_id not in out:
            out[t.audio_id] = t
            trending_kept += 1
    for search in searches(mood):
        if len(out) >= CAP:
            break
        found = _audio(client, graph=graph, token=token, ig_user_id=ig_user_id, search=search) or []
        for x in found:
            if len(out) >= CAP:
                break
            t = _track(x, None, search)
            if t.audio_id not in out and t.audio_id not in exclude:
                out[t.audio_id] = t
    return list(out.values())


def rule_pick(tracks: list[Track], mood: str | None) -> Track:
    """The fallback pick without the picker: the first track the mood's searches found
    (Hindi search first), else the best trending rank, else the first track.
    `tracks` must not be empty."""
    for search in MOOD_SEARCHES.get(mood or "", MOOD_SEARCHES[FALLBACK]):
        for t in tracks:
            if t.found_by == search:
                return t
    ranked = [t for t in tracks if t.trending_rank is not None]
    if ranked:
        return min(ranked, key=lambda t: t.trending_rank)
    return tracks[0]


def volumes(narrated: bool) -> dict:
    """Mix levels for the reel's audio: a narrated reel keeps the song quiet under the voice."""
    if narrated:
        return {"audio_volume": 25, "video_volume": 100}
    return {"audio_volume": 100, "video_volume": 40}


def _reel_lines(reel: dict) -> str:
    return "\n".join([
        f"Title: {reel.get('title') or ''}",
        f"Hook: {reel.get('hook') or ''}",
        f"Category: {reel.get('category') or ''}",
        f"Mood: {reel.get('mood') or ''}",
        f"Narrated: {'yes' if reel.get('narrated') else 'no'}",
    ])


def _unique_labels(tracks: list[Track]) -> list[str]:
    """Each track's label, made unique: a repeated label gets ' (2)', ' (3)'…"""
    used: set[str] = set()
    out: list[str] = []
    for t in tracks:
        label, n = t.label, 1
        while label in used:
            n += 1
            label = f"{t.label} ({n})"
        used.add(label)
        out.append(label)
    return out


def _usage(data: dict) -> Usage | None:
    u = data.get("usage")
    if not isinstance(u, dict):
        return None
    details = u.get("input_tokens_details") if isinstance(u.get("input_tokens_details"), dict) else {}
    try:
        return Usage(model=MODEL, input_tokens=int(u.get("input_tokens") or 0), output_tokens=0,
                     cached_input_tokens=int(details.get("cached_tokens") or 0))
    except (TypeError, ValueError):
        log.warning("Decisions usage unreadable; recording none")
        return None


def decide(client: httpx.Client | None, api_key: str | None, reel: dict, tracks: list[Track]
           ) -> tuple[Track, float | None, Usage | None, str]:
    """The reel's song, asked of OpenAI's Decisions API as one choice question.
    Returns (track, confidence, usage, picked_by): "only" when there is one song (no call),
    "decisions" when the model chose, "rule" when rule_pick stands in (no key, a failed
    call, a refusal, or a choice that is not offered). `usage` is set whenever a reply carried one."""
    if len(tracks) == 1:
        return tracks[0], None, None, "only"
    if client is None:
        with httpx.Client() as c:
            return decide(c, api_key, reel, tracks)
    fallback = rule_pick(tracks, reel.get("mood"))
    if not api_key:
        return fallback, None, None, "rule"
    labels = _unique_labels(tracks)
    by_label = dict(zip(labels, tracks))
    choices = [{"value": label,
                "description": (f"trending #{t.trending_rank}" if t.trending_rank else "not in trending")
                + f"; found by: {t.found_by}"}
               for label, t in zip(labels, tracks)]
    body = {"model": MODEL,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": _reel_lines(reel)},
                {"type": "input_json", "data": {"songs": [
                    {"song": label, "artist": t.artist, "trending_rank": t.trending_rank,
                     "found_by": t.found_by, "seconds": round(t.duration_ms / 1000)}
                    for label, t in zip(labels, tracks)]}}]}],
            "questions": [{"type": "choice", "name": "song", "instructions": INSTRUCTIONS,
                           "choices": choices}]}
    try:
        r = client.post(DECISIONS, json=body, headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
    except httpx.HTTPError as e:
        log.warning("Decisions call failed, using the rule pick: %s", e)
        return fallback, None, None, "rule"
    if r.status_code != 200:
        log.warning("Decisions returned %s, using the rule pick: %s", r.status_code, r.text[:300])
        return fallback, None, None, "rule"
    try:
        data = r.json()
        if not isinstance(data, dict):
            raise ValueError("reply is not an object")
    except ValueError as e:
        log.warning("Decisions reply unreadable, using the rule pick: %s", e)
        return fallback, None, None, "rule"
    usage = _usage(data)
    try:
        answer = next(a for a in data.get("answers") or []
                      if isinstance(a, dict) and a.get("name") == "song")
        if answer.get("type") != "choice":
            log.warning("Decisions refused the song question, using the rule pick")
            return fallback, None, usage, "rule"
        track = by_label.get(answer.get("choice"))
        conf = answer.get("confidence")
        conf = float(conf) if conf is not None else None
    except (TypeError, ValueError, StopIteration, AttributeError) as e:
        log.warning("Decisions answer unreadable, using the rule pick: %s", e)
        return fallback, None, usage, "rule"
    if track is None:
        log.warning("Decisions chose %r, which was not offered; using the rule pick", answer.get("choice"))
        return fallback, None, usage, "rule"
    return track, conf, usage, "decisions"


def choose(client: httpx.Client, *, post: dict, acc: dict, token: str, job_id=None) -> dict | None:
    """The reel's song, saved on the post (posts.ig_music) and returned. A song Instagram
    refused stays refused (None: the reel goes out with the bed); a song already saved
    is reused as it is. None too when Instagram has no songs to offer."""
    saved = post.get("ig_music")
    if saved and "dropped" in saved:
        return None
    if saved and saved.get("audio_id"):
        return saved
    row = db.one("""select s.title, s.hook, s.music_mood, p.audio_source, c.name as category
                      from posts p
                      left join scripts s on s.id = p.approved_script_id
                      left join categories c on c.id = p.category_id
                     where p.id = %s""", (post["id"],))
    with db.conn() as c:
        recent = {r["audio_id"] for r in c.execute(
            """select ig_music->>'audio_id' as audio_id from posts
                where channel_id = %s and id <> %s and ig_music->>'audio_id' is not null
                order by created_at desc limit %s""", (post["channel_id"], post["id"], RECENT)).fetchall()}
    narrated = row["audio_source"] == "kokoro"
    reel = {"title": row["title"] or "", "hook": row["hook"] or "", "category": row["category"] or "",
            "mood": row["music_mood"] or "", "narrated": narrated}
    tracks = candidates(client, graph=instagram.host("unified"), token=token, ig_user_id=acc["external_id"],
                        mood=reel["mood"], exclude=recent)
    if not tracks:
        return None
    track, conf, usage, picked_by = decide(client, vault.secret(post["user_id"], "openai"), reel, tracks)
    if usage is not None:
        costs.record_llm(usage, user_id=post["user_id"], kind="music_pick", post_id=post["id"],
                         channel_id=post["channel_id"], job_id=job_id, note="Instagram song")
    out = {"audio_id": track.audio_id, "title": track.title, "artist": track.artist, "confidence": conf,
           "trending_rank": track.trending_rank, "found_by": track.found_by, "picked_by": picked_by,
           **volumes(narrated)}
    with db.conn() as c:
        c.execute("update posts set ig_music = %s where id = %s", (Jsonb(out), post["id"]))
    return out
