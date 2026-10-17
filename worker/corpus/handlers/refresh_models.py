"""ideas/refresh_models — re-read the models the owner's OpenAI key can use."""

from __future__ import annotations

from .. import openai_models
from ..runner import Handler, JobContext, Permanent


def run(ctx: JobContext) -> dict:
    ids = openai_models.refresh(ctx.job["user_id"])
    if ids is None:
        raise Permanent("Add your OpenAI API key in Settings first.", stage="config")
    return {"models": len(ids)}


HANDLER = Handler(run=run)
