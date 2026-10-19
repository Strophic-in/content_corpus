"""Narrator voices and voice styles, and Jev's pick of both for a post.

  prompts/voices/catalog.json     every voice: engine (kokoro: free, on this CPU,
                                  speed only · openai: gpt-4o-mini-tts, follows a
                                  style's instructions, English and Hindi), who it
                                  sounds like, what it suits
  prompts/voice_styles/<id>.json  ready-made deliveries — breaking news, calm
                                  explainer, documentary, somber, energetic,
                                  storyteller, conversational, Hindi news anchor:
                                  instructions (openai) and a pace (both)

The owner switches voices and styles on in Settings → Voices. For each narrated post
(narrate.py) Jev picks, from those, the voice that fits the channel's language and
the story, and the style — never a playful one for a tragedy. "Fixed" mode: always
the owner's one voice. The pick is kept on the post (voice_id, voice_style, voice_why).
"""

from __future__ import annotations

import functools
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .jev import Jev, yes
from .config import settings

log = logging.getLogger("corpus.voices")

TTS_MODEL = "gpt-4o-mini-tts"
USD_PER_MINUTE = 0.015            # gpt-4o-mini-tts, about
SURE = 0.4


@dataclass(frozen=True)
class Voice:
    id: str
    engine: str
    voice: str
    name: str
    gender: str
    accent: str
    languages: tuple[str, ...]
    tone: str
    best_for: tuple[str, ...]


@dataclass(frozen=True)
class Style:
    style_id: str
    name: str
    description: str
    instructions: str
    speed: float
    playful: bool = False
    sensitive: bool = False
    languages: tuple[str, ...] = field(default=())
    best_for: tuple[str, ...] = field(default=())
    group: str = ""
    dark: bool = False            # horror and the like: never for a real tragedy
    expressive: bool = False      # needs acting: only the directable (OpenAI) voices can do it
    voice_hint: str = ""          # what kind of voice suits it ("deep, low, breathy")


@functools.lru_cache(maxsize=1)
def catalog() -> dict[str, Voice]:
    raw = json.loads((settings().prompts_dir / "voices" / "catalog.json").read_text(encoding="utf-8"))
    out = {}
    for v in raw["voices"]:
        out[v["id"]] = Voice(v["id"], v["engine"], v["voice"], v["name"], v["gender"], v["accent"],
                             tuple(v["languages"]), v["tone"], tuple(v["best_for"]))
    return out


@functools.lru_cache(maxsize=1)
def styles() -> dict[str, Style]:
    out = {}
    for f in sorted((settings().prompts_dir / "voice_styles").glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        out[s["style_id"]] = Style(s["style_id"], s["name"], s["description"], s["instructions"], float(s["speed"]),
                                   bool(s.get("playful")), bool(s.get("sensitive")), tuple(s.get("languages") or ()),
                                   tuple(s.get("best_for") or ()), s.get("group", ""), bool(s.get("dark")),
                                   bool(s.get("expressive")), s.get("voice_hint", ""))
    return out


def language_code(language: str | None) -> str:
    """The channel's script language ("English", "Hindi", "hi") → "en" | "hi"."""
    return "hi" if (language or "").strip().lower() in ("hindi", "hi", "हिंदी", "हिन्दी") else "en"


def _usable(st: dict, lang: str) -> tuple[list[Voice], list[Style]]:
    cat, sty = catalog(), styles()
    vs = [cat[v] for v in (st.get("voices_enabled") or []) if v in cat and lang in cat[v].languages]
    ss = [sty[s] for s in (st.get("voice_styles_enabled") or []) if s in sty
          and (not sty[s].languages or lang in sty[s].languages)]
    if not vs:            # nothing switched on speaks it: any voice that does
        vs = [v for v in cat.values() if lang in v.languages][:1]
    if not ss:
        ss = [sty["hindi_anchor" if lang == "hi" else "calm_explainer"]]
    return vs, ss


def _default_style(ss: list[Style], lang: str) -> Style:
    want = "hindi_anchor" if lang == "hi" else "calm_explainer"
    return next((s for s in ss if s.style_id == want), ss[0])


SENSITIVE = {"sensitive": {"type": "noul", "instructions": "Is `story` about deaths, a disaster, violence, a crime "
                                                           "with victims, or another tragedy?"}}


def choose(judge: Jev | None, st: dict, *, language: str | None, story: str, category: str = "",
           template: str = "") -> tuple[str, str, str]:
    """(voice id, style id, why) for a post."""
    lang = language_code(language)
    vs, ss = _usable(st, lang)
    fixed = catalog().get(st.get("fixed_voice") or "")
    if st.get("voice_mode") == "fixed" and fixed and lang in fixed.languages:
        style = styles().get(st.get("fixed_voice_style") or "") or _default_style(ss, lang)
        return fixed.id, style.style_id, "your voice"
    own = fixed or catalog().get(f"kokoro:{st.get('narrator_voice') or ''}")
    first = own if own and lang in own.languages else vs[0]
    if judge is None or (len(vs) < 2 and len(ss) < 2):
        return first.id, _default_style(ss, lang).style_id, "your voice" if first is own else "the first voice switched on"
    # Jev can't hear a voice: it reads each one's description. So the style is picked
    # first (how the story should be read), then the voice that suits that style.
    state = {"story": story[:1500], "category": category or "news", "format": template or "short video"}
    q = dict(SENSITIVE)
    if len(ss) > 1:
        q["style"] = {"type": "choice", "instructions": "How should `story` be read aloud, for this `category`?",
                      "criteria": {f"s{i}": f"{x.name} ({x.group}): {x.description} Best for {', '.join(x.best_for)}."
                                   for i, x in enumerate(ss)}}
    try:
        a = judge.ask(state, q)
    except Exception as e:  # noqa: BLE001 - a voice is still needed
        log.warning("voice style choice: %s", e)
        return first.id, _default_style(ss, lang).style_id, "your voice" if first is own else "the first voice switched on"
    style, sconf = _pick(a.get("style"), "s", ss)
    style = style if style and sconf >= SURE else _default_style(ss, lang)
    if yes(a.get("sensitive"), 0.0) >= 0.6:       # a real tragedy: never playful, never horror
        if style.playful or style.dark:
            style = next((x for x in ss if x.sensitive), None) or next(
                (x for x in ss if not x.playful and not x.dark), _default_style(ss, lang))
    # A style that needs acting goes to the voices that can act it, when any are on.
    actors = [v for v in vs if v.engine == "openai"]
    pool = actors if style.expressive and actors else vs
    voice, vconf = (pool[0], 1.0) if len(pool) < 2 else (None, 0.0)
    if len(pool) > 1:
        try:
            b = judge.ask({**state, "style": f"{style.name}: {style.description} It suits a voice that is "
                                              f"{style.voice_hint or 'clear'}."},
                          {"voice": {"type": "choice", "instructions": "Which narrator voice reads `story` best in "
                                                                       "`style`?",
                                     "criteria": {f"v{i}": f"{v.name}: {v.gender}, {v.accent} accent; {v.tone}. "
                                                           f"Best for {', '.join(v.best_for)}."
                                                  for i, v in enumerate(pool)}}})
            voice, vconf = _pick(b.get("voice"), "v", pool)
        except Exception as e:  # noqa: BLE001
            log.warning("voice choice: %s", e)
    if not voice or vconf < SURE:
        voice = first if first in pool else pool[0]
    return voice.id, style.style_id, f"Jev's pick ({round(100 * min(vconf or 1, sconf or 1))}% sure)"


def _pick(answer: dict | None, prefix: str, items: list):
    if not answer or len(items) < 2:
        return (items[0] if items else None), 1.0
    ch = str(answer.get("choice") or "")
    if ch.startswith(prefix) and ch[1:].isdigit() and int(ch[1:]) < len(items):
        return items[int(ch[1:])], float(answer.get("confidence") or 0)
    return None, 0.0


def speak_openai(api_key: str, voice: str, instructions: str, text: str, out: Path) -> float:
    """`text` read by an OpenAI voice following `instructions`, as WAV; its length in seconds."""
    import soundfile as sf
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=90, max_retries=2)
    r = client.audio.speech.create(model=TTS_MODEL, voice=voice, input=text, instructions=instructions,
                                   response_format="wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    info = sf.info(str(out))
    return info.frames / info.samplerate
