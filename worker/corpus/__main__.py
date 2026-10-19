"""Entry point:  python -m corpus   (lane from CORPUS_LANE, default cpu)."""

from __future__ import annotations

import logging

from .config import settings
from . import upkeep
from .handlers import (analyze_asset, assemble, attach_media, auto_pick, build_segment, check_sources, fetch_asset,
                       make_ai_image, narrate, package_post, plan_shots, prepare_shot, publish_post, refresh_models,
                       render_post,
                       render_slides, research_post, suggest_ideas, write_script)
from .runner import Runner

HANDLERS = {
    "cpu": {
        "write_script": write_script.HANDLER,
        "plan_shots": plan_shots.HANDLER,
        "narrate": narrate.HANDLER,
        "build_segment": build_segment.HANDLER,
        "assemble": assemble.HANDLER,
        # Footage: what a post's clip or picture shows, and shots made from it or from stock.
        "analyze_asset": analyze_asset.HANDLER,
        "prepare_shot": prepare_shot.HANDLER,
        "make_ai_image": make_ai_image.HANDLER,
        # Carousels and cards: slides for Instagram, a slideshow for YouTube.
        "render_slides": render_slides.HANDLER,
        # A finished reel's title, caption, hashtags, first comment and cover.
        "package_post": package_post.HANDLER,
    },
    # The only process that contacts Reddit and arbitrary URLs: its rate-limit waits
    # and downloads never hold up scripts, segments or assembly.
    "ideas": {
        "suggest_ideas": suggest_ideas.HANDLER,
        "auto_pick": auto_pick.HANDLER,                       # the day's post when the owner picked none
        "idea_from_video": suggest_ideas.HANDLER,           # Explore YouTube → "Make an idea"
        "attach_media": attach_media.HANDLER,
        "check_sources": check_sources.CHECK_HANDLER,
        "suggest_sources": check_sources.SUGGEST_HANDLER,
        "refresh_models": refresh_models.HANDLER,
        "fetch_asset": fetch_asset.HANDLER,
        "research_post": research_post.HANDLER,
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
