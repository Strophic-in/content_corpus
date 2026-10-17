"""OpenAI image generation, for AI versions of a post's pictures.

The picture is drawn from words only — what the original shows (its logged
description) in the channel's look — never from the original's pixels: an AI
version is a new picture of the same scene, not a filtered copy of someone's photo.
The reply carries token counts (text in, image out), which the cost ledger prices
like any other model call.
"""

from __future__ import annotations

import base64

from .script.llm import Usage

SIZE = "1024x1536"          # portrait 2:3: fills a 9:16 reel with a slight crop


class OpenAIImages:
    def __init__(self, api_key: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=180, max_retries=2)

    def generate(self, *, model: str, prompt: str, quality: str = "medium") -> tuple[bytes, Usage]:
        resp = self.client.images.generate(model=model, prompt=prompt, size=SIZE, quality=quality, n=1)
        u = getattr(resp, "usage", None)
        usage = Usage(model=model, input_tokens=getattr(u, "input_tokens", 0) or 0,
                      output_tokens=getattr(u, "output_tokens", 0) or 0)
        return base64.b64decode(resp.data[0].b64_json), usage


def prompt_for(description: str, look: str, topic: str) -> str:
    return (f"A vertical illustration for a short news video about: {topic.strip()[:200]}.\n"
            f"Show this scene: {description.strip()[:1200]}\n"
            f"Style: {look.strip()[:600] or 'clean editorial illustration, soft light'}.\n"
            "No text, captions, logos or watermarks. People appear as generic figures, never a recognisable "
            "real person. Nothing graphic.")
