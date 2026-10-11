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
# on-screen characters; a voice-over narrator may run faster (explainer pace).
MAX_WORDS_PER_SECOND = 2.8
MAX_NARRATION_WORDS_PER_SECOND = 3.2


class Shot(BaseModel):
    seconds: int
    visual: str     # what we see, in order: subject, action, setting, camera, light
    audio: str      # sounds in the shot; on-screen dialogue in double quotes (native mode only)
    narration: str  # voice-over spoken over this shot (narrated mode); "" otherwise


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
            raise ValueError("model returned no parsable script")
        u = resp.usage
        return out, Usage(model=resp.model, input_tokens=getattr(u, "input_tokens", 0),
                          output_tokens=getattr(u, "output_tokens", 0))


def validate(out: ScriptOut, target_seconds: int, narrated: bool = False) -> list[str]:
    """Problems that make a script unusable. Empty list = fine.

    narrated: one voice-over across the reel (audio_source='kokoro'). Then every
    shot needs its narration and its own audio must be sound effects only — any
    quoted line there would make the video model invent a second, random voice.
    """
    problems = []
    if not out.shots:
        problems.append("no shots")
    if len(out.title) > 100:
        problems.append(f"title is {len(out.title)} chars; YouTube allows 100")
    for i, s in enumerate(out.shots, 1):
        if not MIN_SHOT_SECONDS <= s.seconds <= MAX_SHOT_SECONDS:
            problems.append(f"shot {i} is {s.seconds}s; allowed {MIN_SHOT_SECONDS}-{MAX_SHOT_SECONDS}s")
        quoted = " ".join(s.audio.split('"')[1::2])
        if narrated:
            words = len(s.narration.split())
            if not words:
                problems.append(f"shot {i} has no narration")
            elif words > s.seconds * MAX_NARRATION_WORDS_PER_SECOND:
                problems.append(f"shot {i} narration is {words} words for {s.seconds}s")
            if quoted:
                problems.append(f"shot {i} audio contains dialogue; narrated shots carry sound effects only")
        elif quoted and len(quoted.split()) > s.seconds * MAX_WORDS_PER_SECOND:
            problems.append(f"shot {i} has {len(quoted.split())} spoken words for {s.seconds}s")
    total = sum(s.seconds for s in out.shots)
    if out.shots and not 0.6 * target_seconds <= total <= 1.4 * target_seconds:
        problems.append(f"shots total {total}s against a {target_seconds}s target")
    return problems
