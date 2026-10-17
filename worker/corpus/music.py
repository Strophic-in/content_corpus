"""Background music: a CC0 track from Freesound, by the mood the script picked
(ported from TrendCaster's media/audio.py).

Only Creative Commons 0 sounds are searched, so a track needs no licence and no
attribution (it is credited anyway, as a courtesy). Each mood has a few curated,
multi-word instrumental searches — far better results than one adjective. A track
used in the owner's last RECENT reels is skipped. The preview MP3 (128 kbps) is
what the API serves to a token; it is plenty for a bed played under a voice.
Previews are checked by their magic number, because CDNs answer with error pages
labelled audio/mpeg.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from . import net

SEARCH = "https://freesound.org/apiv2/search/text/"
RECENT = 20
# Its level where the picture is otherwise silent; under the narration or a shot's
# own sound it ducks itself (media/assemble.py DUCK).
GAIN = 0.30
TRACK_BYTES = 15_000_000

MOODS: dict[str, list[str]] = {
    "breaking-tension": ["tense cinematic pulse", "dark suspense underscore", "dramatic percussion loop",
                         "newsroom tension drone"],
    "somber": ["sad piano ambient", "melancholic strings instrumental", "somber cello pad",
               "emotional piano underscore"],
    "uplifting": ["uplifting piano background", "hopeful acoustic instrumental", "inspiring build underscore",
                  "bright motivational loop"],
    "energetic-hype": ["energetic electronic beat", "upbeat synthwave loop", "driving edm background",
                       "hype percussion groove"],
    "neutral-corporate": ["corporate background music", "minimal tech ambient", "clean electronic underscore",
                          "soft synth background loop"],
    "playful": ["quirky ukulele background", "playful pizzicato loop", "light comedy background",
                "fun upbeat whistle tune"],
}


@dataclass
class Track:
    id: int
    name: str
    author: str
    page: str
    path: Path

    @property
    def credit(self) -> str:
        return f"Music: “{self.name}” by {self.author} (Freesound, CC0)"


def is_audio(data: bytes) -> bool:
    if not data or len(data) < 2048:
        return False
    return (data[:3] == b"ID3" or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)
            or data[:4] in (b"OggS", b"fLaC", b"RIFF") or data[4:8] == b"ftyp")


def find(client: httpx.Client, api_key: str, mood: str, exclude: set[int], dest: Path,
         min_seconds: int = 20) -> Track | None:
    for query in MOODS.get(mood, []):
        r = client.get(SEARCH, headers={"Authorization": f"Token {api_key}"}, timeout=20, params={
            "query": query, "filter": f'license:"Creative Commons 0" duration:[{min_seconds} TO 300]',
            "sort": "rating_desc", "fields": "id,name,username,url,previews", "page_size": 15})
        if r.status_code in (401, 403):
            raise PermissionError("Freesound refused the API key — check it in Settings")
        if r.status_code != 200:
            continue
        for s in r.json().get("results") or []:
            url = (s.get("previews") or {}).get("preview-hq-mp3")
            if not url or s.get("id") in exclude:
                continue
            try:
                path = net.download(client, url, dest, max_bytes=TRACK_BYTES, accept=("audio/", "application/"))
            except Exception:  # noqa: BLE001 - next one
                continue
            if is_audio(path.read_bytes()):
                return Track(int(s["id"]), s.get("name") or "untitled", s.get("username") or "unknown",
                             s.get("url") or "", path)
    return None
