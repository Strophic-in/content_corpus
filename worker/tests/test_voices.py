"""Narrator voices: the catalog, Jev's pick for a post (free voices first for English,
AI voices for Hindi), and narration with an AI voice told how to sound by a direction
written from the script."""

from __future__ import annotations

import wave

import httpx

from corpus import jev, voices
from corpus.handlers import narrate
from test_render_pipeline import (  # noqa: F401
    approved_narrated_post, cpu, fake_whisper, fakes, owner, pod_notes, s3, segment_cache, user,
)

ON = {"voices_enabled": ["openai:marin", "openai:onyx", "kokoro:am_michael", "kokoro:bf_emma", "kokoro:hf_alpha"],
      "narrator_voice": "am_michael", "voice_mode": "auto"}


def test_the_catalog_loads_and_hindi_has_voices():
    cat = voices.catalog()
    assert len(cat) >= 40
    assert any("hi" in v.languages and v.engine == "kokoro" for v in cat.values())
    assert all("hi" in v.languages for v in cat.values() if v.engine == "openai")
    assert all(v.id == f"{v.engine}:{v.voice}" for v in cat.values())
    assert voices.language_code("Hindi") == "hi" and voices.language_code("English") == "en"


class VoiceJev(jev.Jev):
    def __init__(self, voice="v1", sure=0.8):
        super().__init__("k", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        self.voice, self.sure, self.asked = voice, sure, []

    def ask(self, state, questions, images=None):
        self.asked.append((state, questions))
        return {"voice": {"choice": self.voice, "confidence": self.sure}}


def test_english_is_read_by_a_free_voice_and_hindi_by_an_ai_voice():
    j = VoiceJev("v1")
    voice, why = voices.choose(j, ON, language="English", story="A rocket launches")
    assert voice == "kokoro:bf_emma" and why.startswith("Jev's pick")
    assert len(j.asked[-1][1]["voice"]["criteria"]) == 2             # michael, emma: no AI voices
    j = VoiceJev("v1")
    voice, _ = voices.choose(j, ON, language="Hindi", story="बाढ़")
    assert voice == "openai:onyx" and len(j.asked[-1][1]["voice"]["criteria"]) == 2   # marin, onyx
    # No AI voice on: Hindi falls back to the free Hindi voices.
    only_free = dict(ON, voices_enabled=["kokoro:am_michael", "kokoro:hf_alpha"])
    assert voices.choose(VoiceJev(), only_free, language="Hindi", story="x")[0] == "kokoro:hf_alpha"


def test_fixed_mode_and_unsure_jev_fall_back_to_the_owners_voice():
    fixed = dict(ON, voice_mode="fixed", fixed_voice="kokoro:bf_emma")
    assert voices.choose(VoiceJev(), fixed, language="English", story="x") == ("kokoro:bf_emma", "your voice")
    assert voices.choose(VoiceJev(sure=0.1), ON, language="English", story="x")[0] == "kokoro:am_michael"


def _wav(path, seconds=1.5, rate=24000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))


def test_an_ai_voice_reads_with_a_direction_written_from_the_script(s3, owner, user, monkeypatch):
    pid, sid = approved_narrated_post(owner, user)
    owner.execute("update posts set voice_id = 'openai:marin', voice_style = null where id = %s", (pid,))
    calls, directed = [], []

    def fake_direction(key, model, script, language):
        directed.append(script)
        return "Voice: low and steady. Tone: respectful. Pacing: slow.", None

    def fake_openai(key, voice, instructions, text, out):
        calls.append((key, voice, instructions))
        _wav(out, 1.5)
        return 1.5

    monkeypatch.setattr(voices, "direction", fake_direction)
    monkeypatch.setattr(narrate, "SPEAK_OPENAI", fake_openai)
    assert cpu().tick()                                                    # narrate
    assert len(directed) == 1 and directed[0].strip()
    assert len(calls) > 1 and all(k == "sk-test-key" and v == "marin" and i.startswith("Voice: low")
                                  for k, v, i in calls)
    kept = owner.execute("select voice_style from posts where id = %s", (pid,)).fetchone()["voice_style"]
    assert kept.startswith("Voice: low")
    voiced = owner.execute("select count(*) as n from shots where script_id = %s and narration_key is not null",
                           (sid,)).fetchone()["n"]
    assert voiced == len(calls)
    cost = owner.execute("select kind, model, usd_micros from costs where post_id = %s and kind = 'tts'",
                         (pid,)).fetchone()
    assert cost["model"] == voices.TTS_MODEL and cost["usd_micros"] > 0
    owner.execute("delete from jobs where post_id = %s", (pid,))


def test_the_narrator_varies_across_a_channels_posts():
    # Jev is told which voices the last posts had, and asked to vary them.
    j = VoiceJev("v1")
    voices.choose(j, ON, language="English", story="x", recent=["kokoro:am_michael", "kokoro:am_michael"])
    state, q = j.asked[-1]
    assert state["recent_voices"] == "Michael (male), Michael (male)"
    assert "women's voices as often as men's" in q["voice"]["instructions"]
    # Unsure: the voice used least lately, a woman's after a man's and a man's after a woman's.
    assert voices.choose(VoiceJev(sure=0.1), ON, language="English", story="x",
                         recent=["kokoro:am_michael"])[0] == "kokoro:bf_emma"
    assert voices.choose(VoiceJev(sure=0.1), ON, language="English", story="x",
                         recent=["kokoro:bf_emma", "kokoro:am_michael"])[0] == "kokoro:am_michael"
    assert voices.choose(None, ON, language="English", story="x", recent=["kokoro:bf_emma"]) \
        == ("kokoro:am_michael", "taking turns with the channel's other voices")
