"""Card media: a post's video or picture, fetched safely and made small.

Previews are for the owner's phone, not for the reel: ≤480p video (with sound,
at most PREVIEW_SECONDS long) or an image at most 1080 px, plus a poster frame.
The full-quality source is fetched later, only if the owner chooses to use it.

Reddit videos are DASH: picture and sound are separate files listed in
v.redd.it/<id>/DASHPlaylist.mpd (CMAF_<height>.mp4 and CMAF_AUDIO_<kbps>.mp4, or
DASH_* on older posts). Both are downloaded through net (public hosts only,
size-capped) and joined by ffmpeg working on local files only
(-protocol_whitelist file), with +faststart so the browser can start playing
before the whole file has arrived.

Mastodon and Lemmy videos are plain MP4 files (direct_video). Bluesky's are HLS:
a master playlist lists renditions, each a playlist of short .ts segments
(hls_video). The smallest rendition that is at least preview size is read, its
segments downloaded one by one through net up to PREVIEW_SECONDS, and joined
locally — ffmpeg never fetches a playlist itself.

The same readers fetch a post's footage at FULL quality (≤1080p short side, up
to three minutes) when the owner chose to use it in a reel (fetch_asset).
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


@dataclass(frozen=True)
class Quality:
    side: int                  # the short side, at most
    seconds: int               # read at most this much
    part_bytes: int            # one download, at most
    crf: int
    max_bytes: int | None      # squeeze the result below this (cards only)


PREVIEW = Quality(PREVIEW_HEIGHT, PREVIEW_SECONDS, VIDEO_PART_BYTES, 28, PREVIEW_MAX_BYTES)
FULL = Quality(1080, 180, 150_000_000, 20, None)


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


def dash_parts(client: httpx.Client, vid: str, max_height: int = PREVIEW_HEIGHT) -> tuple[str, str | None]:
    """(video part URL ≤ max_height, audio part URL or None) from the playlist."""
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
    fitting = [v for v in videos if v[0] <= max_height]
    video = max(fitting) if fitting else min(videos)
    audio = max(audios)[1] if audios else None
    return video[1], audio


def reddit_video(client: httpx.Client, link: str, work: Path, q: Quality = PREVIEW) -> Path:
    """A playable MP4 of a v.redd.it post (a card preview, or FULL for a reel)."""
    vid = vreddit_id(link)
    if not vid:
        raise MediaError(f"not a Reddit video: {link[:80]}")
    v_url, a_url = dash_parts(client, vid, q.side)
    v = net.download(client, v_url, work / "v.mp4", max_bytes=q.part_bytes, accept=("video/", "application/"))
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
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(q.crf), "-pix_fmt", "yuv420p"]
    args = ["-i", v.name] + (["-i", a.name] if a else []) + ["-t", str(q.seconds), "-map", "0:v:0"]
    args += (["-map", "1:a:0", "-c:a", "aac", "-b:a", "96k" if q.max_bytes else "160k"] if a else []) + vcodec
    _ff(args + ["-movflags", "+faststart", out.name], cwd=work)
    if q.max_bytes and out.stat().st_size > q.max_bytes:          # too big for a card: squeeze it
        small = work / "preview_small.mp4"
        _ff(["-i", out.name, "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", small.name], cwd=work)
        out = small
    return out


def _preview(src: Path, work: Path, q: Quality = PREVIEW) -> Path:
    """Any local video → an H.264 MP4 with its short side ≤ q.side, at most q.seconds long."""
    out = work / "preview.mp4"
    p = probe(src)
    scale = (f"scale='if(gt(iw,ih),-2,min({q.side},iw))':'if(gt(iw,ih),min({q.side},ih),-2)'")
    args = ["-i", src.name, "-t", str(q.seconds), "-map", "0:v:0", "-vf", scale,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(q.crf), "-pix_fmt", "yuv420p"]
    args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k" if q.max_bytes else "160k"] if p.has_audio else ["-an"]
    _ff(args + ["-movflags", "+faststart", out.name], cwd=work)
    if q.max_bytes and out.stat().st_size > q.max_bytes:
        small = work / "preview_small.mp4"
        _ff(["-i", out.name, "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", small.name], cwd=work)
        out = small
    return out


def direct_video(client: httpx.Client, url: str, work: Path, q: Quality = PREVIEW) -> Path:
    """A post's MP4 (Mastodon, Lemmy) → a card preview (or FULL)."""
    src = net.download(client, url, work / "source.mp4", max_bytes=q.part_bytes,
                       accept=("video/", "application/octet-stream"))
    return _preview(src, work, q)


_STREAM_INF = re.compile(r"RESOLUTION=(\d+)x(\d+)")
HLS_TYPES = ("application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "audio/x-mpegurl",
             "text/plain", "application/octet-stream")


def _hls_rendition(master_url: str, text: str, max_side: int = PREVIEW_HEIGHT) -> str:
    """The rendition whose short side is the largest not above max_side (else the smallest)."""
    lines = [ln.strip() for ln in text.splitlines()]
    options = []
    for n, ln in enumerate(lines):
        if ln.startswith("#EXT-X-STREAM-INF"):
            m = _STREAM_INF.search(ln)
            nxt = next((x for x in lines[n + 1:] if x and not x.startswith("#")), None)
            if nxt:
                options.append((min(int(m.group(1)), int(m.group(2))) if m else 0, urljoin(master_url, nxt)))
    if not options:
        return master_url                        # already a media playlist
    fitting = [o for o in options if o[0] <= max_side]
    return (max(fitting) if fitting else min(options))[1]


def hls_video(client: httpx.Client, playlist_url: str, work: Path, q: Quality = PREVIEW) -> Path:
    """A Bluesky (HLS) video → a card preview (or FULL)."""
    master = net.get(client, playlist_url, max_bytes=200_000, accept=HLS_TYPES).content.decode("utf-8", "replace")
    media_url = _hls_rendition(playlist_url, master, q.side)
    text = master
    if media_url != playlist_url:
        text = net.get(client, media_url, max_bytes=500_000, accept=HLS_TYPES).content.decode("utf-8", "replace")
    if "#EXT-X-KEY" in text and "METHOD=NONE" not in text:
        raise MediaError("the stream is encrypted")
    parts: list[str] = []
    m = re.search(r'#EXT-X-MAP:URI="([^"]+)"', text)
    if m:
        parts.append(urljoin(media_url, m.group(1)))          # fMP4: the init segment comes first
    seconds = 0.0
    lines = [ln.strip() for ln in text.splitlines()]
    for n, ln in enumerate(lines):
        if ln.startswith("#EXTINF:"):
            nxt = next((x for x in lines[n + 1:] if x and not x.startswith("#")), None)
            if nxt:
                parts.append(urljoin(media_url, nxt))
                seconds += float(ln[8:].split(",")[0] or 0)
                if seconds >= q.seconds:
                    break
    if not parts:
        raise MediaError("the playlist lists no segments")
    joined, total = work / "joined.ts", 0
    with joined.open("wb") as out:
        for n, url in enumerate(parts):
            seg = net.download(client, url, work / f"seg{n}", max_bytes=q.part_bytes - total,
                               accept=("video/", "application/octet-stream", "binary/octet-stream"))
            total += seg.stat().st_size
            out.write(seg.read_bytes())
            seg.unlink()
    return _preview(joined, work, q)


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
                        headers={"User-Agent": net.user_agent(url)})


def page_image(client: httpx.Client, url: str) -> str | None:
    """An article's og:image (its own lead picture), if it declares one."""
    try:
        page = net.get(client, url, max_bytes=PAGE_BYTES, accept=("text/html",),
                       headers={"User-Agent": net.BROWSER_UA})
    except Exception:  # noqa: BLE001 - no picture is fine
        return None
    meta = sites.page_links(page.content.decode("utf-8", "replace"), page.url).meta
    return meta.get("og:image:secure_url") or meta.get("og:image") or meta.get("twitter:image")
