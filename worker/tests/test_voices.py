"""Narrator voices and styles: the catalog, Jev's pick for a post, and narration with
an OpenAI voice following a style's instructions."""

from __future__ import annotations

import wave

import httpx

from corpus import jev, voices
from corpus.handlers import narrate
from test_render_pipeline import (  # noqa: F401
    approved_narrated_post, cpu, fake_whisper, fakes, owner, pod_notes, s3, segment_cache, user,
)

ON = {"voices_enabled": ["openai:marin", "openai:onyx", "kokoro:am_michael", "kokoro:hf_alpha"],
      "voice_styles_enabled": list(voices.styles()), "narrator_voice": "am_michael", "voice_mode": "auto"}


def test_the_catalog_and_styles_load_and_hindi_has_voices():
    cat, sty = voices.catalog(), voices.styles()
    assert len(cat) >= 40 and {"breaking_news", "somber", "hindi_anchor"} <= set(sty)
    assert any("hi" in v.languages and v.engine == "kokoro" for v in cat.values())
    assert all(v.id == f"{v.engine}:{v.voice}" for v in cat.values())
    assert voices.language_code("Hindi") == "hi" and voices.language_code("English") == "en"


class VoiceJev(jev.Jev):
    def __init__(self, voice="v1", style="s0", sensitive=0.1, sure=0.8):
        super().__init__("k", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        self.answer = {"voice": {"choice": voice, "confidence": sure}, "style": {"choice": style, "confidence": sure},
                       "sensitive": {"noul": sensitive}}
        self.asked = None

    def ask(self, state, questions, images=None):
        self.asked = questions
        return self.answer


def test_jev_picks_from_the_voices_switched_on_for_the_language():
    # English: the enabled voices that speak it, in order (marin, onyx, michael): v1 = onyx
    voice, style, why = voices.choose(VoiceJev("v1", "s0"), ON, language="English", story="A rocket launches")
    enabled_styles = [s for s in ON["voice_styles_enabled"] if s != "hindi_anchor"]
    assert voice == "openai:onyx" and style == enabled_styles[0] and why.startswith("Jev's pick")
    # Hindi: only voices that speak it are offered (marin, onyx, alpha — not michael)
    j = VoiceJev("v2", "s0")
    voice, _, _ = voices.choose(j, ON, language="Hindi", story="बाढ़")
    assert voice == "kokoro:hf_alpha" and len(j.asked["voice"]["criteria"]) == 3


def test_a_tragedy_is_never_read_playfully():
    energetic = list(voices.styles()).index("energetic")
    _, style, _ = voices.choose(VoiceJev("v0", f"s{energetic}", sensitive=0.95), ON, language="English",
                                story="A bridge collapse kills 12")
    assert style == "somber"


def test_fixed_mode_and_unsure_jev_fall_back_to_the_owners_voice():
    fixed = dict(ON, voice_mode="fixed", fixed_voice="kokoro:am_michael", fixed_voice_style="documentary")
    assert voices.choose(VoiceJev(), fixed, language="English", story="x") == ("kokoro:am_michael", "documentary",
                                                                                "your voice")
    voice, style, _ = voices.choose(VoiceJev(sure=0.1), ON, language="English", story="x")
    assert voice == "kokoro:am_michael" and style == "calm_explainer"


def _wav(path, seconds=1.5, rate=24000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))


def test_an_openai_voice_reads_with_its_styles_instructions(s3, owner, user, monkeypatch):
    pid, sid = approved_narrated_post(owner, user)
    owner.execute("update posts set voice_id = 'openai:marin', voice_style = 'somber' where id = %s", (pid,))
    calls = []

    def fake_openai(key, voice, instructions, text, out):
        calls.append((voice, instructions))
        _wav(out, 1.5)
        return 1.5

    monkeypatch.setattr(narrate, "SPEAK_OPENAI", fake_openai)
    assert cpu().tick()                                                    # narrate
    assert calls and all(v == "marin" and "somber" in i.lower() for v, i in calls)
    voiced = owner.execute("select count(*) as n from shots where script_id = %s and narration_key is not null",
                           (sid,)).fetchone()["n"]
    assert voiced == len(calls)
    cost = owner.execute("select kind, model, usd_micros from costs where post_id = %s and kind = 'tts'",
                         (pid,)).fetchone()
    assert cost["model"] == voices.TTS_MODEL and cost["usd_micros"] > 0
    owner.execute("delete from jobs where post_id = %s", (pid,))
