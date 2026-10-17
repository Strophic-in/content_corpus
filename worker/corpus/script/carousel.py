"""The writer's output for carousels and cards: slides instead of shots.

One structured call, like a reel's script (write_script.py runs it, repairs it
and stores it in scripts.slides). Each slide has a role in the template's
structure, a heading, a body and a visual: one of the post's pictures, an AI
picture to draw, a chart, or nothing (the format's background). `problems`
checks a draft the way the slide renderer will lay it out (media/slides.plan),
so text that passes fits.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..media import slides as sl
from ..templates import Look, Template
from .llm import CHART_POINTS, MUSIC_MOODS, NO_CHART, Chart, Footage, Review, Unparsed, Usage

VISUALS = ("asset", "ai_image", "chart", "none")


class SlideVisual(BaseModel):
    source: str      # "asset" | "ai_image" | "chart" | "none"
    asset: int       # asset: the picture's number in the footage list; 0 otherwise
    prompt: str      # ai_image: what to draw; "" otherwise
    chart: Chart     # chart: its numbers; empty otherwise


class Slide(BaseModel):
    role: str
    heading: str
    body: str
    visual: SlideVisual


class CarouselOut(BaseModel):
    title: str
    hook: str
    description: str
    hashtags: list[str]
    slides: list[Slide]
    music_mood: str
    review: Review


class OpenAICarouselWriter:
    def __init__(self, api_key: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=120, max_retries=2)

    def write(self, *, model: str, system: str, user: str) -> tuple[CarouselOut, Usage]:
        resp = self.client.responses.parse(model=model, instructions=system, input=user, text_format=CarouselOut)
        out = resp.output_parsed
        if out is None:
            raise Unparsed("model returned no parsable slides", Usage.of(resp))
        return out, Usage.of(resp)


def count_hint(look: Look) -> str:
    lo, hi = look.slides.count if look.slides else (1, 1)
    return "exactly 1 slide" if hi == 1 else f"{lo}-{hi} slides" if lo != hi else f"exactly {lo} slides"


def normalize(out: CarouselOut, footage: Footage, music: bool) -> None:
    if not music or out.music_mood not in MUSIC_MOODS:
        out.music_mood = ""
    for s in out.slides:
        v = s.visual
        s.role = s.role.strip().lower().replace(" ", "_")
        s.heading, s.body = " ".join(s.heading.split()), s.body.strip()
        if v.source not in VISUALS:
            continue
        if v.source != "asset":
            v.asset = 0
        if v.source != "ai_image":
            v.prompt = ""
        if v.source != "chart":
            v.chart = Chart(**NO_CHART)


def problems(out: CarouselOut, t: Template, look: Look, footage: Footage) -> list[str]:
    errs: list[str] = []
    lo, hi = look.slides.count if look.slides else (1, 1)
    n = len(out.slides)
    if not lo <= n <= hi:
        errs.append(f"there are {n} slides; make {count_hint(look)}")
    if len(out.title) > 100:
        errs.append(f"the title is {len(out.title)} characters; shorten it to at most 100")
    layout = look.slides.layout if look.slides else "educational"
    aspect = look.slides.aspect if look.slides else "4:5"
    pictures = 0
    for i, s in enumerate(out.slides, 1):
        v = s.visual
        if not s.heading and not (layout == "photo" and v.source == "asset" and i > 1):
            errs.append(f"slide {i} has no heading")
        if v.source not in VISUALS:
            errs.append(f"slide {i}'s visual source \"{v.source}\" must be one of {', '.join(VISUALS)}")
            continue
        if v.source == "asset":
            a = footage.asset(v.asset)
            if a is None or a["kind"] != "image":
                errs.append(f"slide {i} uses picture #{v.asset}, which is not a picture in the footage list; "
                            "pick a listed picture, or use \"ai_image\" or \"none\"")
            else:
                pictures += 1
        elif v.source == "ai_image":
            if look.ai_images == "none":
                errs.append(f"slide {i} asks for an AI picture, which this format doesn't make; use a listed "
                            "picture, a chart or \"none\"")
            elif look.ai_images == "cover" and i > 1:
                errs.append(f"slide {i} asks for an AI picture; this format draws one only for the first slide — "
                            "use a listed picture, a chart or \"none\"")
            elif not v.prompt.strip():
                errs.append(f"slide {i}'s AI picture has no prompt; describe what to draw")
        elif v.source == "chart":
            c = v.chart
            lo_p, hi_p = CHART_POINTS.get(c.kind or "bar", (2, 6))
            if c.kind not in t.render.chart_kinds:
                errs.append(f"slide {i}'s chart kind \"{c.kind}\" must be one of {', '.join(t.render.chart_kinds)}")
            elif not c.title.strip() and c.kind != "stat":
                errs.append(f"slide {i}'s chart needs a title")
            elif not lo_p <= len(c.labels) <= hi_p or len(c.labels) != len(c.values):
                errs.append(f"slide {i}'s {c.kind} chart takes {lo_p}-{hi_p} labels, each with one value")
        has_visual = v.source in ("asset", "ai_image", "chart")
        try:
            sl.plan(s.model_dump(), i - 1, n, layout, aspect, look.font, has_visual)
        except sl.Overflow as e:
            errs.append(f"slide {i}: the {e.field} is too long to fit; shorten it")
    if t.template_id == "photo_dump_collage" and pictures < 3:
        errs.append(f"a photo dump needs at least 3 of the post's pictures; {pictures} are used — upload more "
                    "photos to the post" if len([a for a in footage.assets if a["kind"] == "image"]) < 3
                    else f"a photo dump shows at least 3 of the listed pictures; only {pictures} are used")
    return errs


def seconds(slide: dict, look: Look) -> float:
    """How long a slide stays up in the slideshow: time to read it, within the template's bounds."""
    lo, hi = look.slides.seconds if look.slides else (3.0, 7.0)
    words = len((slide.get("heading") or "").split()) + len((slide.get("body") or "").split())
    return max(lo, min(hi, 1.2 + words / 3.2))
