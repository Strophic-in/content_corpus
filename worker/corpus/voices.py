"""Narrator voices, and Jev's pick of one for a post.

prompts/voices/catalog.json lists every voice: engine kokoro (free, on this CPU,
English American and British, a few Hindi) or openai (gpt-4o-mini-tts: speaks English
and Hindi well, follows directions, billed to the owner's key, about ₹1 a reel).

Free first: an English post is read by a free voice; a Hindi post by an AI voice (the
free Hindi voices are the fallback). The owner switches voices on in Settings →
Voices; Jev picks one of those for the story (it reads each voice's description — it
cannot hear them). An AI voice is also told how to sound: a short direction written
from the script itself (direction()), so the tone follows the content — urgent for
breaking news, calm for science, slow and respectful for a tragedy. A free voice
only takes the owner's speed.
"""

from __future__ import annotations

import functools
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .jev import Jev

log = logging.getLogger("corpus.voices")

TTS_MODEL = "gpt-4o-mini-tts"
USD_PER_MINUTE = 0.015            # gpt-4o-mini-tts, about
SURE = 0.4
DEFAULT_DIRECTION = ("Voice: a clear, natural narrator for a short news video. Tone: confident and engaging. "
                     "Pacing: brisk but easy to follow.")


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


@functools.lru_cache(maxsize=1)
def catalog() -> dict[str, Voice]:
    raw = json.loads((settings().prompts_dir / "voices" / "catalog.json").read_text(encoding="utf-8"))
    return {v["id"]: Voice(v["id"], v["engine"], v["voice"], v["name"], v["gender"], v["accent"],
                           tuple(v["languages"]), v["tone"], tuple(v["best_for"])) for v in raw["voices"]}


def language_code(language: str | None) -> str:
    """The channel's script language ("English", "Hindi", "hi") → "en" | "hi"."""
    return "hi" if (language or "").strip().lower() in ("hindi", "hi", "हिंदी", "हिन्दी") else "en"


def _pool(st: dict, lang: str) -> list[Voice]:
    """The voices switched on that speak `lang`, the preferred engine only: free for
    English, AI for Hindi — the other engine when none of the preferred is on."""
    cat = catalog()
    on = [cat[v] for v in (st.get("voices_enabled") or []) if v in cat and lang in cat[v].languages]
    want = "openai" if lang == "hi" else "kokoro"
    preferred = [v for v in on if v.engine == want]
    if preferred or on:
        return preferred or on
    return [v for v in cat.values() if lang in v.languages and v.engine == want][:1] or \
        [v for v in cat.values() if lang in v.languages][:1]


def choose(judge: Jev | None, st: dict, *, language: str | None, story: str, category: str = "",
           template: str = "") -> tuple[str, str]:
    """(voice id, why) for a post."""
    lang = language_code(language)
    pool = _pool(st, lang)
    fixed = catalog().get(st.get("fixed_voice") or "")
    if st.get("voice_mode") == "fixed" and fixed and lang in fixed.languages:
        return fixed.id, "your voice"
    own = fixed or catalog().get(f"kokoro:{st.get('narrator_voice') or ''}")
    first = own if own in pool else pool[0]
    if judge is None or len(pool) < 2:
        return first.id, "your voice" if first is own else "the first voice switched on"
    q = {"voice": {"type": "choice", "instructions": "Which narrator voice suits `story` best, for this `category`?",
                   "criteria": {f"v{i}": f"{v.name}: {v.gender}, {v.accent} accent; {v.tone}. "
                                         f"Best for {', '.join(v.best_for)}." for i, v in enumerate(pool)}}}
    try:
        a = judge.ask({"story": story[:1500], "category": category or "news", "format": template or "short video"}, q)
        pick = a.get("voice") or {}
        ch, conf = str(pick.get("choice") or ""), float(pick.get("confidence") or 0)
        if ch.startswith("v") and ch[1:].isdigit() and int(ch[1:]) < len(pool) and conf >= SURE:
            return pool[int(ch[1:])].id, f"Jev's pick ({round(conf * 100)}% sure)"
    except Exception as e:  # noqa: BLE001 - a voice is still needed
        log.warning("voice choice: %s", e)
    return first.id, "your voice" if first is own else "the first voice switched on"


DIRECTION_PROMPT = """You direct a narrator for a short vertical video. Read the script and write how it should be
spoken, in 2-3 short sentences: "Voice: …. Tone: …. Pacing: …." Match the content: urgent and crisp for breaking
news, warm and curious for science, slow, low and respectful for deaths or disasters, playful for light or funny
stories, gripping for crime or mystery. The language of the script is {language}; say so if it is not English
("Speak in natural Hindi …"). Never ask for an imitation of a real person. Reply with the direction only."""


def direction(api_key: str, model: str, script: str, language: str | None) -> tuple[str, object | None]:
    """How an AI voice should read `script` (and the model call's usage, for the ledger)."""
    from openai import OpenAI

    try:
        client = OpenAI(api_key=api_key, timeout=45, max_retries=1)
        r = client.responses.create(model=model, instructions=DIRECTION_PROMPT.format(language=language or "English"),
                                    input=script[:3000])
        from .script.llm import Usage
        return ((r.output_text or "").strip()[:600] or DEFAULT_DIRECTION), Usage.of(r)
    except Exception as e:  # noqa: BLE001 - a plain direction still reads well
        log.warning("voice direction: %s", e)
        return DEFAULT_DIRECTION, None


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
