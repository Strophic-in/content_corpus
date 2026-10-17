"""What a template asks of a script, told to the writer and checked in its draft.

`writer_section` explains the on-screen fields this template uses (role, text,
label, layout, transition, panel, focus, timelapse) and appends the template's
guide; `normalize` empties the fields a template does not draw, whatever the
model put there; `problems` checks the draft against the template — the beats
its structure stands on (MYTH then FACT, a countdown to #1), the shot sources it
allows, and that every piece of on-screen text fits where it is drawn (measured
with the bundled fonts, as the renderer will draw it). Roles are guidance for the
writer and labels for the owner, never a reason to send a draft back.
"""

from __future__ import annotations

import re

from ..media import text as tx
from ..templates import Look, Template
from .llm import CHART_KINDS, NO_FOCUS, Chart, Focus, Footage, ScriptOut

W = 1080
# On-screen text sizes (px on the 1080x1920 frame) and how many lines each may take.
HEADLINE = dict(max_size=66, min_size=50, max_lines=3)
BEAT = dict(max_size=92, min_size=62, max_lines=5)
LABEL = dict(max_size=44, min_size=36, max_lines=1)
KINETIC_MIN = 96
READ_WORDS_PER_SECOND = 3.0       # text beats: a reader takes about a third of a second a word
KINETIC_WORDS_PER_SECOND = 2.5
RANK = re.compile(r"^#\s*(\d{1,2})$")


def voice_rules(audio: str, narration_words: int, words_per_second: float) -> str:
    """Fills {voice_rules} in script_video.md: what `narration` is in this format."""
    if audio == "kokoro":
        return ("  - `narration`: what the narrator says over this shot — one or two short sentences, at most "
                f"{narration_words} words (the narrator speaks about {words_per_second} words a second, plus a "
                "pause; the recording sets the shot's real length). Split a longer thought across two shots.")
    return ("  - `narration`: \"\" — this format has no voice: the on-screen text and the pictures tell it, and "
            "the music and the shots' own sound carry it.")


def writer_section(t: Template, look: Look, audio: str) -> str:
    r = t.render
    lines = ["", "", f"## On-screen fields ({t.display_name})",
             "Every shot also has these fields; one this template doesn't use takes its empty value.",
             f"- `role`: the shot's step, one of: {', '.join(t.scene_structure)}."]
    if look.captions == "beats":
        lines.append("- `text`: the shot's text beat, drawn large in the middle of the screen for the whole shot.")
    elif look.captions == "kinetic" and audio != "kokoro":
        lines.append("- `text`: the words that animate on screen during the shot, in short phrases.")
    elif look.text == "headline":
        lines.append("- `text`: a short headline drawn at the top of the screen, or \"\".")
    else:
        lines.append("- `text`: \"\".")
    lines.append("- `label`: a 1-2 word chip drawn above the picture (see the template), or \"\"." if r.labels
                 else "- `label`: \"\".")
    if "split" in r.layouts:
        lines.append(f"- `layout`: \"split\" (the picture in the top half, words or a second picture below) or "
                     f"\"full\"; \"\" means the template's own ({r.layout}).")
        lines.append("- `panel_asset`: for a split shot, a picture's number from the footage list to show in the "
                     "bottom panel instead of text; 0 otherwise.")
    else:
        lines += ["- `layout`: \"\".", "- `panel_asset`: 0."]
    others = [x for x in r.transitions if x != r.transition]
    lines.append(f"- `transition`: how the shot begins — \"\" for the template's own ({r.transition})"
                 + (f", or one of {', '.join(others)}" if others else "") + ".")
    lines.append("- `focus`: for a clip or picture, the region to punch in on as fractions of the frame (x, y from "
                 "the top left, w, h — at least 0.25 wide and tall), or all 0 for the whole frame." if r.focus
                 else "- `focus`: all 0.")
    lines.append("- `timelapse`: true for a clip whose whole window (longer than the shot) plays sped up; false "
                 "otherwise." if r.timelapse else "- `timelapse`: false.")
    if "chart" in r.sources:
        lines.append(f"- a chart's `kind`: {', '.join(r.chart_kinds)} (\"\" when the shot is not a chart).")
    else:
        lines.append("- a chart's `kind`: \"\".")
    if "plain" in r.sources:
        lines.append("- `source` \"plain\": the format's own background colour behind the text, no picture.")
    lines.append(f"Use only these shot sources: {', '.join(r.sources)}.")
    return "\n".join(lines) + "\n\n" + t.guide


def normalize(out: ScriptOut, t: Template, look: Look, audio: str) -> None:
    """Empty the fields this template doesn't draw (the model sometimes fills them)."""
    r = t.render
    keeps_text = look.captions in ("beats", "kinetic") or look.text == "headline"
    for s in out.shots:
        s.role = s.role.strip().lower().replace(" ", "_")
        s.text = " ".join(s.text.split()) if keeps_text else ""
        s.label = " ".join(s.label.split()) if r.labels else ""
        if "split" not in r.layouts or s.layout not in r.layouts:
            s.layout = ""
        if s.layout != "split" and look.layout != "split":
            s.panel_asset = 0
        if s.transition not in r.transitions:
            s.transition = ""
        if not r.focus or s.source not in ("clip", "image") or s.focus.w <= 0 or s.focus.h <= 0:
            s.focus = Focus(**NO_FOCUS)
        if not r.timelapse or s.source != "clip":
            s.timelapse = False
        if s.source == "chart":
            if s.chart.kind not in r.chart_kinds:
                s.chart.kind = r.chart_kinds[0]
        else:
            s.chart = Chart(kind="", title="", labels=[], values=[], unit="")
        if audio != "kokoro":
            s.narration = ""


def _fits(text: str, font, spec: dict, width: float) -> bool:
    return tx.fit(text, font, max_width=width, **spec) is not None


def problems(out: ScriptOut, t: Template, look: Look, *, audio: str, footage: Footage | None) -> list[str]:
    r = t.render
    out_ = []
    shots = out.shots
    if not shots:
        return out_
    font = tx.heavy(look.font)
    width = W - 2 * look.safe_margin_px
    for i, s in enumerate(shots, 1):
        src = s.source or "generate"
        if src not in r.sources:
            out_.append(f"shot {i} uses source \"{src}\", which {t.display_name} doesn't use; use one of "
                        f"{', '.join(r.sources)}")
        if s.text:
            spec = BEAT if look.captions == "beats" else HEADLINE
            if look.captions == "kinetic" and audio != "kokoro":
                words = len(s.text.split())
                if words > max(3, s.seconds * KINETIC_WORDS_PER_SECOND + 2):
                    out_.append(f"shot {i}'s text has {words} words for {s.seconds}s of animation; keep it to "
                                f"{int(s.seconds * KINETIC_WORDS_PER_SECOND + 2)} or lengthen the shot")
                too_wide = [w for w in s.text.split() if tx.width(w.upper(), font, KINETIC_MIN) > width]
                if too_wide:
                    out_.append(f"shot {i}'s word \"{too_wide[0]}\" is too long to animate; use a shorter word")
            elif not _fits(s.text, font, spec, width):
                limit = "5 short lines" if spec is BEAT else "3 lines"
                out_.append(f"shot {i}'s text is too long to fit on screen ({limit}); shorten it")
            elif look.captions == "beats":
                words = len(s.text.split())
                if words > max(4, s.seconds * READ_WORDS_PER_SECOND):
                    out_.append(f"shot {i}'s text has {words} words but is on screen for {s.seconds}s; cut it to "
                                f"{int(max(4, s.seconds * READ_WORDS_PER_SECOND))} words or lengthen the shot")
        if s.label and not _fits(s.label.upper(), font, LABEL, 760):
            out_.append(f"shot {i}'s label \"{s.label}\" is too long; use one or two short words")
        if s.panel_asset:
            a = footage.asset(s.panel_asset) if footage else None
            if a is None or a["kind"] != "image":
                out_.append(f"shot {i}'s panel_asset #{s.panel_asset} is not a picture in the footage list; "
                            "use a listed picture or 0")
        f = s.focus
        if f.w > 0 and not (0 <= f.x and 0 <= f.y and f.x + f.w <= 1.001 and f.y + f.h <= 1.001
                            and f.w >= 0.25 and f.h >= 0.25):
            out_.append(f"shot {i}'s focus box ({f.x:g}, {f.y:g}, {f.w:g}, {f.h:g}) must lie inside the frame and "
                        "be at least 0.25 wide and tall")
    if look.captions == "beats":
        missing = [i for i, s in enumerate(shots, 1) if not s.text]
        if missing:
            out_.append(f"shots {', '.join(map(str, missing))} have no text; every shot of this template carries a "
                        "text beat")
    if look.captions == "kinetic" and audio != "kokoro":
        missing = [i for i, s in enumerate(shots, 1) if not s.text]
        if missing:
            out_.append(f"shots {', '.join(map(str, missing))} have no text to animate")
    out_ += _template_rules(t, shots, footage, audio)
    return out_


def _labels(shots) -> list[str]:
    return [s.label.strip().lower() for s in shots]


def _template_rules(t: Template, shots, footage: Footage | None, audio: str) -> list[str]:
    """The beats a template's structure stands on."""
    tid, out = t.template_id, []
    labels = _labels(shots)
    if tid == "myth_vs_fact":
        if "myth" not in labels or "fact" not in labels:
            out.append("label the claim's shot \"Myth\" and the first evidence shot \"Fact\"")
        elif labels.index("fact") < labels.index("myth"):
            out.append("the \"Myth\" shot comes before the \"Fact\" shot")
    elif tid == "before_after_comparison":
        if "before" not in labels or "after" not in labels:
            out.append("label one shot \"Before\" and a later one \"After\"")
        elif labels.index("after") < labels.index("before"):
            out.append("the \"Before\" shot comes before the \"After\" shot")
    elif tid == "ranked_countdown":
        ranks = [int(m.group(1)) for s in shots if (m := RANK.match(s.label.strip()))]
        distinct = list(dict.fromkeys(ranks))
        if len(distinct) < 3:
            out.append("count down at least three items, labelled \"#3\", \"#2\", \"#1\" (or from a higher number)")
        elif distinct != sorted(distinct, reverse=True) or distinct[-1] != 1 or distinct != list(
                range(distinct[0], 0, -1)):
            out.append(f"item labels must count down by one to #1 (got {', '.join('#' + str(n) for n in distinct)})")
        else:
            per = {}
            for s in shots:
                if (m := RANK.match(s.label.strip())):
                    per[m.group(1)] = per.get(m.group(1), 0) + s.seconds
            lo, hi = min(per.values()), max(per.values())
            if hi > 2 * max(lo, 1):
                out.append("give the items about the same time each (the longest is more than twice the shortest)")
    elif tid == "pov_immersive_scenario":
        if not shots[0].text.lower().startswith("pov"):
            out.append("shot 1's text starts with \"POV:\"")
    elif tid == "question_answer_demo":
        if not shots[0].text.strip().endswith("?"):
            out.append("shot 1's text is the question, ending with \"?\"")
    elif tid == "animated_infographic":
        charts = sum(1 for s in shots if s.source == "chart")
        if charts * 2 < len(shots):
            out.append(f"only {charts} of {len(shots)} shots are charts; make at least half of them charts")
    elif tid == "podcast_interview_clip":
        talking = [a for a in (footage.assets if footage else []) if a["kind"] == "video" and a.get("has_audio")]
        if not talking:
            out.append("this template needs the owner's interview video with sound in the footage list — "
                       "upload it to the post")
        bad = [i for i, s in enumerate(shots, 1) if s.source != "clip" or not s.keep_audio]
        if bad:
            out.append(f"shots {', '.join(map(str, bad))} must be clips that keep their own sound")
    elif tid == "screen_recording_tutorial":
        if not any(a["kind"] == "video" for a in (footage.assets if footage else [])):
            out.append("this template needs the owner's screen recording in the footage list — upload it to the post")
    elif tid == "seamless_loop":
        if len(shots) > 3:
            out.append(f"a loop has 1-3 shots, not {len(shots)}")
    return out
