"""Posting finished reels to YouTube and Instagram (the publish lane).

Each platform module takes an httpx.Client, so tests drive it against a fake API.
Every step is written to publish_attempts before it is taken (attempts.py): a run
that dies mid-upload is resumed or reconciled by the next one, never re-posted.
"""
