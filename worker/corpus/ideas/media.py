"""Card media: a Reddit video or a picture, fetched safely and made small.

Previews are for the owner's phone, not for the reel: ≤480p video (with sound,
at most PREVIEW_SECONDS long) or an image at most 1080 px, plus a poster frame.
The full-quality source is fetched later, only if the owner chooses to use it.

Reddit videos are DASH: picture and sound are separate files listed in
v.redd.it/<id>/DASHPlaylist.mpd (CMAF_<height>.mp4 and CMAF_AUDIO_<kbps>.mp4, or
DASH_* on older posts). Both are downloaded through net (public hosts only,
size-capped) and joined by ffmpeg working on local files only
(-protocol_whitelist file), with +faststart so the browser can start playing
before the whole file has arrived.
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .. import net
from . import sites

PREVIEW_HEIGHT = 480
PREVIEW_SECONDS = 90
VIDEO_PART_BYTES = 40_000_000
AUDIO_PART_BYTES = 8_000_000
IMAGE_BYTES = 15_000_000
PAGE_BYTES = 2_000_000
PREVIEW_MAX_BYTES = 12_000_000


class MediaError(Exception):
    pass


@dataclass
class Probe:
    w: int
    h: int
    seconds: float
    vcodec: str
    has_audio: bool


def _ff(args: list[str], cwd: Path | None = None) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-protocol_whitelist", "file,pipe", *args],
                       cwd=cwd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise MediaError(f"ffmpeg: {r.stderr.strip()[-400:]}")


def probe(path: Path) -> Probe:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise MediaError(f"ffprobe: {r.stderr.strip()[-300:]}")
    info = json.loads(r.stdout)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    return Probe(int(v.get("width") or 0), int(v.get("height") or 0),
                 float((info.get("format") or {}).get("duration") or 0), v.get("codec_name", ""),
                 any(s.get("codec_type") == "audio" for s in info.get("streams", [])))


def vreddit_id(link: str) -> str | None:
    m = re.search(r"v\.redd\.it/([A-Za-z0-9]+)", link)
    return m.group(1) if m else None


def dash_parts(client: httpx.Client, vid: str) -> tuple[str, str | None]:
    """(video part URL ≤ PREVIEW_HEIGHT, audio part URL or None) from the playlist."""
    base = f"https://v.redd.it/{vid}/"
    body = net.get(client, base + "DASHPlaylist.mpd", max_bytes=1_000_000).content
    root = ET.fromstring(body)
    videos, audios = [], []
    for aset in root.iter():
        if not aset.tag.endswith("AdaptationSet"):
            continue
        set_kind = (aset.get("contentType") or aset.get("mimeType") or "").lower()
        for rep in aset:
            if not rep.tag.endswith("Representation"):
                continue
            url_el = next((e for e in rep.iter() if e.tag.endswith("BaseURL") and e.text), None)
            if url_el is None:
                continue
            url = urljoin(base, url_el.text.strip())
            kind = (rep.get("mimeType") or set_kind).lower()
            if "audio" in kind or "AUDIO" in url:
                audios.append((int(rep.get("bandwidth") or 0), url))
            else:
                m = re.search(r"_(\d+)\.mp4", url)
                height = int(rep.get("height") or (m.group(1) if m else 0))
                videos.append((height, url))
    if not videos:
        raise MediaError("the video's playlist lists no picture")
    fitting = [v for v in videos if v[0] <= PREVIEW_HEIGHT]
    video = max(fitting) if fitting else min(videos)
    audio = max(audios)[1] if audios else None
    return video[1], audio


def reddit_video(client: httpx.Client, link: str, work: Path) -> Path:
    """A playable preview MP4 of a v.redd.it post."""
    vid = vreddit_id(link)
    if not vid:
        raise MediaError(f"not a Reddit video: {link[:80]}")
    v_url, a_url = dash_parts(client, vid)
    v = net.download(client, v_url, work / "v.mp4", max_bytes=VIDEO_PART_BYTES, accept=("video/", "application/"))
    a = None
    if a_url:
        try:
            a = net.download(client, a_url, work / "a.mp4", max_bytes=AUDIO_PART_BYTES,
                             accept=("audio/", "video/", "application/"))
        except Exception:  # noqa: BLE001 - many Reddit videos have no sound at all
            a = None
    out = work / "preview.mp4"
    p = probe(v)
    vcodec = ["-c:v", "copy"] if p.vcodec == "h264" else \
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p"]
    args = ["-i", v.name] + (["-i", a.name] if a else []) + ["-t", str(PREVIEW_SECONDS), "-map", "0:v:0"]
    args += (["-map", "1:a:0", "-c:a", "aac", "-b:a", "96k"] if a else []) + vcodec
    _ff(args + ["-movflags", "+faststart", out.name], cwd=work)
    if out.stat().st_size > PREVIEW_MAX_BYTES:          # too big for a card: squeeze it
        small = work / "preview_small.mp4"
        _ff(["-i", out.name, "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", small.name], cwd=work)
        out = small
    return out


def poster(video: Path, out: Path) -> Path:
    at = min(1.0, max(0.0, probe(video).seconds / 3))
    _ff(["-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale='min(720,iw)':-2", "-q:v", "4",
         str(out)])
    return out


def contact_sheet(video: Path, out: Path, tiles: int = 3) -> Path:
    """tiles×tiles frames spread over the video, in one image (one vision call)."""
    seconds = max(probe(video).seconds, 1.0)
    rate = tiles * tiles / seconds
    _ff(["-i", str(video), "-vf", f"fps={rate:.4f},scale=320:-2,tile={tiles}x{tiles}", "-frames:v", "1",
         "-q:v", "4", str(out)])
    return out


def image_preview(src: Path, out: Path, max_side: int = 1080) -> Path:
    _ff(["-i", str(src), "-frames:v", "1", "-vf",
         f"scale='min({max_side},iw)':'min({max_side},ih)':force_original_aspect_ratio=decrease",
         "-q:v", "4", str(out)])
    return out


def download_image(client: httpx.Client, url: str, dest: Path) -> Path:
    return net.download(client, url, dest, max_bytes=IMAGE_BYTES, accept=("image/",),
                        headers={"User-Agent": net.BROWSER_UA})


def page_image(client: httpx.Client, url: str) -> str | None:
    """An article's og:image (its own lead picture), if it declares one."""
    try:
        page = net.get(client, url, max_bytes=PAGE_BYTES, accept=("text/html",),
                       headers={"User-Agent": net.BROWSER_UA})
    except Exception:  # noqa: BLE001 - no picture is fine
        return None
    meta = sites.page_links(page.content.decode("utf-8", "replace"), page.url).meta
    return meta.get("og:image:secure_url") or meta.get("og:image") or meta.get("twitter:image")
