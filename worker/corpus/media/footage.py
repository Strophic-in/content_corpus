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


def compose_clip(src: Path, out: Path, *, seconds: float, start: float = 0.0, end: float = 0.0,
                 layout: str | None = None, audio: str = "duck", credit: str | None = None) -> dict:
    """A video file → the finished shot `out` (exactly round(seconds*24) frames)."""
    work = out.parent
    i = info(src)
    frames = max(9, round(seconds * FPS))
    seconds = frames / FPS
    layout = layout or choose_layout(i.w, i.h)
    at, length, hold = window(start, end or start + seconds, seconds, i.seconds)
    graph = (_layout(layout, "0:v", "framed") + ";"
             + f"[framed]fps={FPS},tpad=stop_mode=clone:stop_duration={hold + 1:.3f}[held];"
             + _credit(work, credit, "held", "v"))
    args = ["-ss", f"{at:.3f}", "-t", f"{length:.3f}", "-i", str(src.resolve()), "-filter_complex", graph,
            "-map", "[v]"]
    sound = audio != "mute" and i.has_audio
    if sound:
        args += ["-map", "0:a:0", "-af", f"aresample={RATE},apad", "-t", f"{seconds:.3f}",
                 "-c:a", "aac", "-b:a", "160k", "-ar", str(RATE), "-ac", "2"]
    else:
        args += ["-an"]
    _ff(args + _encode(frames) + [out.name], cwd=work)
    return {"frames": frames, "layout": layout, "window": [round(at, 2), round(at + length, 2)],
            "held_s": round(hold, 2), "sound": sound}


def _num(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:,.1f}"


def chart_still(chart: dict, out: Path) -> Path:
    """A bar chart as a 1080x1920 picture: the title at the top, one horizontal bar
    per label, longest bar = largest value, each value printed at its bar's end."""
    work = out.parent
    shutil.copyfile(FONT, work / "chart.ttf")
    labels, values = list(chart["labels"])[:6], [float(v) for v in chart["values"]][:6]
    top = max(values) or 1.0
    unit = (chart.get("unit") or "").strip()
    (work / "title.txt").write_text(chart["title"].strip()[:80], encoding="utf-8")
    graph = [f"drawtext=fontfile=chart.ttf:textfile=title.txt:expansion=none:fontsize=60:fontcolor=white:"
             f"x=(w-text_w)/2:y=300"]
    # Rows end above y≈1300: the captions sit around 72% of the height.
    row, y0, x0, full = 800 // max(1, len(labels)), 480, 90, 820
    for k, (label, value) in enumerate(zip(labels, values)):
        y = y0 + k * row
        bar = max(12, round(full * value / top))
        (work / f"l{k}.txt").write_text(str(label).strip()[:40], encoding="utf-8")
        (work / f"v{k}.txt").write_text(f"{_num(value)}{(' ' + unit) if unit and unit != '%' else unit}",
                                        encoding="utf-8")
        graph += [f"drawtext=fontfile=chart.ttf:textfile=l{k}.txt:expansion=none:fontsize=42:fontcolor=0xcbd5e1:"
                  f"x={x0}:y={y}",
                  f"drawbox=x={x0}:y={y + 60}:w={bar}:h={min(90, row - 90)}:color=0xef4444@1:t=fill",
                  f"drawtext=fontfile=chart.ttf:textfile=v{k}.txt:expansion=none:fontsize=44:fontcolor=white:"
                  f"x={min(x0 + bar + 20, W - 260)}:y={y + 60 + max(0, (min(90, row - 90) - 44) // 2)}"]
    _ff(["-f", "lavfi", "-i", f"color=c=0x0f172a:s={W}x{H}", "-vf", ",".join(graph), "-frames:v", "1", out.name],
        cwd=work)
    return out


def ken_burns(src: Path, out: Path, *, seconds: float, idx: int = 0, credit: str | None = None,
              layout: str | None = None, zoom: float = KEN_BURNS_ZOOM) -> dict:
    """A picture → the finished shot `out`: composed to 9:16, slowly zooming."""
    work = out.parent
    i = info(src)
    frames = max(9, round(seconds * FPS))
    layout = layout or choose_layout(i.w, i.h)
    # Composed at twice the size, so the zoom's sub-pixel steps don't judder.
    still = work / "still.png"
    _ff(["-i", str(src.resolve()), "-filter_complex", _layout(layout, "0:v", "s", 2 * W, 2 * H), "-map", "[s]",
         "-frames:v", "1", still.name], cwd=work)
    z = f"1+{zoom}*on/{frames}" if idx % 2 == 0 else f"{1 + zoom}-{zoom}*on/{frames}"
    graph = (f"[0:v]zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
             f"setsar=1[kb];" + _credit(work, credit, "kb", "v"))
    _ff(["-loop", "1", "-framerate", str(FPS), "-i", still.name, "-filter_complex", graph, "-map", "[v]", "-an"]
        + _encode(frames) + [out.name], cwd=work)
    still.unlink(missing_ok=True)
    return {"frames": frames, "layout": layout, "zoom": "in" if idx % 2 == 0 else "out"}
