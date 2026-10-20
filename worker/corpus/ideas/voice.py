"""Captions first (owner, 2026-10-20: "the narrator voice makes this more AI ... give
more priority to no voice, only captions, and sometimes voice").

Each channel says what share of its reels may have a narrator (channels.voice_share,
25% by default). When a format is picked for an idea (a batch, the day's automatic
pick, the owner's own idea), a narrated reel past that share becomes the channel's
captions-only reel: footage, pictures, text on screen and music. The share is
counted over the channel's reels lately (posts of the last two weeks, and the ideas
still on its deck), so a run of narrated ones is followed by silent ones until the
mix is back. Carousels and picture cards have no voice and don't count. The owner
can still pick a narrated format when they accept a card.
"""

from __future__ import annotations

CAPTIONS_WHY = "Captions only: most of this channel's reels go without a voice"


def voiced(f: dict) -> bool:
    return f.get("content_type") == "video" and (f.get("audio_source") or "none") != "none"


def silent_reel(fmts: list[dict]) -> dict | None:
    """The first captions-only reel among the formats allowed here, if any."""
    return next((f for f in fmts if f.get("content_type") == "video" and f.get("audio_source") == "none"), None)


def prompt_note(share: int) -> str:
    """For the idea writer: what the channel's mix is meant to be."""
    if share >= 100:
        return ""
    if share <= 0:
        return ("\n\n## Voice\nThis channel's reels have no narrator: pick a format without narration for every "
                "reel.")
    return (f"\n\n## Voice\nMost of this channel's reels have no narrator: about {share} in 100 do. Prefer a format "
            "without narration (footage or pictures with text on screen and music); pick a narrated one only for "
            "a story that can't be understood without someone explaining it.")


class Budget:
    """The channel's voiced and total reels lately, kept up to date as a batch picks."""

    def __init__(self, share: int, voiced: int, reels: int):
        self.share, self.voiced, self.reels = share, voiced, reels

    @classmethod
    def load(cls, c, channel_id, share: int | None) -> Budget:
        r = c.execute(
            """with picks as (
                 select format_id from posts where channel_id = %s and created_at > now() - interval '14 days'
                 union all
                 select format_id from ideas where channel_id = %s and status = 'new'
                    and created_at > now() - interval '3 days')
               select count(*) filter (where f.audio_source <> 'none') as voiced, count(*) as reels
                 from picks p join formats f on f.id = p.format_id
                where f.content_type = 'video'""", (channel_id, channel_id)).fetchone()
        return cls(25 if share is None else int(share), int(r["voiced"]), int(r["reels"]))

    def allows_voice(self) -> bool:
        """One more narrated reel stays within the share."""
        return (self.voiced + 1) * 100 <= self.share * (self.reels + 1)

    def fit(self, chosen: dict, fmts: list[dict], why: str) -> tuple[dict, str]:
        """The format to use (and why): `chosen`, or the captions-only reel when a
        narrated one is past the share. Counts the result."""
        if voiced(chosen) and not self.allows_voice():
            alt = silent_reel(fmts)
            if alt is not None:
                chosen, why = alt, CAPTIONS_WHY
        if chosen.get("content_type") == "video":
            self.reels += 1
            self.voiced += voiced(chosen)
        return chosen, why
