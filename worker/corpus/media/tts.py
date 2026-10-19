"""Narration with Kokoro (82M parameters, ONNX) on the CPU: one consistent voice
per channel, no GPU needed. The model files (~350 MB) are fetched once into the
models cache and checked by size; a truncated download is replaced, not used.
"""

from __future__ import annotations

import functools
import os
import urllib.request
from pathlib import Path

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
FILES = {"kokoro-v1.0.onnx": 325_532_387, "voices-v1.0.bin": 28_214_398}

# Offered in Settings. a* = American English, b* = British English.
VOICES = {
    "am_michael": "Michael — calm US male",
    "am_fenrir": "Fenrir — deeper US male",
    "am_onyx": "Onyx — low US male",
    "bm_george": "George — British documentary",
    "bm_lewis": "Lewis — British male",
    "af_heart": "Heart — warm US female",
    "af_bella": "Bella — bright US female",
    "bf_emma": "Emma — British female",
}


def models_dir() -> Path:
    return Path(os.environ.get("CORPUS_MODELS_DIR") or Path.home() / ".cache" / "content_corpus") / "kokoro"


def _ensure_files() -> Path:
    d = models_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name, size in FILES.items():
        path = d / name
        if path.exists() and path.stat().st_size == size:
            continue
        tmp = path.with_suffix(path.suffix + ".part")
        urllib.request.urlretrieve(f"{RELEASE}/{name}", tmp)
        if tmp.stat().st_size != size:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"Kokoro download of {name} came out the wrong size")
        tmp.replace(path)
    return d


@functools.lru_cache(maxsize=1)
def _kokoro():
    from kokoro_onnx import Kokoro

    d = _ensure_files()
    return Kokoro(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))


def speak(text: str, voice: str, speed: float, out: Path) -> float:
    """Write `text` as a WAV in `voice`; return its length in seconds."""
    import numpy as np
    import soundfile as sf

    lang = "hi" if voice.startswith("h") else "en-gb" if voice.startswith("b") else "en-us"
    audio, sr = _kokoro().create(text, voice=voice, speed=float(speed), lang=lang)
    audio = np.asarray(audio, dtype=np.float32)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, audio, sr)
    return len(audio) / sr
