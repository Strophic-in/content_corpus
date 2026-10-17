"""Stock video from Pexels, for shots that show a setting or a subject in general.

Free with a Pexels API key (200 requests an hour, 20,000 a month), stored in the
owner's key vault as 'pexels_api_key'. A search asks for portrait clips; the pick
is the best-ranked clip at least as long as the shot that this reel hasn't used
yet, in the largest file that fits 1080x1920. If nothing matches, the query is
tried again with fewer words. Pexels asks for credit, so every stock shot is
credited on screen ("Video by … on Pexels") and in the description.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from . import net

SEARCH = "https://api.pexels.com/videos/search"
FILE_BYTES = 120_000_000


class NotFound(Exception):
    """No usable stock clip for the query."""


@dataclass
class Clip:
    id: int
    url: str            # the video file
    page: str           # its Pexels page
    author: str
    seconds: float
    w: int
    h: int

    @property
    def credit(self) -> str:
        return f"Video by {self.author} on Pexels"


def _queries(query: str) -> list[str]:
    words = query.split()
    out = [" ".join(words)]
    if len(words) > 2:
        out.append(" ".join(words[:2]))
    if len(words) > 1:
        out.append(words[-1] if len(words) == 2 else words[0])
    return list(dict.fromkeys(q for q in out if q))


def _best_file(video: dict) -> dict | None:
    files = [f for f in video.get("video_files") or []
             if (f.get("file_type") or "").startswith("video/mp4") and f.get("width") and f.get("height")
             and f["width"] <= 1080 and f["height"] <= 1920]
    portrait = [f for f in files if f["height"] >= f["width"]]
    return max(portrait or files, key=lambda f: f["width"] * f["height"], default=None)


def find(client: httpx.Client, api_key: str, query: str, seconds: float, exclude: set[int]) -> Clip:
    for q in _queries(query.strip()):
        r = client.get(SEARCH, params={"query": q, "orientation": "portrait", "size": "medium", "per_page": 30},
                       headers={"Authorization": api_key}, timeout=30)
        if r.status_code in (401, 403):
            raise PermissionError("Pexels refused the API key — check it in Settings")
        r.raise_for_status()
        videos = [v for v in r.json().get("videos") or [] if v.get("id") not in exclude]
        # Long enough first (in Pexels' own order), then the longest of the rest: a short
        # clip's last frame can be held, but less is better.
        ranked = sorted(videos, key=lambda v: (float(v.get("duration") or 0) < seconds,
                                               -float(v.get("duration") or 0)
                                               if float(v.get("duration") or 0) < seconds else 0))
        for v in ranked:
            f = _best_file(v)
            if f:
                return Clip(int(v["id"]), f["link"], v.get("url") or "", (v.get("user") or {}).get("name") or "Pexels",
                            float(v.get("duration") or 0), int(f["width"]), int(f["height"]))
    raise NotFound(f"no stock video found for \"{query}\"")


def download(client: httpx.Client, clip: Clip, dest: Path) -> Path:
    return net.download(client, clip.url, dest, max_bytes=FILE_BYTES, accept=("video/", "application/octet-stream"))
