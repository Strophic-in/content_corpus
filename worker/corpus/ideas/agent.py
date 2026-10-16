"""The idea writer: one structured LLM call that turns trends into video ideas."""

from __future__ import annotations

from pydantic import BaseModel

from ..script.llm import Unparsed, Usage


class Idea(BaseModel):
    title: str
    hook: str
    brief: str
    why_now: str
    # Numbers of the trend items it came from (the list in the prompt is numbered);
    # their links, posts and media follow the idea onto its card.
    items: list[int]


class IdeasOut(BaseModel):
    ideas: list[Idea]


class OpenAIIdeaWriter:
    def __init__(self, api_key: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=180, max_retries=2)

    def write(self, *, model: str, system: str, user: str) -> tuple[IdeasOut, Usage]:
        resp = self.client.responses.parse(model=model, instructions=system, input=user, text_format=IdeasOut)
        out = resp.output_parsed
        if out is None:
            raise Unparsed("model returned no parsable ideas", Usage.of(resp))
        return out, Usage.of(resp)
