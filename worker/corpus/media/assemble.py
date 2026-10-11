"""Shots + narration → the finished 1080x1920 reel with burned-in karaoke captions.

Picture: hard cuts; each 704x1280 shot scaled to 1080 wide, centre-cropped to 1920.
Sound (narrated): the shots' own audio (effects, ambience) ducked under the voice;
narration line i starts LEAD_IN into shot i. Sound (characters speak): the shots'
audio as rendered. Either way the mix is normalised to -14 LUFS (YouTube's target).

Captions (narrated): the SCRIPT's words, timed by Whisper — ASR is trusted for
*when* a word is said, never *what* (it misheard "As" as "Bokas" in testing).
Captions (characters speak): Whisper's words, biased by the intended dialogue.
Each shot becomes a finished segment on its own (see build_segment), so the cpu
worker can finish shots while the GPU is still rendering the rest.
Groups never straddle a sentence or shot boundary. A group too wide for the frame
wraps onto a second line, measured with the bundled caption font.
"""

from __future__ import annotations

import difflib
import functools
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

LEAD_IN = 0.15
SFX_GAIN = 0.30

Words = list[tuple[float, float, str]]


@dataclass(frozen=True)
class CaptionStyle:
    font_family: str = "Montserrat"
    font_size_px: int = 84
    primary_color: str = "#FFFFFF"
    accent_color: str = "#FFE000"
    outline_px: int = 8
    shadow_px: int = 4
    position_y: float = 0.72
    words_per_group: int = 3
    active_scale: float = 1.18
    uppercase: bool = True


def probe_duration(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(p)],
                       capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


@functools.lru_cache(maxsize=1)
def _whisper():
    from faster_whisper import WhisperModel

    return WhisperModel("small", device="cpu", compute_type="int8")


def whisper_words(audio: Path, hint: str) -> Words:
    segs, _ = _whisper().transcribe(str(audio), language="en", word_timestamps=True,
                               initial_prompt=hint or None, beam_size=5)
    return [(w.start, w.end, w.word.strip()) for s in segs for w in s.words if w.word.strip()]


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


def align(script_words: list[str], heard: Words, total: float) -> list[tuple[float, float]]:
    """Timings for each script word: matched words take the heard timing,
    unmatched runs are spread evenly across the gap their neighbours leave."""
    times: list[tuple[float, float] | None] = [None] * len(script_words)
    sm = difflib.SequenceMatcher(a=[_norm(w) for w in script_words], b=[_norm(h[2]) for h in heard],
                                 autojunk=False)
    for a0, b0, n in sm.get_matching_blocks():
        for k in range(n):
            times[a0 + k] = (heard[b0 + k][0], heard[b0 + k][1])
    k = 0
    while k < len(times):
        if times[k] is not None:
            k += 1
            continue
        j = k
        while j < len(times) and times[j] is None:
            j += 1
        lo = times[k - 1][1] if k > 0 else 0.0
        hi = times[j][0] if j < len(times) else total
        step = max(0.05, (hi - lo) / (j - k))
        for m in range(k, j):
            times[m] = (lo + (m - k) * step, lo + (m - k + 1) * step)
        k = j
    return times  # type: ignore[return-value]


def _ass_color(hex_rgb: str) -> str:
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()   # ASS is &HAABBGGRR


def _ts(t: float) -> str:
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


SAFE_WIDTH = 1080 - 2 * 60   # the style's MarginL/MarginR
# Caption fonts ship with the worker (ffmpeg's ass filter gets fontsdir=), so the reel
# looks the same on every machine and line widths can be measured, not guessed.
FONTS_DIR = Path(__file__).parent / "fonts"
BUNDLED_FONTS = {"montserrat": "Montserrat-Bold.ttf"}


@dataclass(frozen=True)
class _Metrics:
    advance: dict[int, int]  # codepoint -> advance width, font units
    upem: int
    win_height: int          # usWinAscent + usWinDescent: what libass sizes Fontsize by
    fallback: int            # advance for a character the font lacks


@functools.lru_cache(maxsize=8)
def _metrics(family: str) -> _Metrics | None:
    name = BUNDLED_FONTS.get(family.lower())
    if not name:
        return None
    from fontTools.ttLib import TTFont

    f = TTFont(FONTS_DIR / name)
    hmtx = f["hmtx"]
    advance = {cp: hmtx[g][0] for cp, g in f.getBestCmap().items()}
    upem = f["head"].unitsPerEm
    return _Metrics(advance, upem, f["OS/2"].usWinAscent + f["OS/2"].usWinDescent, advance.get(ord("N"), upem // 2))


def _ass_font_size(style: CaptionStyle) -> float:
    """font_size_px is the em size, as in CSS. libass instead scales a font so its
    ascent+descent equals Fontsize, which for Montserrat is 1.56x smaller."""
    m = _metrics(style.font_family)
    return style.font_size_px * m.win_height / m.upem if m else style.font_size_px


def _text_px(text: str, style: CaptionStyle) -> float:
    m = _metrics(style.font_family)
    if m is None:  # not bundled: a generous guess for a bold sans
        return len(text) * 0.62 * style.font_size_px
    return sum(m.advance.get(ord(ch), m.fallback) for ch in text) * style.font_size_px / m.upem


def _line_px(grp: Words, style: CaptionStyle) -> float:
    """Width of a caption line as libass will draw it: the words, the outline on both
    ends, and room for the active word at its enlarged size."""
    longest = max(_text_px(w, style) for _, _, w in grp)
    return (_text_px(" ".join(w for _, _, w in grp), style) + longest * (style.active_scale - 1)
            + 2 * style.outline_px)


def captions_ass(words: Words, breaks_after: set[int], style: CaptionStyle) -> str:
    """ASS file text. `breaks_after`: word indexes that end a sentence or a shot."""
    bs = chr(92)  # a literal backslash for ASS override tags
    primary, accent = _ass_color(style.primary_color), _ass_color(style.accent_color)
    scale = int(round(style.active_scale * 100))
    groups, cur = [], []
    for n, w in enumerate(words):
        cur.append(w)
        if len(cur) == style.words_per_group or n in breaks_after:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    states = []
    for grp in groups:
        # Too wide for one line: wrap onto a second line at the most even split. The
        # break is placed here, once per group, so it does not jump as the active word
        # grows; libass's own wrapping (WrapStyle 0) is only a backstop.
        split = None
        if len(grp) > 1 and _line_px(grp, style) > SAFE_WIDTH:
            split = min(range(1, len(grp)),
                        key=lambda k: max(_line_px(grp[:k], style), _line_px(grp[k:], style)))
        widest = max(_line_px(part, style) for part in ([grp[:split], grp[split:]] if split else [grp]))
        # Only a single over-long word can still be too wide: shrink the caption to fit.
        fit = f"{{{bs}fs{int(_ass_font_size(style) * SAFE_WIDTH / widest)}}}" if widest > SAFE_WIDTH else ""
        for i, (st, en, _) in enumerate(grp):
            stop = grp[i + 1][0] if i + 1 < len(grp) else en + 0.12
            parts = [(f"{{{bs}c{accent}&{bs}fscx{scale}{bs}fscy{scale}}}{w}{{{bs}c{primary}&{bs}fscx100{bs}fscy100}}"
                      if j == i else w) for j, (_, _, w) in enumerate(grp)]
            text = fit + "".join(p if j == 0 else (bs + "N" if j == split else " ") + p
                                 for j, p in enumerate(parts))
            states.append([st, stop, text])
    for a, b in zip(states, states[1:]):
        a[1] = min(a[1], b[0])
    events = "\n".join(f"Dialogue: 0,{_ts(st)},{_ts(sp)},Cap,,0,0,0,,{tx}" for st, sp, tx in states if sp > st)
    margin_v = int(1920 * (1 - style.position_y))
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{style.font_family},{_ass_font_size(style):.0f},{primary},{primary},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{style.outline_px},{style.shadow_px},2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}
"""


def _spoken_words(line: str) -> list[str]:
    """Whitespace words, also split after dashes: "glowing—you" is two spoken words
    (and two Whisper words), and as one caption token it was too wide for the frame."""
    return line.replace("—", "— ").replace("–", "– ").split()


# ── pieces: one shot → one finished segment; the reel is the segments joined ──────
#
# Each segment is the shot's 1080x1920 picture with its captions burned in, plus its
# sound (effects bed + narration) as PCM of *exactly* the picture's length. Segments
# are built while the GPU is still rendering later shots; joining them afterwards
# copies the video (no re-encode) and only processes the audio.

FPS = 24
RATE = 48000
BREAK_AFTER = (".", "!", "?", "—", "–")   # a caption group never runs past these
# Bump when a segment's content changes, so cached segments are not reused.
SEGMENT_VERSION = 2


def narration_words(wav: Path, line: str,
                    word_timings: Callable[[Path, str], Words] = whisper_words) -> Words:
    """The line's own words, timed against its recording (seconds from the WAV start)."""
    words = _spoken_words(line)
    times = align(words, word_timings(wav, line), probe_duration(wav))
    return [(round(a, 3), round(b, 3), w) for (a, b), w in zip(times, words)]


def dialogue_words(clip: Path, hint: str,
                   word_timings: Callable[[Path, str], Words] = whisper_words) -> Words:
    """What the characters in a shot say, as heard (biased by the intended dialogue)."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "speech.wav"
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        return word_timings(wav, hint)


class FfmpegError(RuntimeError):
    """ffmpeg/ffprobe failed; the message carries the tool's own last error lines."""


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        tail = " | ".join(ln.strip() for ln in r.stderr.strip().splitlines()[-4:])
        raise FfmpegError(f"{cmd[0]} failed: {tail or f'exit {r.returncode}'}")


def _has_audio(p: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True, check=True)
    return bool(r.stdout.strip())


def _frames(p: Path) -> int:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                        "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return int(r.stdout.strip())


def build_segment(clip: Path, out_video: Path, out_audio: Path, *, narration: Path | None = None,
                  words: Words | None = None, style: CaptionStyle = CaptionStyle()) -> dict:
    """One rendered shot → its finished piece of the reel.

    `words` are timed from the start of the shot. With `narration` the shot's own
    sound is ducked under the voice, which starts LEAD_IN into the shot."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        vf = "scale=1080:-2:flags=lanczos,crop=1080:1920,setsar=1,fps=24,format=yuv420p"
        if words:
            breaks = {i for i, (_, _, w) in enumerate(words) if w.rstrip('"”').endswith(BREAK_AFTER)}
            clean = [(st, en, (w.upper() if style.uppercase else w).strip(",.!?;:—–\"“”")) for st, en, w in words]
            (work / "captions.ass").write_text(captions_ass(clean, breaks, style), encoding="utf-8")
            # A relative fontsdir: ffmpeg's filter syntax mangles Windows drive paths.
            shutil.copytree(FONTS_DIR, work / "fonts")
            vf += ",ass=captions.ass:fontsdir=fonts"
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(clip.resolve()), "-vf", vf, "-an",
              "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
              str(out_video.resolve())], cwd=work)
    frames = _frames(out_video)
    samples = frames * RATE // FPS                 # the picture's exact length, in samples

    stereo = f"aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"
    inputs = (["-i", str(clip)] if _has_audio(clip)
              else ["-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=stereo"])
    graph = f"[0:a]{stereo},volume={SFX_GAIN if narration else 1.0}[bed];"
    if narration:
        inputs += ["-i", str(narration)]
        ms = int(LEAD_IN * 1000)
        graph += f"[1:a]{stereo},adelay={ms}|{ms}[nar];[bed][nar]amix=inputs=2:normalize=0[mix];"
    else:
        graph += "[bed]anull[mix];"
    graph += f"[mix]apad=whole_len={samples},atrim=end_sample={samples}[out]"
    _run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[out]",
          "-c:a", "pcm_s16le", "-ar", str(RATE), str(out_audio)])
    return {"frames": frames, "seconds": frames / FPS, "caption_words": len(words or [])}


# Loudness to YouTube's target, once over the whole reel. The explicit stereo layout,
# before the filters and on the encoder, matters: WAV stores no channel layout,
# and ffmpeg 5.1 (Debian 12, the worker image) then fails to set up loudnorm ->
# AAC with "Cannot select channel layout" — newer ffmpeg does not, which is how
# this reached production (2026-10-11, after an 8-shot render).
SOUND_FILTERS = (f"aformat=sample_fmts=fltp:sample_rates={RATE}:channel_layouts=stereo,"
                 f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample={RATE}")
SOUND_CODEC = ["-ch_layout", "stereo", "-c:a", "aac", "-b:a", "160k"]


def _listing(path: Path, files: list[Path]) -> Path:
    """An ffmpeg concat-demuxer list of `files` (absolute paths, quotes escaped)."""
    quote = chr(39)
    lines = (f"file {quote}{f.resolve().as_posix().replace(quote, quote + chr(92) + quote + quote)}{quote}"
             for f in files)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _check_reel(out: Path, frames: int) -> float:
    """Raise unless `out` has every frame and sound for its whole length."""
    got = _frames(out)
    if got != frames:
        raise FfmpegError(f"joined reel has {got} frames, expected {frames}")
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
    sound = float((r.stdout.strip() or "0").split(",")[0] or 0)
    if abs(sound - frames / FPS) > 0.25:
        raise FfmpegError(f"joined reel's sound is {sound:.2f}s for {frames / FPS:.2f}s of picture")
    return frames / FPS


def join_segments(segments: list[tuple[Path, Path]], out: Path, log: Callable[[str], None] = print) -> dict:
    """Finished segments -> the reel, checked before it is returned.

    The sound is joined as one stream (the segments' WAVs are sample-exact), made
    stereo explicitly, normalised once and encoded to AAC. The pictures are copied
    as they are. If that fast join fails or comes out wrong, the pictures are
    re-encoded instead: slower, but a render is never lost to the final step.
    """
    frames = sum(_frames(v) for v, _ in segments)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        pictures = _listing(work / "pictures.txt", [v for v, _ in segments])
        sounds = _listing(work / "sounds.txt", [a for _, a in segments])
        sound = work / "sound.m4a"
        _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(sounds),
              "-af", SOUND_FILTERS, *SOUND_CODEC, str(sound)])
        try:
            _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(pictures),
                  "-i", str(sound), "-map", "0:v", "-map", "1:a", "-c", "copy", "-movflags", "+faststart",
                  str(out)])
            seconds, how = _check_reel(out, frames), "copy"
        except FfmpegError as e:
            log(f"fast join failed ({e}); re-encoding the pictures instead")
            _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(pictures),
                  "-i", str(sound), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)])
            seconds, how = _check_reel(out, frames), "re-encode"
    return {"seconds": round(seconds, 2), "shots": len(segments), "join": how}


def shifted(words: Words, by: float) -> Words:
    return [(a + by, b + by, w) for a, b, w in words]


def build_reel(work: Path, shots: list[Path], narrations: list[Path] | None, lines: list[str],
               out: Path, *, style: CaptionStyle = CaptionStyle(), hint: str = "",
               word_timings: Callable[[Path, str], Words] = whisper_words) -> dict:
    """The whole reel in one go, in `work` (a scratch dir). The workers build the same
    segments one by one while rendering; this is that path without the wait.
    `narrations`/`lines` are per shot for narrated posts; None if characters speak."""
    segments, n_words = [], 0
    for k, clip in enumerate(shots):
        narr = narrations[k] if narrations is not None else None
        words = (shifted(narration_words(narr, lines[k], word_timings), LEAD_IN) if narr is not None
                 else dialogue_words(clip, hint, word_timings))
        seg = (work / f"seg{k}.mp4", work / f"seg{k}.wav")
        n_words += build_segment(clip, *seg, narration=narr, words=words, style=style)["caption_words"]
        segments.append(seg)
    return {**join_segments(segments, out), "caption_words": n_words}
