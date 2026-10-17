"""The template registry: every kind of post a format can be made from.

A template is data, shipped in prompts/templates/: `<id>.json` says what it is
(content type, length, structure, assets, music, cost, rights) and how it renders
by default (`render`); `<id>.md` is the guide appended to the script writer's
prompt, saying how this template's script is built. The renderers (media/) know
nothing about templates: they read a script's shots — role, on-screen text,
label, layout, transition — and a Look (fonts, colours, captions) resolved here
from the template's defaults and the owner's per-format `params`.

A format (the formats table) is one template plus the owner's prompts and params.
Nothing here is called "viral": templates are ranked by the channel's own numbers.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .config import settings

ContentType = Literal["video", "carousel", "image"]
Captions = Literal["karaoke", "beats", "kinetic", "speech", "none"]
Layout = Literal["full", "split"]
Transition = Literal["cut", "fade", "crossfade", "whip", "wipe", "zoom", "flash"]
Audio = Literal["kokoro", "none", "ltx_native"]
Source = Literal["generate", "clip", "image", "stock", "chart", "plain"]
ChartKind = Literal["bar", "stat", "compare", "line"]
SlideLayout = Literal["educational", "photo", "card"]

PLATFORMS = ("youtube_shorts", "instagram_reels", "instagram_carousel", "instagram_image")
MUSIC_SOURCE_MODES = ("licensed_asset", "platform_native", "none")
# Music moods a template may suggest: music.MOODS's names.
MOODS = ("breaking-tension", "somber", "uplifting", "energetic-hype", "neutral-corporate", "playful", "cinematic",
         "curious")
FONTS = {"Montserrat": "Montserrat-ExtraBold.ttf", "Noto Serif": "NotoSerif-Bold.ttf"}
BODY_FONTS = {"Montserrat": "Montserrat-Medium.ttf", "Noto Serif": "NotoSerif-Regular.ttf"}


class Slides(BaseModel):
    layout: SlideLayout
    aspect: Literal["4:5", "1:1"] = "4:5"
    count: tuple[int, int]
    # Each slide's time in the YouTube slideshow: reading time, within these bounds.
    seconds: tuple[float, float] = (3.0, 7.0)

    @model_validator(mode="after")
    def _ranges(self):
        if not 1 <= self.count[0] <= self.count[1] <= 10:
            raise ValueError("slide count must be within 1-10 (Instagram's carousel limit)")
        if not 1 <= self.seconds[0] <= self.seconds[1] <= 15:
            raise ValueError("seconds per slide must be within 1-15")
        return self


class Render(BaseModel):
    """How a template renders unless the format's params say otherwise."""
    captions: Captions = "karaoke"
    text: Literal["headline", "none"] = "none"     # shot.text drawn as a headline (when captions != beats)
    labels: bool = False                           # shot.label drawn as a chip
    layout: Layout = "full"
    layouts: list[Layout] = ["full"]               # what a shot may choose
    transition: Transition = "cut"
    transitions: list[Transition] = ["cut"]
    audio: Audio = "kokoro"
    audios: list[Audio] = ["kokoro"]
    sources: list[Source] = ["generate", "clip", "image", "stock", "chart"]
    chart_kinds: list[ChartKind] = ["bar"]
    loop: bool = False
    timelapse: bool = False
    focus: bool = False                            # shots may punch in on a region
    ken_burns: float = 0.12
    slides: Slides | None = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.layout not in self.layouts:
            raise ValueError(f"default layout {self.layout} is not in layouts")
        if self.transition not in self.transitions:
            raise ValueError(f"default transition {self.transition} is not in transitions")
        if self.audio not in self.audios:
            raise ValueError(f"default audio {self.audio} is not in audios")
        if not 0 <= self.ken_burns <= 0.3:
            raise ValueError("ken_burns zoom must be 0-0.3")
        return self


class Template(BaseModel):
    template_id: str
    display_name: str
    content_type: ContentType
    supported_platforms: list[str]
    aspect_ratio: Literal["9:16", "4:5", "1:1"]
    recommended_duration_seconds: tuple[int, int]
    recommended_slide_count: tuple[int, int] | None = None
    required_assets: list[str]
    optional_assets: list[str] = []
    scene_structure: list[str]
    caption_style: str
    visual_style: str
    music_mood: list[str]
    music_source_mode: str = "licensed_asset"
    automation_level: Literal["high", "medium", "low"]
    estimated_render_cost: Literal["low", "medium", "high"]
    rights_requirements: list[str] = []
    render_notes: list[str] = []
    platform_notes: list[str] = []
    performance_metrics: list[str] = ["views", "likes", "comments", "views_vs_channel_baseline"]
    format: str                                    # one line: what it looks like
    best_for: list[str]
    topics: list[str]
    goals: list[str]
    # The idea agent may choose it on its own. Templates that need the owner's own
    # footage (a screen recording, an interview) are chosen by the owner.
    ai_pick: bool = True
    needs_owned_footage: bool = False
    base_prompt: str = "script_video.md"
    render: Render
    guide: str = Field(default="", exclude=True)   # the <id>.md writer guide

    @field_validator("template_id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9_]{3,60}", v):
            raise ValueError("template_id must be lowercase letters, digits and _")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        lo, hi = self.recommended_duration_seconds
        if not 3 <= lo <= hi <= 180:
            raise ValueError("recommended_duration_seconds must be within 3-180 s")
        if not self.scene_structure:
            raise ValueError("scene_structure is empty")
        bad = [p for p in self.supported_platforms if p not in PLATFORMS]
        if bad:
            raise ValueError(f"unknown platforms {bad}")
        if self.music_source_mode not in MUSIC_SOURCE_MODES:
            raise ValueError(f"music_source_mode must be one of {MUSIC_SOURCE_MODES}")
        bad = [m for m in self.music_mood if m not in MOODS]
        if bad:
            raise ValueError(f"unknown music moods {bad}")
        if self.content_type == "video":
            if self.aspect_ratio != "9:16" or self.render.slides is not None:
                raise ValueError("a video template is 9:16 and has no slides")
        else:
            s = self.render.slides
            if s is None or self.recommended_slide_count is None:
                raise ValueError("a carousel or image template needs render.slides and recommended_slide_count")
            if self.aspect_ratio != s.aspect:
                raise ValueError("aspect_ratio must match render.slides.aspect")
            if self.content_type == "image" and s.count != (1, 1):
                raise ValueError("an image template has exactly one slide")
        return self


class TemplateError(ValueError):
    pass


def templates_dir() -> Path:
    return settings().prompts_dir / "templates"


@functools.lru_cache(maxsize=1)
def registry() -> dict[str, Template]:
    """Every template, validated; a broken file is an error, never skipped."""
    out: dict[str, Template] = {}
    for path in sorted(templates_dir().glob("*.json")):
        try:
            t = Template.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, ValidationError) as e:
            raise TemplateError(f"{path.name}: {e}") from e
        if t.template_id != path.stem:
            raise TemplateError(f"{path.name}: template_id {t.template_id!r} does not match the file name")
        guide = path.with_suffix(".md")
        if not guide.exists():
            raise TemplateError(f"{path.name}: its writer guide {guide.name} is missing")
        t.guide = guide.read_text(encoding="utf-8").strip()
        if not (settings().prompts_dir / t.base_prompt).exists():
            raise TemplateError(f"{path.name}: base_prompt {t.base_prompt} does not exist")
        out[t.template_id] = t
    return out


def get(template_id: str | None) -> Template:
    reg = registry()
    return reg.get(template_id or "") or reg["cinematic_3d_explainer"]


# ── a format's look: the template's defaults, overridden by the owner's params ──

class Look(BaseModel):
    """Everything about a format's appearance the renderers need, resolved."""
    captions: Captions
    text: Literal["headline", "none"]
    labels: bool
    layout: Layout
    transition: Transition
    loop: bool
    timelapse: bool
    ken_burns: float
    font: str = "Montserrat"
    primary_color: str = "#FFFFFF"
    accent_color: str = "#FFE000"
    background_color: str = "#0F172A"
    panel_color: str = "#111827"
    caption_position: Literal["top", "middle", "bottom"] = "bottom"
    safe_margin_px: int = 60
    music_source_mode: str = "licensed_asset"
    brand_text: str = ""
    slides: Slides | None = None
    ai_images: Literal["cover", "all", "none"] = "cover"

    @property
    def caption_y(self) -> float:
        return {"top": 0.30, "middle": 0.55, "bottom": 0.72}[self.caption_position]


HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
PARAM_KEYS = ("captions", "transition", "font", "primary_color", "accent_color", "background_color",
              "panel_color", "caption_position", "safe_margin_px", "music_source_mode", "brand_text",
              "slide_aspect", "slide_count", "ai_images", "layout")


def clean_params(params: dict | None, t: Template) -> tuple[dict, list[str]]:
    """The params a format may set, checked; (kept, problems). Unknown keys are dropped."""
    p, problems, out = dict(params or {}), [], {}
    r = t.render
    allowed = {
        "captions": lambda v: v in ("karaoke", "beats", "kinetic", "speech", "none"),
        "transition": lambda v: v in r.transitions,
        "layout": lambda v: v in r.layouts,
        "font": lambda v: v in FONTS,
        "primary_color": lambda v: isinstance(v, str) and bool(HEX.match(v)),
        "accent_color": lambda v: isinstance(v, str) and bool(HEX.match(v)),
        "background_color": lambda v: isinstance(v, str) and bool(HEX.match(v)),
        "panel_color": lambda v: isinstance(v, str) and bool(HEX.match(v)),
        "caption_position": lambda v: v in ("top", "middle", "bottom"),
        "safe_margin_px": lambda v: isinstance(v, int) and 30 <= v <= 160,
        "music_source_mode": lambda v: v in MUSIC_SOURCE_MODES,
        "brand_text": lambda v: isinstance(v, str) and len(v) <= 40,
        "slide_aspect": lambda v: t.render.slides is not None and v in ("4:5", "1:1"),
        "slide_count": lambda v: (t.render.slides is not None and isinstance(v, int)
                                  and t.render.slides.count[0] <= v <= t.render.slides.count[1]),
        "ai_images": lambda v: v in ("cover", "all", "none"),
    }
    for k, v in p.items():
        if k not in allowed:
            continue
        if allowed[k](v):
            out[k] = v
        else:
            problems.append(f"{k}: {v!r} is not allowed for {t.display_name}")
    return out, problems


def look(template_id: str | None, params: dict | None = None) -> Look:
    t = get(template_id)
    p, _ = clean_params(params, t)
    r = t.render
    slides = r.slides
    if slides is not None and ("slide_aspect" in p or "slide_count" in p):
        n = p.get("slide_count")
        slides = slides.model_copy(update={"aspect": p.get("slide_aspect", slides.aspect),
                                           "count": (n, n) if n else slides.count})
    return Look(captions=p.get("captions", r.captions), text=r.text, labels=r.labels,
                layout=p.get("layout", r.layout), transition=p.get("transition", r.transition), loop=r.loop,
                timelapse=r.timelapse, ken_burns=r.ken_burns, slides=slides,
                music_source_mode=p.get("music_source_mode", t.music_source_mode),
                **{k: p[k] for k in ("font", "primary_color", "accent_color", "background_color", "panel_color",
                                     "caption_position", "safe_margin_px", "brand_text", "ai_images") if k in p})


def look_for_post(c, post: dict) -> Look:
    """The look a post renders with: its format's template and params (a post made
    before formats renders as the template its audio implies)."""
    f = (c.execute("select template_id, params from formats where id = %s", (post["format_id"],)).fetchone()
         if post.get("format_id") else None)
    if f is None:
        return look("character_dialogue" if post.get("audio_source") == "ltx_native" else "cinematic_3d_explainer")
    return look(f["template_id"], f["params"])


def split_size(extras: dict | None, lk: Look) -> tuple[int, int]:
    """A shot's picture size: half height for a split screen's top panel."""
    return (1080, 960) if ((extras or {}).get("layout") or lk.layout) == "split" else (1080, 1920)


# ── for the idea agent: the formats it may choose from ─────────────────────────

def describe_for_planner(n: int, name: str, t: Template, performance: str = "") -> str:
    kind = {"video": "vertical video", "carousel": "swipeable carousel (Instagram; a slideshow Short on YouTube)",
            "image": "single picture post (Instagram; a short slideshow on YouTube)"}[t.content_type]
    lo, hi = t.recommended_duration_seconds
    needs = ", ".join(t.required_assets)
    return (f"{n}. {name} — {t.display_name}: {t.format} ({kind}, {lo}-{hi} s). Best for: {', '.join(t.best_for)}. "
            f"Needs: {needs}. Cost to make: {t.estimated_render_cost}."
            + (" Only when the owner has their own footage for it." if t.needs_owned_footage else "")
            + (f" {performance}" if performance else ""))
