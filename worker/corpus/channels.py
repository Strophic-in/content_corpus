"""A channel's identity, as the prompts see it."""

from __future__ import annotations

PROFILE_KEYS = ("channel_name", "channel_niche", "channel_audience", "channel_voice", "script_language")


def profile(c, user_id: str, channel_id=None) -> dict:
    """{channel_name, channel_niche, channel_audience, channel_voice, script_language}
    for this channel (or the user's default one). Posts made before channels existed
    fall back to the old single profile in app_settings."""
    ch = None
    if channel_id:
        ch = c.execute("select * from channels where id = %s", (channel_id,)).fetchone()
    if ch is None:
        ch = c.execute("select * from channels where user_id = %s and is_default", (user_id,)).fetchone()
    if ch is not None:
        return {"channel_name": ch["name"], "channel_niche": ch["niche"], "channel_audience": ch["audience"],
                "channel_voice": ch["voice"], "script_language": ch["language"], "channel_id": ch["id"],
                "timezone": ch["timezone"]}
    st = c.execute("select * from app_settings where user_id = %s", (user_id,)).fetchone() or {}
    return {k: st.get(k) for k in PROFILE_KEYS}
