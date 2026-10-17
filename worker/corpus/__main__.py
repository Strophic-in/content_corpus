"""Entry point:  python -m corpus   (lane from CORPUS_LANE, default cpu)."""

from __future__ import annotations

import logging

from .config import settings
from . import upkeep
from .handlers import (assemble, attach_media, build_segment, check_sources, narrate, plan_shots, publish_post,
                       refresh_models, render_post, suggest_ideas, write_script)
from .runner import Runner

HANDLERS = {
    "cpu": {
        "write_script": write_script.HANDLER,
        "plan_shots": plan_shots.HANDLER,
        "narrate": narrate.HANDLER,
        "build_segment": build_segment.HANDLER,
        "assemble": assemble.HANDLER,
    },
    # The only process that contacts Reddit and arbitrary URLs: its rate-limit waits
    # and downloads never hold up scripts, segments or assembly.
    "ideas": {
        "suggest_ideas": suggest_ideas.HANDLER,
        "attach_media": attach_media.HANDLER,
        "check_sources": check_sources.CHECK_HANDLER,
        "suggest_sources": check_sources.SUGGEST_HANDLER,
        "refresh_models": refresh_models.HANDLER,
    },
    # The gpu lane runs on the same always-on box as cpu, as its own process: it
    # rents and drives the Race GPU remotely, and a long render must not block
    # script writing.
    "gpu": {
        "render_post": render_post.HANDLER,
    },
    # Its own process too: an upload must never wait behind a render or a script.
    "publish": {
        "publish_post": publish_post.HANDLER,
    },
}

# Housekeeping each lane does on every tick, besides claiming work.
UPKEEP = {
    "publish": publish_post.upkeep,
    "ideas": upkeep.ideas_lane,
}


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    lane = settings().lane
    Runner(lane, HANDLERS[lane], upkeep=UPKEEP.get(lane)).run_forever()


if __name__ == "__main__":
    main()
