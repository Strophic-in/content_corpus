"""python -m corpus.selftest — prove this image can make a reel before it goes live.

deploy/deploy.sh runs this in the freshly built worker image, before switching
over. It builds three short segments the way production does (a narrated shot
with burned-in captions, a shot whose clip has no sound, a plain one), joins them
and checks the result. A tool difference that breaks reels — like ffmpeg 5.1
failing the loudness step on 2026-10-11, after an 8-shot render had been paid
for — then stops the deploy instead of a render.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .media import assemble as media


def _clip(path: Path, seconds: float, sound: bool) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=704x1280:rate=24"]
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
        shots = [
            (_clip(d / "a.mp4", 2.0, sound=True), voice, media.shifted(words, media.LEAD_IN)),
            (_clip(d / "b.mp4", 1.5, sound=False), None, None),
            (_clip(d / "c.mp4", 1.2, sound=True), None, None),
        ]
        segments, frames = [], 0
        for k, (clip, narration, w) in enumerate(shots):
            seg = (d / f"s{k}.mp4", d / f"s{k}.wav")
            frames += media.build_segment(clip, *seg, narration=narration, words=w)["frames"]
            segments.append(seg)
        info = media.join_segments(segments, d / "reel.mp4")
        if info["join"] != "copy":
            print(f"selftest FAILED: the fast join did not work here (fell back to {info['join']})")
            return 1
        print(f"selftest ok: {len(segments)} segments, {frames} frames joined into a "
              f"{info['seconds']}s reel in {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - the message is the point
        print(f"selftest FAILED: {type(e).__name__}: {e}")
        sys.exit(1)
