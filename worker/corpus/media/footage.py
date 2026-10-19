"""Footage → a finished 1080x1920 shot at 24 fps, ready for build_segment.

Three kinds of shot are made here instead of on the GPU:

  clip    a window of a real video. Landscape (or square) footage is "blur-padded":
          the frame sits whole in the middle over a blurred, darkened copy of itself
          filling the screen; near-vertical footage simply fills it (cover). A window
          shorter than the shot is lengthened from the video where it can be, and its
          last frame held otherwise. The clip's own sound comes along (keep or duck
          — build_segment sets the level), or none at all (mute).
  image   a picture with a slow Ken Burns move (zooming in on even shots, out on odd
          ones, so consecutive pictures don't all move the same way), composed the
          same way; no sound.
  stock   a Pexels video, treated as a muted clip.
  plain   the format's background colour as a slowly drifting gradient with a
          little grain (no banding), for text templates; no sound.
  chart   a chart drawn as a picture (media/slides.draw_chart: bar, big stat,
          comparison or line), then given a gentle zoom.

A shot may punch in on a region (`focus`: a screen recording's button, a
speaker's face) and a clip may play a long window sped up (`timelapse`). A shot
for a split screen is made at half height (1080x960) so its credit stays on it.

Every frame of third-party footage carries its credit ("u/x on r/videos", "Video by
Y on Pexels") in a small box at the top. Text goes to ffmpeg through a file
(drawtext textfile=, expansion off), so a credit can hold any character.
Everything runs on local files with relative paths from a work directory: the
filter syntax mangles Windows drive letters.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

W, H, FPS, RATE = 1080, 1920, 24, 48000
FONT = Path(__file__).parent / "fonts" / "Montserrat-Bold.ttf"
CREDIT_SIZE = 34
# Wider than 3:4 → blur-pad; anything narrower fills the frame.
COVER_MAX_ASPECT = 0.75
KEN_BURNS_ZOOM = 0.12


class FootageError(RuntimeError):
    pass


@dataclass
class Info:
    w: int
    h: int
    seconds: float
    has_audio: bool


def info(path: Path) -> Info:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise FootageError(f"ffprobe: {r.stderr.strip()[-300:]}")
    data = json.loads(r.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return Info(int(v.get("width") or 0), int(v.get("height") or 0),
                float((data.get("format") or {}).get("duration") or 0),
                any(s.get("codec_type") == "audio" for s in data.get("streams", [])))


def _ff(args: list[str], cwd: Path) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-protocol_whitelist", "file,pipe", *args],
                       cwd=cwd, capture_output=True, text=True, errors="replace", timeout=900)
    if r.returncode != 0:
        tail = " | ".join(ln.strip() for ln in r.stderr.strip().splitlines()[-4:])
        raise FootageError(f"ffmpeg: {tail or f'exit {r.returncode}'}")


def inner_frame(src: Path, samples: int = 4) -> dict | None:
    """The phone video inside a broadcaster's widescreen frame: a sharp, roughly 9:16
    picture between blurred copies of itself (how the BBC and many others carry a
    bystander's vertical clip). As a focus box (fractions), or None when the whole
    frame is the picture. Live: the BBC's Limoges clip filled a quarter of the reel."""
    from PIL import Image, ImageFilter

    i = info(src)
    if not i.w or not i.h or i.w <= i.h:
        return None
    work = src.parent
    cols = [0.0] * 160
    for k in range(samples):
        at = (i.seconds or 1) * (k + 1) / (samples + 1)
        frame = work / f"_inner{k}.png"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
                            "-vf", "scale=160:90,format=gray", str(frame)], capture_output=True, timeout=60)
        if r.returncode != 0 or not frame.exists():
            continue
        edges = Image.open(frame).filter(ImageFilter.FIND_EDGES)
        px = edges.load()
        for x in range(1, 159):
            cols[x] += sum(px[x, y] for y in range(10, 80))      # skip logos in the top and bottom strips
        frame.unlink(missing_ok=True)
    peak = max(cols)
    if peak <= 0:
        return None
    sharp = [x for x in range(160) if cols[x] >= 0.35 * peak]
    left, right = min(sharp), max(sharp)
    inner = (right - left + 1) / 160
    side = (sum(cols[:left]) + sum(cols[right + 1:])) / max(1, 160 - (right - left + 1))
    middle = sum(cols[left:right + 1]) / (right - left + 1)
    portrait = (i.h * 9 / 16) / i.w                    # the share of the width a 9:16 picture takes
    if not (0.6 * portrait <= inner <= 1.6 * portrait) or side > 0.3 * middle or abs((left + right) / 2 - 80) > 16:
        return None
    w = min(1.0, portrait)                             # crop exactly 9:16, centred on the sharp part
    x = max(0.0, min(1.0 - w, (left + right + 1) / 2 / 160 - w / 2))
    return {"x": round(x, 4), "y": 0.0, "w": round(w, 4), "h": 1.0}


def choose_layout(w: int, h: int) -> str:
    return "cover" if h and w / h <= COVER_MAX_ASPECT else "blur_pad"


def _layout(layout: str, inp: str, out: str, w: int = W, h: int = H) -> str:
    """A filtergraph fragment from [inp] to [out] filling a w×h frame."""
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}"
    if layout == "cover":
        return f"[{inp}]{cover},setsar=1[{out}]"
    return (f"[{inp}]split=2[{out}_a][{out}_b];"
            f"[{out}_a]scale={w // 8}:{h // 8}:force_original_aspect_ratio=increase,crop={w // 8}:{h // 8},"
            f"boxblur=6:2,scale={w}:{h},eq=brightness=-0.12:saturation=0.85[{out}_bg];"
            f"[{out}_b]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos[{out}_fg];"
            f"[{out}_bg][{out}_fg]overlay=(W-w)/2:(H-h)/2,setsar=1[{out}]")


def _credit(work: Path, credit: str | None, inp: str, out: str) -> str:
    """[inp] → [out] with the credit drawn at the top (a plain copy without one)."""
    if not credit:
        return f"[{inp}]null[{out}]"
    (work / "credit.txt").write_text(credit.strip()[:120], encoding="utf-8")
    if not (work / "credit.ttf").exists():
        shutil.copyfile(FONT, work / "credit.ttf")
    return (f"[{inp}]drawtext=fontfile=credit.ttf:textfile=credit.txt:expansion=none:fontsize={CREDIT_SIZE}:"
            f"fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=14:x=40:y=110[{out}]")


def _encode(frames: int) -> list[str]:
    return ["-frames:v", str(frames), "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def window(start: float, end: float, seconds: float, duration: float) -> tuple[float, float, float]:
    """(start, length to read, seconds of last frame to hold) for a shot of `seconds`.

    A short window grows forward through the video first, then backward; whatever
    the video can't supply is a held last frame."""
    duration = duration or max(end, start + seconds)
    start = min(max(0.0, start), max(0.0, duration - 0.1))
    end = min(duration, end) if end > start else min(duration, start + seconds)
    if end - start < seconds:
        end = min(duration, start + seconds)
        start = max(0.0, end - seconds)
    length = min(end - start, seconds)
    return start, length, max(0.0, seconds - length)


def _focus(focus: dict | None, inp: str, out: str) -> tuple[str, float, float]:
    """[inp] cropped to a focus box (fractions of the frame), and the share of the
    width and height kept; a plain copy without one."""
    if not focus or float(focus.get("w") or 0) <= 0 or float(focus.get("h") or 0) <= 0:
        return f"[{inp}]null[{out}]", 1.0, 1.0
    x, y = max(0.0, float(focus["x"])), max(0.0, float(focus["y"]))
    w, h = min(1.0 - x, float(focus["w"])), min(1.0 - y, float(focus["h"]))
    return (f"[{inp}]crop=trunc(iw*{w:.4f}/2)*2:trunc(ih*{h:.4f}/2)*2:trunc(iw*{x:.4f}):trunc(ih*{y:.4f})[{out}]",
            w, h)


def compose_clip(src: Path, out: Path, *, seconds: float, start: float = 0.0, end: float = 0.0,
                 layout: str | None = None, audio: str = "duck", credit: str | None = None,
                 focus: dict | None = None, timelapse: bool = False, size: tuple[int, int] = (W, H)) -> dict:
    """A video file → the finished shot `out` (exactly round(seconds*24) frames).
    `timelapse`: the whole window [start, end] plays sped up to fit, without sound."""
    work = out.parent
    i = info(src)
    frames = max(9, round(seconds * FPS))
    seconds = frames / FPS
    crop, fw, fh = _focus(focus, "0:v", "f")
    layout = layout or choose_layout(round(i.w * fw), round(i.h * fh))
    speed = 1.0
    if timelapse and end > start and end - start > seconds * 1.2:
        at = max(0.0, start)
        length = min(end, i.seconds or end) - at
        speed, hold = max(1.0, length / seconds), 0.0
    else:
        at, length, hold = window(start, end or start + seconds, seconds, i.seconds)
    graph = (crop + ";" + (f"[f]setpts=PTS/{speed:.4f}[g];" if speed > 1 else "")
             + _layout(layout, "g" if speed > 1 else "f", "framed", *size) + ";"
             + f"[framed]fps={FPS},tpad=stop_mode=clone:stop_duration={hold + 1:.3f}[held];"
             + _credit(work, credit, "held", "v"))
    args = ["-ss", f"{at:.3f}", "-t", f"{length:.3f}", "-i", str(src.resolve()), "-filter_complex", graph,
            "-map", "[v]"]
    sound = audio != "mute" and i.has_audio and speed == 1.0
    if sound:
        args += ["-map", "0:a:0", "-af", f"aresample={RATE},apad", "-t", f"{seconds:.3f}",
                 "-c:a", "aac", "-b:a", "160k", "-ar", str(RATE), "-ac", "2"]
    else:
        args += ["-an"]
    _ff(args + _encode(frames) + [out.name], cwd=work)
    return {"frames": frames, "layout": layout, "window": [round(at, 2), round(at + length, 2)],
            "held_s": round(hold, 2), "sound": sound, **({"speed": round(speed, 2)} if speed > 1 else {}),
            **({"focus": focus} if fw < 1 or fh < 1 else {})}


def chart_still(chart: dict, out: Path, look=None, size: tuple[int, int] = (W, H)) -> Path:
    """A chart as a picture the size of the shot: drawn like a slide's chart (bar,
    big stat, comparison or line), on the format's background, clear of where the
    captions sit (around 72% of the height)."""
    from PIL import Image

    from .. import templates
    from . import slides

    look = look or templates.look("animated_infographic")
    w, h = size
    img = Image.new("RGB", (w, h), slides._rgb(look.background_color))
    box = slides.Box(60, 260, w - 120, int(h * 0.62) - 260) if h > 1200 else slides.Box(40, 40, w - 80, h - 80)
    slides.draw_chart(img, box, chart, look)
    img.save(out)
    return out


def plain(out: Path, *, seconds: float, look=None, size: tuple[int, int] = (W, H)) -> dict:
    """The format's background colour as a slowly drifting two-tone gradient with
    fine grain, `seconds` long (exact frames), silent."""
    from .. import templates

    look = look or templates.look("kinetic_typography")
    frames = max(9, round(seconds * FPS))
    base = look.background_color.lstrip("#")
    r, g, b = (int(base[k:k + 2], 16) for k in (0, 2, 4))
    lift = "{:02X}{:02X}{:02X}".format(min(255, r + 34), min(255, g + 30), min(255, b + 46))
    w, h = size
    src = (f"gradients=s={w}x{h}:r={FPS}:c0=0x{base}:c1=0x{lift}:x0=0:y0=0:x1={w}:y1={h}:nb_colors=2:"
           f"speed=0.004:d={frames / FPS + 1:.3f}")
    _ff(["-f", "lavfi", "-i", src, "-vf", "noise=alls=5:allf=t,format=yuv420p,setsar=1", "-an"]
        + _encode(frames) + [out.name], cwd=out.parent)
    return {"frames": frames, "plain": look.background_color}


def ken_burns(src: Path, out: Path, *, seconds: float, idx: int = 0, credit: str | None = None,
              layout: str | None = None, zoom: float = KEN_BURNS_ZOOM, focus: dict | None = None,
              size: tuple[int, int] = (W, H)) -> dict:
    """A picture → the finished shot `out`: composed to the shot's shape, slowly zooming."""
    work = out.parent
    i = info(src)
    frames = max(9, round(seconds * FPS))
    crop, fw, fh = _focus(focus, "0:v", "f")
    layout = layout or choose_layout(round(i.w * fw), round(i.h * fh))
    w, h = size
    # Composed at twice the size, so the zoom's sub-pixel steps don't judder.
    still = work / "still.png"
    _ff(["-i", str(src.resolve()), "-filter_complex", crop + ";" + _layout(layout, "f", "s", 2 * w, 2 * h),
         "-map", "[s]", "-frames:v", "1", still.name], cwd=work)
    z = f"1+{zoom}*on/{frames}" if idx % 2 == 0 else f"{1 + zoom}-{zoom}*on/{frames}"
    graph = (f"[0:v]zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={FPS},"
             f"setsar=1[kb];" + _credit(work, credit, "kb", "v"))
    _ff(["-loop", "1", "-framerate", str(FPS), "-i", still.name, "-filter_complex", graph, "-map", "[v]", "-an"]
        + _encode(frames) + [out.name], cwd=work)
    still.unlink(missing_ok=True)
    return {"frames": frames, "layout": layout, "zoom": "in" if idx % 2 == 0 else "out"}
