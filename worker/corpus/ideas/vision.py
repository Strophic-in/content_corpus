"""Looking at a post before it reaches the owner's screen.

moderate(): OpenAI's moderation model (free) on the post's text and preview
picture, before any media is downloaded. Sexual content removes the idea;
graphic violence keeps the story but not its pictures.

describe(): one call to the owner's chosen vision model with a contact sheet
(nine frames spread over the video, in one image — far cheaper than nine images),
so the card, and later the script, know what the video shows, and whether it
carries a news outlet's logo or watermark (a rights warning on the card).
"""

from __future__ import annotations

import base64
from pathlib import Path

from pydantic import BaseModel

from ..script.llm import Unparsed, Usage

MODERATION_MODEL = "omni-moderation-latest"
REMOVE = {"sexual", "sexual/minors"}              # never shown at all
NO_MEDIA = {"violence/graphic", "self-harm", "self-harm/intent", "self-harm/instructions"}


class VideoAnalysis(BaseModel):
    summary: str                    # what happens, in two or three sentences
    moments: list[str]              # what each part shows, in order
    logos_or_watermarks: bool       # a broadcaster's logo, a watermark, a channel's name burned in
    logo_names: list[str]
    identifiable_people: bool
    graphic: bool                   # injury, blood, a dead body
    spoken_language: str            # "none" when nobody speaks


class Moment(BaseModel):
    at: float                       # seconds into the video
    what: str


class FootageAnalysis(BaseModel):
    """A reel's footage, logged for the script writer (analyze_asset)."""
    summary: str
    moments: list[Moment]           # what happens when, in order ([] for a picture)
    on_screen_text: list[str]
    logos_or_watermarks: bool
    logo_names: list[str]
    identifiable_people: bool
    graphic: bool


class SafetyCheck(BaseModel):
    sexual: bool
    sexual_minors: bool
    graphic_violence: bool
    self_harm: bool


SAFETY_INSTRUCTIONS = ("You screen social-media posts before a news editor sees them. Answer only from what is "
                       "shown: is any of it sexual (nudity included), sexual content involving minors, graphic "
                       "violence (injury, blood, a dead body), or self-harm?")


def data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


class OpenAIVision:
    def __init__(self, api_key: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=90, max_retries=2)

    def moderate(self, text: str, image: Path | None) -> dict:
        parts: list[dict] = [{"type": "text", "text": text[:4000]}]
        if image is not None:
            parts.append({"type": "image_url", "image_url": {"url": data_url(image)}})
        r = self.client.moderations.create(model=MODERATION_MODEL, input=parts).results[0]
        cats = {k for k, v in r.categories.model_dump(by_alias=True).items() if v}
        return {"flagged": bool(r.flagged), "categories": sorted(cats)}

    def safety(self, model: str, text: str, image: Path | None) -> tuple[dict, Usage]:
        """The moderation verdict from a chat model, for keys that may not call /moderations."""
        content: list[dict] = [{"type": "input_text", "text": text[:4000]}]
        if image is not None:
            content.append({"type": "input_image", "image_url": data_url(image), "detail": "low"})
        resp = self.client.responses.parse(model=model, instructions=SAFETY_INSTRUCTIONS,
                                           input=[{"role": "user", "content": content}], text_format=SafetyCheck)
        out = resp.output_parsed
        if out is None:
            raise Unparsed("the safety check returned no verdict", Usage.of(resp))
        cats = [name for name, hit in (("sexual", out.sexual), ("sexual/minors", out.sexual_minors),
                                       ("violence/graphic", out.graphic_violence), ("self-harm", out.self_harm))
                if hit]
        return {"flagged": bool(cats), "categories": cats, "by": model}, Usage.of(resp)

    def describe(self, model: str, sheet: Path, title: str) -> tuple[VideoAnalysis, Usage]:
        resp = self.client.responses.parse(
            model=model,
            instructions=("You describe short videos for a news editor. The image is a 3x3 contact sheet of "
                          "frames taken in order from one video (left to right, top to bottom). Be factual; "
                          "do not guess names of people."),
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": f"The post's title: {title[:300]}"},
                {"type": "input_image", "image_url": data_url(sheet), "detail": "low"}]}],
            text_format=VideoAnalysis)
        out = resp.output_parsed
        if out is None:
            raise Unparsed("the vision model returned no analysis", Usage.of(resp))
        return out, Usage.of(resp)


    def analyze(self, model: str, sheet: Path, title: str, times: list[float] | None = None,
                transcript: str = "") -> tuple[FootageAnalysis, Usage]:
        """Footage for a reel: a video's contact sheet (frame k at times[k]), or one picture."""
        if times:
            what = (f"The image is a contact sheet of {len(times)} frames from one video, in reading order "
                    f"(left to right, top to bottom). The frames are at these seconds: "
                    + ", ".join(f"{t:.1f}" for t in times) + ". Give `moments` with the time each one starts.")
        else:
            what = "The image is one picture; `moments` is []."
        content: list[dict] = [{"type": "input_text", "text": f"The story: {title[:300]}\n{what}"}]
        if transcript:
            content.append({"type": "input_text", "text": f"What is said in the video:\n{transcript[:3000]}"})
        content.append({"type": "input_image", "image_url": data_url(sheet), "detail": "high" if times else "low"})
        resp = self.client.responses.parse(
            model=model,
            instructions=("You log footage for a news video editor, factually: what happens and when, any text on "
                          "screen, a broadcaster's logo or a watermark, whether identifiable people are shown, "
                          "and anything graphic (injury, blood, a dead body). Never guess names of people. "
                          # Live: 16 frames of a spire burning were all logged "burning", and the
                          # moment it fell (between 10 and 12 s) went unnoticed - so the reel cut
                          # away just before it.
                          "Compare each frame with the one before: name the moment something changes - a "
                          "collapse, an explosion, a fall, a crowd surging, a vehicle arriving - at the time of the "
                          "first frame that shows it, starting with KEY: (\"KEY: the spire collapses\"). Those "
                          "are the moments an editor builds the video around."),
            input=[{"role": "user", "content": content}], text_format=FootageAnalysis)
        out = resp.output_parsed
        if out is None:
            raise Unparsed("the vision model returned no footage log", Usage.of(resp))
        return out, Usage.of(resp)


def verdict(mod: dict) -> str:
    """keep | no_media | remove."""
    cats = set(mod.get("categories") or [])
    if cats & REMOVE:
        return "remove"
    if cats & NO_MEDIA:
        return "no_media"
    return "keep"
