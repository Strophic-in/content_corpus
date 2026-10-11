"""Entry point:  python -m corpus   (lane from CORPUS_LANE, default cpu)."""

from __future__ import annotations

import logging

from .config import settings
from .handlers import assemble, build_segment, narrate, plan_shots, render_post, write_script
from .runner import Runner

HANDLERS = {
    "cpu": {
        "write_script": write_script.HANDLER,
        "plan_shots": plan_shots.HANDLER,
        "narrate": narrate.HANDLER,
        "build_segment": build_segment.HANDLER,
        "assemble": assemble.HANDLER,
    },
    # The gpu lane runs on the same always-on box as cpu, as its own process: it
    # rents and drives the Race GPU remotely, and a long render must not block
    # script writing.
    "gpu": {
        "render_post": render_post.HANDLER,
    },
    "publish": {},
}


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    lane = settings().lane
    Runner(lane, HANDLERS[lane]).run_forever()


if __name__ == "__main__":
    main()
