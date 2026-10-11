"""The idea writer: one structured LLM call that turns trends into video ideas."""

from __future__ import annotations

from pydantic import BaseModel

from ..script.llm import Usage


class Idea(BaseModel):
    title: str
    hook: str
    brief: str
    why_now: str
    sources: list[str]


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
            raise ValueError("model returned no parsable ideas")
        u = resp.usage
        return out, Usage(model=resp.model, input_tokens=getattr(u, "input_tokens", 0),
                          output_tokens=getattr(u, "output_tokens", 0))
