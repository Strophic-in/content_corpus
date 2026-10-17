"""Script writer: one structured LLM call that turns a topic into a reel script.

The output schema is the contract with the rest of the pipeline. Constraints that
matter downstream (shot length, dialogue pace) are checked in validate() rather
than in the JSON schema, so a model that ignores a range produces a clear error
instead of a silently clamped script.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

# LTX-2.5 renders one continuous shot per generation; ~20 s is the documented
# ceiling and quality is best well under it.
MIN_SHOT_SECONDS, MAX_SHOT_SECONDS = 3, 12
# Spoken pace that fits a shot without rushing: ~2.5 words per second for
# on-screen characters.
MAX_WORDS_PER_SECOND = 2.8
# Narrated mode: the voice sets each shot's length, so the model's `seconds` is
# only an estimate. What matters is that a line, spoken, fits one shot. Kokoro
# speaks ~2.55 words/s at speed 1.0 (measured: 27 words → 9.7 s at 1.1); leave
# a second of the 12 s for the pause after the line and slower words.
NARRATOR_WORDS_PER_SECOND = 2.55
NARRATION_FIT_SECONDS = MAX_SHOT_SECONDS - 1.0


def narration_word_cap(speed: float = 1.1) -> int:
    """Most words one shot's narration may have at this narrator speed."""
    return int(NARRATION_FIT_SECONDS * NARRATOR_WORDS_PER_SECOND * speed)


def spoken_seconds(words: int, speed: float = 1.1) -> float:
    return words / (NARRATOR_WORDS_PER_SECOND * speed)


SOURCES = ("generate", "clip", "image", "stock")
# A clip that plays with its own sound (someone speaking, the moment itself) may run
# longer than a generated shot: nothing has to be rendered.
MAX_CLIP_SECONDS = 20
MIN_CLIP_SECONDS = 1.5


class Shot(BaseModel):
    seconds: int
    # Where the picture comes from: "generate" (the AI video model renders `visual`),
    # "clip" (a window of a video from the footage list), "image" (a picture from the
    # footage list, with a slow camera move), "stock" (a stock video found by
    # `stock_query`). Older scripts have no source: they are all "generate".
    source: str
    asset: int          # clip/image: the footage's number in the list; 0 otherwise
    start: float        # clip: where the window starts in that video, in seconds; 0 otherwise
    end: float          # clip: where it ends; 0 otherwise
    keep_audio: bool    # clip: play the video's own sound (no narration over it); false otherwise
    stock_query: str    # stock: 2-5 plain words to search stock video; "" otherwise
    visual: str     # what we see, in order: subject, action, setting, camera, light
    audio: str      # sounds in the shot; on-screen dialogue in double quotes (native mode only)
    narration: str  # voice-over spoken over this shot (narrated mode); "" otherwise


GENERATED = {"source": "generate", "asset": 0, "start": 0.0, "end": 0.0, "keep_audio": False, "stock_query": ""}


def generated_shot(**fields) -> Shot:
    """A generated shot: the footage fields at their "unused" values."""
    return Shot(**{**GENERATED, **fields})


@dataclass
class Footage:
    """What a script may use besides generated shots: the post's assets, and stock."""
    assets: list[dict]          # {"n", "kind": "video"|"image", "seconds", "w", "h", "credit", ...}
    stock: bool = False         # a Pexels key is set

    def asset(self, n: int) -> dict | None:
        return next((a for a in self.assets if a["n"] == n), None)

    @property
    def any(self) -> bool:
        return bool(self.assets) or self.stock


class Review(BaseModel):
    score: int            # 1-10, the model's own honest rating
    risks: list[str]      # things likely to render badly or land poorly
    notes: str


class ScriptOut(BaseModel):
    title: str
    hook: str
    description: str
    hashtags: list[str]
    intended_dialogue: str
    style_prompt: str
    shots: list[Shot]
    review: Review


@dataclass
class Usage:
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0

    @classmethod
    def of(cls, resp) -> "Usage":
        """From an OpenAI Responses API reply (token counts only: replies carry no price)."""
        u = resp.usage
        details = getattr(u, "input_tokens_details", None)
        return cls(model=resp.model, input_tokens=getattr(u, "input_tokens", 0) or 0,
                   output_tokens=getattr(u, "output_tokens", 0) or 0,
                   cached_input_tokens=getattr(details, "cached_tokens", 0) or 0,
                   cache_write_tokens=getattr(details, "cache_write_tokens", 0) or 0)


class Unparsed(ValueError):
    """The model answered (and was billed) but not in the requested shape."""

    def __init__(self, message: str, usage: Usage):
        super().__init__(message)
        self.usage = usage


class ScriptWriter(Protocol):
    def write(self, *, model: str, system: str, user: str) -> tuple[ScriptOut, Usage]: ...


class OpenAIScriptWriter:
    def __init__(self, api_key: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=120, max_retries=2)

    def write(self, *, model: str, system: str, user: str) -> tuple[ScriptOut, Usage]:
        resp = self.client.responses.parse(model=model, instructions=system, input=user,
                                           text_format=ScriptOut)
        out = resp.output_parsed
        if out is None:
            raise Unparsed("model returned no parsable script", Usage.of(resp))
        return out, Usage.of(resp)


def _footage_problems(i: int, s: Shot, footage: Footage | None, narrated: bool) -> list[str]:
    src = s.source or "generate"
    if src not in SOURCES:
        return [f"shot {i} has source \"{s.source}\"; use one of {', '.join(SOURCES)}"]
    if src == "generate":
        return []
    if src == "stock":
        if footage is None or not footage.stock:
            return [f"shot {i} uses stock video, which is not available for this reel; use \"generate\""]
        return [] if s.stock_query.strip() else [f"shot {i} is a stock shot without a stock_query; add 2-5 words"]
    a = footage.asset(s.asset) if footage else None
    want = "video" if src == "clip" else "image"
    if a is None or a["kind"] != want:
        return [f"shot {i} uses footage #{s.asset}, which is not a {want} in the footage list; "
                f"pick a listed {want} or use \"generate\""]
    if src == "image":
        return []
    out = []
    length = s.end - s.start
    if s.start < 0 or (a.get("seconds") and s.end > float(a["seconds"]) + 0.05):
        out.append(f"shot {i}'s clip window {s.start:g}-{s.end:g}s is outside video #{s.asset} "
                   f"(0-{float(a['seconds']):g}s)")
    elif length < MIN_CLIP_SECONDS:
        out.append(f"shot {i}'s clip window is {length:.1f}s; make it at least {MIN_CLIP_SECONDS:g}s")
    elif s.keep_audio and length > MAX_CLIP_SECONDS:
        out.append(f"shot {i} plays {length:.0f}s of the clip with its own sound; keep it to {MAX_CLIP_SECONDS}s")
    if s.keep_audio and narrated and s.narration.strip():
        out.append(f"shot {i} keeps the clip's own sound, so its narration must be \"\"")
    return out


def shot_seconds(s: Shot, narrated: bool, speed: float = 1.1) -> float:
    """About how long a shot lasts in the reel."""
    if (s.source or "generate") == "clip" and s.keep_audio:
        return max(0.0, s.end - s.start)
    if narrated:
        return max(MIN_SHOT_SECONDS, spoken_seconds(len(s.narration.split()), speed) + 0.35)
    return s.seconds


def validate(out: ScriptOut, target_seconds: int, narrated: bool = False, speed: float = 1.1,
             footage: Footage | None = None) -> list[str]:
    """Problems that make a script unusable. Empty list = fine. Each problem is
    written as an instruction the model can act on when asked to repair the draft.

    narrated: one voice-over across the reel (audio_source='kokoro'). Then every
    shot needs its narration and its own audio must be sound effects only — any
    quoted line there would make the video model invent a second, random voice.
    The narration, not `seconds`, sets each shot's length (`speed` is the
    narrator's), so lines are checked for fitting one shot when spoken. A clip
    that keeps its own sound is the exception: it has no narration, and its window
    sets its length.

    footage: what this reel may show besides generated shots; a shot that names
    footage or stock the reel doesn't have is a problem.
    """
    problems = []
    if not out.shots:
        problems.append("there are no shots")
    if len(out.title) > 100:
        problems.append(f"the title is {len(out.title)} characters; shorten it to at most 100")
    cap = narration_word_cap(speed)
    for i, s in enumerate(out.shots, 1):
        problems += _footage_problems(i, s, footage, narrated)
        keeps_sound = (s.source or "generate") == "clip" and s.keep_audio
        if not narrated and not keeps_sound and not MIN_SHOT_SECONDS <= s.seconds <= MAX_SHOT_SECONDS:
            problems.append(f"shot {i} is {s.seconds}s; make it {MIN_SHOT_SECONDS}-{MAX_SHOT_SECONDS}s")
        quoted = " ".join(s.audio.split('"')[1::2])
        if narrated and keeps_sound:
            continue
        if narrated:
            words = len(s.narration.split())
            if not words:
                problems.append(f"shot {i} has no narration; give it a line")
            elif words > cap:
                problems.append(f"shot {i} narration is {words} words but at most {cap} fit one shot; "
                                f"shorten it, or split it across two shots")
            if quoted:
                problems.append(f"shot {i} audio contains dialogue; narrated shots carry sound effects only")
        elif quoted and len(quoted.split()) > s.seconds * MAX_WORDS_PER_SECOND:
            problems.append(f"shot {i} has {len(quoted.split())} spoken words for {s.seconds}s; "
                            f"cut the dialogue or lengthen the shot")
    # A narrated reel lasts as long as its narration takes to say (plus kept clips).
    total = round(sum(shot_seconds(s, narrated, speed) for s in out.shots))
    what = "the narration runs about" if narrated else "the shots total"
    if out.shots and not 0.6 * target_seconds <= total <= 1.4 * target_seconds:
        problems.append(f"{what} {total}s against a {target_seconds}s target; "
                        f"{'add' if total < target_seconds else 'cut'} material to fit")
    return problems
