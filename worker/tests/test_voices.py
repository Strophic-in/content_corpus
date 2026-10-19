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
    assert len(cat) >= 40 and len(sty) >= 24 and {"breaking_news", "somber", "horror", "funny", "cringe"} <= set(sty)
    assert all(s.group for s in sty.values()) and sty["horror"].dark and sty["funny"].playful
    assert any("hi" in v.languages and v.engine == "kokoro" for v in cat.values())
    assert all(v.id == f"{v.engine}:{v.voice}" for v in cat.values())
    assert voices.language_code("Hindi") == "hi" and voices.language_code("English") == "en"


class VoiceJev(jev.Jev):
    """Answers the style question, then the voice question (two calls)."""

    def __init__(self, voice="v1", style="breaking_news", sensitive=0.1, sure=0.8):
        super().__init__("k", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        self.voice, self.style, self.sensitive, self.sure = voice, style, sensitive, sure
        self.asked = []

    def ask(self, state, questions, images=None):
        self.asked.append((state, questions))
        if "style" in questions and "voice" not in questions:
            names = [c.split(" (")[0] for c in questions["style"]["criteria"].values()]
            want = voices.styles()[self.style].name
            return {"style": {"choice": f"s{names.index(want)}", "confidence": self.sure},
                    "sensitive": {"noul": self.sensitive}}
        return {"voice": {"choice": self.voice, "confidence": self.sure}}


def test_jev_picks_the_style_then_a_voice_that_suits_it():
    # A plain style: any voice speaking the language (marin, onyx, michael): v1 = onyx
    voice, style, why = voices.choose(VoiceJev("v1", "breaking_news"), ON, language="English", story="A rocket launches")
    assert (voice, style) == ("openai:onyx", "breaking_news") and why.startswith("Jev's pick")
    # A style that needs acting goes only to the voices that can act (marin, onyx)
    j = VoiceJev("v0", "horror")
    voice, style, _ = voices.choose(j, ON, language="English", story="The haunted fort")
    state, q = j.asked[-1]
    assert style == "horror" and voice == "openai:marin" and len(q["voice"]["criteria"]) == 2
    assert "Horror" in state["style"] and "deep" in state["style"]
    # Hindi: only voices that speak it (marin, onyx, alpha)
    j = VoiceJev("v2", "hindi_anchor")
    voice, style, _ = voices.choose(j, ON, language="Hindi", story="बाढ़")
    assert (voice, style) == ("kokoro:hf_alpha", "hindi_anchor") and len(j.asked[-1][1]["voice"]["criteria"]) == 3


def test_a_tragedy_is_never_read_playfully_or_as_horror():
    for wanted in ("funny", "horror", "cringe"):
        _, style, _ = voices.choose(VoiceJev("v0", wanted, sensitive=0.95), ON, language="English",
                                    story="A bridge collapse kills 12")
        assert style == "somber", wanted


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
