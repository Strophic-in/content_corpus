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

from dataclasses import dataclass

import httpx

from .publish import instagram

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
    return Track(audio_id=str(x["audio_id"]), title=str(x.get("title") or ""),
                 artist=str(x.get("display_artist") or ""), duration_ms=int(x.get("duration_in_ms") or 0),
                 trending_rank=rank, found_by=found_by)


def candidates(client: httpx.Client, *, graph: str, token: str, ig_user_id: str,
               mood: str | None, exclude: set[str]) -> list[Track]:
    """Songs to pick from: the top of the trending list, then each search in order,
    de-duplicated by audio_id (the first sighting wins), minus `exclude`, at most CAP.
    Returns [] when Instagram answers nothing at all."""
    out: dict[str, Track] = {}
    trending = _audio(client, graph=graph, token=token, ig_user_id=ig_user_id, search=None) or []
    for rank, x in enumerate(trending[:TRENDING_SLOTS], start=1):
        t = _track(x, rank, "trending")
        out.setdefault(t.audio_id, t)
    for search in searches(mood):
        if len(out) >= CAP:
            break
        found = _audio(client, graph=graph, token=token, ig_user_id=ig_user_id, search=search) or []
        for x in found:
            t = _track(x, None, search)
            out.setdefault(t.audio_id, t)
    kept = [t for t in out.values() if t.audio_id not in exclude]
    return kept[:CAP]


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
