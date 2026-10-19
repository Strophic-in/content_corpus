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
                                   tuple(s.get("best_for") or ()))
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
    q = dict(SENSITIVE)
    if len(vs) > 1:
        q["voice"] = {"type": "choice", "instructions": "Which narrator voice suits `story` best, for this channel "
                                                        "and `category`?",
                      "criteria": {f"v{i}": f"{v.name}: {v.gender}, {v.accent} accent; {v.tone}. "
                                            f"Best for {', '.join(v.best_for)}." for i, v in enumerate(vs)}}
    if len(ss) > 1:
        q["style"] = {"type": "choice", "instructions": "Which way of reading `story` aloud fits it best?",
                      "criteria": {f"s{i}": f"{s.name}: {s.description} Best for {', '.join(s.best_for)}."
                                   for i, s in enumerate(ss)}}
    try:
        a = judge.ask({"story": story[:1500], "category": category or "news", "format": template or "short video"}, q)
    except Exception as e:  # noqa: BLE001 - a voice is still needed
        log.warning("voice choice: %s", e)
        return first.id, _default_style(ss, lang).style_id, "your voice" if first is own else "the first voice switched on"
    voice, vconf = _pick(a.get("voice"), "v", vs)
    style, sconf = _pick(a.get("style"), "s", ss)
    voice = voice if voice and vconf >= SURE else first
    style = style if style and sconf >= SURE else _default_style(ss, lang)
    if yes(a.get("sensitive"), 0.0) >= 0.6:       # a tragedy is never read playfully
        somber = next((s for s in ss if s.sensitive), None)
        if somber:
            style = somber
        elif style.playful:
            style = next((s for s in ss if not s.playful), style)
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
