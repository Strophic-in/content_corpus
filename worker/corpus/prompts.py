"""Prompt templates: the defaults shipped in prompts/, and filling their placeholders.

The prompts a user edits live in their formats (the prompt library); the files are
the defaults a new format starts from, and what posts without a format still use.
Placeholders are `{name}`; only known names are filled, so a prompt the user writes
may contain any other braces (a JSON example, say) without breaking.
"""

from __future__ import annotations

import re

from .config import settings

DEFAULTS = {
    "script:kokoro": "script_narrated.md",
    "script:ltx_native": "script_reel.md",
    "ideas": "ideas.md",
    "visual_style": "visual_style.md",
}


def default(name: str) -> str:
    return (settings().prompts_dir / DEFAULTS[name]).read_text(encoding="utf-8").strip()


def fill(template: str, values: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0),
                  template)


def _words(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def contains(text: str, part: str) -> bool:
    """Whether `part` already appears in `text`, ignoring case and punctuation."""
    p = _words(part)
    return bool(p) and p in _words(text)
