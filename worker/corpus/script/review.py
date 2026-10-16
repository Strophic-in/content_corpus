"""The desk editor: one more read of a script before Automatic mode approves it.

A model can't audit the facts in the same pass that writes them (TrendCaster's
lesson), so this is a separate call with the script and the material it came
from. It looks only for problems serious enough to stop an unattended post;
style is the writer's business. When it finds one — or when it can't be reached —
the post waits for the owner's review instead of being approved.
"""

from __future__ import annotations

from pydantic import BaseModel

from .llm import Unparsed, Usage

INSTRUCTIONS = """You are the desk editor of a short-video channel. A script is about to be
published without a human reading it first. Compare it with the source material and
report only problems serious enough to stop it:

- a fact, number, name, date or quote that the sources do not support;
- a claim stated as certain that the sources report as alleged or unconfirmed;
- a named victim of sexual violence, or a named minor;
- someone presented as guilty before a verdict;
- partisan framing, or content that could inflame a community;
- graphic description of injury or death;
- anything dangerous to copy.

Return ok = true when none of these is present (style and wording are not your job).
Otherwise ok = false, with each problem as one short, specific line."""


class DeskReview(BaseModel):
    ok: bool
    issues: list[str]


class OpenAIReviewer:
    def __init__(self, api_key: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=90, max_retries=2)

    def review(self, *, model: str, script: str, sources: str) -> tuple[DeskReview, Usage]:
        resp = self.client.responses.parse(
            model=model, instructions=INSTRUCTIONS,
            input=f"## Source material\n{sources}\n\n## Script (JSON)\n{script}",
            text_format=DeskReview)
        out = resp.output_parsed
        if out is None:
            raise Unparsed("the desk editor returned no verdict", Usage.of(resp))
        return out, Usage.of(resp)
