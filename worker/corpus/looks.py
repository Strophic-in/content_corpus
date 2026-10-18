"""Video looks: how a post's *generated* shots look — photoreal, documentary, 3D,
cartoon, anime, stick figures, claymation, watercolour, comic, retro film, VHS,
black-and-white archival, war documentary, neon sci-fi, motion graphics.

Each look (prompts/looks/<id>.json) carries the words added to every generated
shot (`prompt`), what the video model should avoid (`avoid`), and a colour grade
(`grade`, an ffmpeg filter) applied after rendering — to generated shots only:
real footage stays as it was filmed (owner's choice, 2026-10-18).

A channel's `video_look` is "auto", "format" (each format's own look text, as
before looks existed) or one look. On auto, Jev picks the look per post from the
story, its category and its format; a story Jev judges sensitive (death, war,
disaster, a crime with victims) never gets a playful look (cartoon, anime, stick
figures, claymation, comic). Without Jev, auto falls back to a look per template.
A photoreal look marks its generated shots "AI-generated" on screen, so a viewer
never takes them for footage of the event.
"""

from __future__ import annotations

import functools
import json
import re

from pydantic import BaseModel, field_validator

from .config import settings


class VideoLook(BaseModel):
    look_id: str
    name: str
    realism: str            # "photoreal" | "stylised"
    playful: bool
    prompt: str
    avoid: str
    grade: str
    best_for: list[str]
    never_for: list[str]

    @field_validator("look_id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9_]{3,40}", v):
            raise ValueError("look_id must be lowercase letters, digits and _")
        return v

    @field_validator("realism")
    @classmethod
    def _realism(cls, v: str) -> str:
        if v not in ("photoreal", "stylised"):
            raise ValueError("realism is photoreal or stylised")
        return v

    @field_validator("grade")
    @classmethod
    def _grade(cls, v: str) -> str:
        # A filter chain only: no labels, no second input, no file access.
        if v and not re.fullmatch(r"[a-z]+=[A-Za-z0-9_.:=/\-]+(,[a-z]+=[A-Za-z0-9_.:=/\-]+)*", v):
            raise ValueError(f"grade {v!r} must be a plain ffmpeg filter chain")
        return v


@functools.lru_cache(maxsize=1)
def registry() -> dict[str, VideoLook]:
    out = {}
    for path in sorted((settings().prompts_dir / "looks").glob("*.json")):
        look = VideoLook.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if look.look_id != path.stem:
            raise ValueError(f"{path.name}: look_id {look.look_id!r} does not match the file name")
        out[look.look_id] = look
    return out


def get(look_id: str | None) -> VideoLook | None:
    return registry().get(look_id or "")


# Auto without Jev: what each template's generated shots look like by default.
BY_TEMPLATE = {
    "mini_news_explainer": "documentary_real", "documentary_storytelling": "documentary_real",
    "reaction_commentary": "documentary_real", "top_bottom_split_screen": "documentary_real",
    "animated_infographic": "motion_graphics", "myth_vs_fact": "editorial_3d",
    "cinematic_3d_explainer": "animated_3d", "question_answer_demo": "animated_3d",
    "character_dialogue": "photoreal_cinematic", "pov_immersive_scenario": "photoreal_cinematic",
    "transformation_match_cut": "photoreal_cinematic", "seamless_loop": "photoreal_cinematic",
    "satisfying_process_timelapse": "photoreal_cinematic", "ranked_countdown": "photoreal_cinematic",
    "before_after_comparison": "photoreal_cinematic", "kinetic_typography": "motion_graphics",
    "full_screen_text_overlay": "motion_graphics",
}
SAFE = "documentary_real"       # for a sensitive story that drew a playful look
SURE = 0.3


def default_for(template_id: str | None) -> str:
    return BY_TEMPLATE.get(template_id or "", "photoreal_cinematic")


def choose(judge, setting: str | None, *, story: str, category: str, template) -> tuple[str, str]:
    """(look_id or "format", why) for a post."""
    setting = setting or "auto"
    if setting == "format":
        return "format", "the format's own look"
    if setting != "auto":
        if get(setting):
            return setting, "the channel's look"
        setting = "auto"
    fallback = default_for(getattr(template, "template_id", None))
    if judge is None:
        return fallback, f"the usual look for {getattr(template, 'display_name', 'this format')}"
    reg = registry()
    criteria = {lid: f"{lk.name}: best for {', '.join(lk.best_for)}"
                + (f"; never for {', '.join(lk.never_for)}" if lk.never_for else "") for lid, lk in reg.items()}
    try:
        a = judge.ask({"story": story[:1500], "category": category[:600],
                       "format": f"{template.display_name}: {template.format}"},
                      {"look": {"type": "choice", "criteria": criteria,
                                "instructions": "Which visual style should the AI-generated shots of a short video "
                                                "about `story` have, given `category` and `format`?"},
                       "sensitive": {"type": "noul",
                                     "instructions": "Is `story` about death, violence, war, a disaster, a crime "
                                                     "with victims or another tragedy?"}})
    except Exception:  # noqa: BLE001 - the template's usual look
        return fallback, f"the usual look for {template.display_name}"
    pick = a.get("look") or {}
    look_id, sure = pick.get("choice"), float(pick.get("confidence") or 0)
    if look_id not in reg or sure < SURE:
        return fallback, f"the usual look for {template.display_name} (Jev unsure)"
    if reg[look_id].playful and float((a.get("sensitive") or {}).get("noul", 0)) >= 0.5:
        return SAFE, f"a sensitive story: not {reg[look_id].name.lower()}"
    return look_id, f"Jev's pick ({sure:.0%} sure)"
