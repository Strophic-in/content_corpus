"""python -m corpus.selftest — prove this image can make a reel before it goes live.

deploy/deploy.sh runs this in the freshly built worker image, before switching
over. It builds short segments the way production does (a narrated shot with
burned-in captions, a shot whose clip has no sound, a plain one, and footage
shots: a landscape clip blur-padded with its credit drawn on, a picture with a
Ken Burns move), joins them and checks the result — with hard cuts, and again
blended (transitions and a loop seam, as templates use) — and draws a slide. A
tool difference that breaks reels — like ffmpeg 5.1 failing the loudness step on
2026-10-11, after an 8-shot render had been paid for, or its xfade making one
frame more than newer versions (2026-10-17) — then stops the deploy instead of a
render.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .media import assemble as media
from .media import footage


def _clip(path: Path, seconds: float, sound: bool, size: str = "704x1280", rate: int = 24) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}"]
    if sound:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000", "-c:a", "aac", "-shortest"]
    cmd += ["-t", f"{seconds:.3f}", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def main() -> int:
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        voice = d / "voice.wav"                     # like Kokoro: 24 kHz mono
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=24000",
                        "-t", "1.6", "-ac", "1", str(voice)], check=True, capture_output=True)
        words = [(0.2, 0.6, "TINY"), (0.6, 1.0, "CLEANERS"), (1.0, 1.5, "EVERYWHERE.")]
        (d / "clip").mkdir()
        (d / "pic").mkdir()
        landscape = _clip(d / "land.mp4", 3.0, sound=True, size="1280x720", rate=30)
        picture = d / "pic.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1600x900",
                        "-frames:v", "1", str(picture)], check=True, capture_output=True)
        footage.compose_clip(landscape, d / "clip" / "shot.mp4", seconds=1.5, start=0.5, end=2.0,
                             credit="u/selftest on r/videos")
        footage.ken_burns(picture, d / "pic" / "shot.mp4", seconds=1.0, credit="Photo: selftest")
        shots = [
            (_clip(d / "a.mp4", 2.0, sound=True), voice, media.shifted(words, media.LEAD_IN)),
            (_clip(d / "b.mp4", 1.5, sound=False), None, None),
            (_clip(d / "c.mp4", 1.2, sound=True), None, None),
            (d / "clip" / "shot.mp4", voice, media.shifted(words, media.LEAD_IN)),
            (d / "pic" / "shot.mp4", None, None),
        ]
        segments, frames = [], 0
        for k, (clip, narration, w) in enumerate(shots):
            seg = (d / f"s{k}.mp4", d / f"s{k}.wav")
            label = "AI reconstruction" if k == 2 else None          # a generated shot's label, drawn on
            frames += media.build_segment(clip, *seg, narration=narration, words=w, label=label)["frames"]
            segments.append(seg)
        # A short MP3 bed, looped under the reel and ducked by its sound (as Freesound tracks are).
        track = d / "music.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=44100",
                        "-t", "2", "-c:a", "libmp3lame", str(track)], check=True, capture_output=True)
        info = media.join_segments(segments, d / "reel.mp4", music=track)
        if info["join"] != "copy":
            print(f"selftest FAILED: the fast join did not work here (fell back to {info['join']})")
            return 1
        # Templates: on-screen text and a split screen, blended joins, a loop seam, a slide.
        from . import looks, templates
        from .media import slides

        look = templates.look("ranked_countdown")
        tseg = (d / "t.mp4", d / "t.wav")
        media.build_segment(shots[0][0], *tseg, words=media.shifted(words, media.LEAD_IN), look=look,
                            extras={"label": "#2", "text": "A headline here", "layout": "split"},
                            grade=looks.get("black_and_white_archival").grade)     # a video look's colour grade
        blended = media.join_segments([tseg, *segments[1:3]], d / "blend.mp4", transitions=["", "whip", "fade"])
        looped = media.join_segments(segments[:2], d / "loop.mp4", transitions=["", "crossfade"], loop=True)
        slides.render({"heading": "Five things", "body": "A body line.", "visual": {"source": "none"}}, 1, 5,
                      layout="educational", look=templates.look("educational_carousel"), out=d / "slide.jpg")
        print(f"selftest ok: blended joins of {blended['seconds']}s and {looped['seconds']}s (loop), a slide")
        print(f"selftest ok: {len(segments)} segments, {frames} frames joined into a "
              f"{info['seconds']}s reel in {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - the message is the point
        print(f"selftest FAILED: {type(e).__name__}: {e}")
        sys.exit(1)
