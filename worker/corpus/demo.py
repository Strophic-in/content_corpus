"""A sample of every template, made locally with canned content — no model calls,
no GPU, no database, no storage:

    python -m corpus.demo                         # all 22 into ./template-demos
    python -m corpus.demo kinetic_typography --out /tmp/demos
    python -m corpus.demo --posters ../apps/web/public/templates   # the gallery's pictures

A video template becomes a short MP4 built by the real renderers (prepare →
build_segment → join, with its overlays, layout, transitions and loop) where
generated and footage shots are stood in for by abstract moving pictures (ffmpeg's
Mandelbrot and cellular sources), and captions are timed evenly (there is no
voice). A carousel or card becomes its slides (media/slides.py) and slideshow.
Each also gives a poster: one representative frame or slide, 9:16.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import templates
from .media import assemble, footage, slides

W, H, FPS = 1080, 1920, 24

# Canned content: (role, source, seconds, text, label, extras) per shot; words are the caption line.
SHOTS: dict[str, list[dict]] = {
    "cinematic_3d_explainer": [
        dict(role="hook", source="generate", seconds=4, words="What happens inside a black hole?"),
        dict(role="explanation", source="generate", seconds=4, words="Space itself falls inward faster than light.",
             label="Illustration"),
        dict(role="payoff", source="generate", seconds=4, words="So nothing, not even light, gets out.")],
    "full_screen_text_overlay": [
        dict(role="hook", source="plain", seconds=3, text="Octopuses have three hearts."),
        dict(role="beat", source="generate", seconds=3, text="Two pump blood to the gills."),
        dict(role="reveal", source="plain", seconds=3, text="The third stops when they swim.", transition="flash")],
    "top_bottom_split_screen": [
        dict(role="hook", source="generate", seconds=4, text="Why the sky turns red at sunset",
             words="Watch the light travel through more air."),
        dict(role="explanation", source="chart", seconds=4, text="Blue scatters first",
             chart={"kind": "compare", "title": "", "labels": ["noon path", "sunset path"], "values": [1, 38],
                    "unit": "x air"}, words="At sunset it crosses forty times more.")],
    "animated_infographic": [
        dict(role="statistic", source="chart", seconds=4, text="India's solar boom",
             chart={"kind": "stat", "title": "", "labels": ["gigawatts of solar, 2025"], "values": [105], "unit": ""},
             words="India now runs on over a hundred gigawatts of sun."),
        dict(role="comparison", source="chart", seconds=4,
             chart={"kind": "line", "title": "Solar capacity (GW)", "labels": ["2019", "2021", "2023", "2025"],
                    "values": [35, 49, 73, 105], "unit": ""}, words="Triple what it had six years ago.")],
    "documentary_storytelling": [
        dict(role="opening", source="image", seconds=4, text="Kolkata, 1943", words="The city was about to change."),
        dict(role="escalation", source="generate", seconds=4, label="Reconstruction",
             words="Then the river rose overnight.")],
    "podcast_interview_clip": [
        dict(role="quote", source="clip", seconds=4, text="“Start before you're ready”",
             words="You start before you are ready. Always.", focus={"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.6}),
        dict(role="key_point", source="clip", seconds=4, words="Nobody feels ready. That is the point.")],
    "pov_immersive_scenario": [
        dict(role="pov_hook", source="generate", seconds=3, text="POV: you wake up on Mars", label="Fiction"),
        dict(role="escalation", source="generate", seconds=3, text="The oxygen alarm starts", transition="whip")],
    "transformation_match_cut": [
        dict(role="before", source="plain", seconds=3, text="Day 1"),
        dict(role="reveal", source="generate", seconds=3, text="Day 100", transition="zoom")],
    "before_after_comparison": [
        dict(role="before", source="image", seconds=3, label="Before", words="The old street, flooded every June."),
        dict(role="after", source="generate", seconds=3, label="After", transition="wipe",
             words="Now the drains carry it away.")],
    "myth_vs_fact": [
        dict(role="myth", source="generate", seconds=4, label="Myth", text="We only use 10% of our brain",
             words="You've heard we only use ten percent."),
        dict(role="evidence", source="chart", seconds=4, label="Fact",
             chart={"kind": "stat", "title": "", "labels": ["of the brain is active over a day"], "values": [100],
                    "unit": "%"}, words="Scans show all of it working.")],
    "ranked_countdown": [
        dict(role="item", source="generate", seconds=3, label="#3", text="Kerala backwaters",
             words="Number three, the backwaters."),
        dict(role="item", source="generate", seconds=3, label="#2", text="Ladakh in winter", transition="whip",
             words="Number two, Ladakh."),
        dict(role="payoff", source="generate", seconds=3, label="#1", text="Hampi at sunrise", transition="whip",
             words="And number one, Hampi.")],
    "screen_recording_tutorial": [
        dict(role="step", source="clip", seconds=4, label="Step 1", text="Open Settings → Privacy",
             focus={"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}, words="First, open privacy settings."),
        dict(role="step", source="clip", seconds=4, label="Step 2", text="Turn off Location History",
             focus={"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}, words="Then switch this off.")],
    "kinetic_typography": [
        dict(role="hook_phrase", source="plain", seconds=3, text="You don't need MORE time."),
        dict(role="emphasis", source="plain", seconds=3, text="You need FEWER tabs open.", transition="flash")],
    "mini_news_explainer": [
        dict(role="what_happened", source="generate", seconds=4, text="What happened", label="Developing",
             words="A dam upstream released water overnight."),
        dict(role="why_it_matters", source="chart", seconds=4, text="Why it matters",
             chart={"kind": "bar", "title": "Villages on alert", "labels": ["Thrissur", "Ernakulam", "Idukki"],
                    "values": [14, 9, 6], "unit": ""}, words="Twenty-nine villages are on alert.")],
    "question_answer_demo": [
        dict(role="question", source="generate", seconds=4, text="What if the Moon disappeared?",
             words="What if the Moon vanished tonight?"),
        dict(role="answer", source="generate", seconds=4, words="Tides would shrink to a third.")],
    "satisfying_process_timelapse": [
        dict(role="result_preview", source="generate", seconds=3, label="Hour 40"),
        dict(role="process", source="clip", seconds=3, timelapse=True, label="Hour 1")],
    "reaction_commentary": [
        dict(role="excerpt", source="clip", seconds=4, layout="split", text="The viral claim",
             words="This clip says the bridge was built in a week."),
        dict(role="analysis", source="generate", seconds=4, words="The records say eleven months.")],
    "seamless_loop": [
        dict(role="setup", source="generate", seconds=3),
        dict(role="return", source="generate", seconds=3)],
    "character_dialogue": [
        dict(role="setup", source="generate", seconds=4, words="Is the client call at five?"),
        dict(role="punchline", source="generate", seconds=4, words="It was at four.")],
}

SLIDES: dict[str, list[dict]] = {
    "educational_carousel": [
        {"heading": "5 settings that drain your battery", "body": "Number 3 is on by default.", "picture": True},
        {"heading": "Always-on display", "body": "It wakes the screen hundreds of times a day. Turn it off in Display.",
         "picture": True},
        {"heading": "Background refresh", "body": "Apps update even when closed. Allow it only for messaging.",
         "chart": {"kind": "bar", "title": "Battery used overnight", "labels": ["Refresh on", "Refresh off"],
                   "values": [14, 4], "unit": "%"}},
        {"heading": "Save it for later", "body": "Which one surprised you? Tell us below."}],
    "photo_dump_collage": [
        {"heading": "A week in Munnar", "body": "", "picture": True},
        {"heading": "Morning tea fields", "body": "", "picture": True},
        {"heading": "The road up", "body": "", "picture": True}],
    "picture_above_text_below": [
        {"heading": "Kerala opens its first floating solar plant",
         "body": "The 92 MW plant on the West Kallada wetland will power about 40,000 homes, the state utility said.",
         "picture": True}],
}


def _picture(kind: str, out: Path, seconds: float, size=(1920, 1080), hue: int = 0) -> Path:
    """An abstract stand-in for footage or a generated shot (`hue`: so samples differ)."""
    src = {"generate": "mandelbrot=s={w}x{h}:rate=24:maxiter=300:start_scale=2.5:end_scale=0.3",
           "image": "cellauto=s={w}x{h}:rate=24:rule=110",
           "clip": "life=s={w}x{h}:rate=24:mold=10:r=0.2:life_color=#ffd166:death_color=#1d3557:mold_color=#457b9d"}[kind]
    w, h = size
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src.format(w=w, h=h), "-t", f"{seconds:.2f}",
                    "-vf", f"hue=h={hue},format=yuv420p" if kind != "image" else f"hue=h={hue}",
                    *(["-frames:v", "1"] if out.suffix == ".png" else ["-c:v", "libx264", "-preset", "veryfast"]),
                    str(out)], check=True, capture_output=True)
    return out


def _hue(tid: str, k: int) -> int:
    return (sum(map(ord, tid)) * 37 + k * 50) % 360


def _words(line: str, seconds: float) -> list[tuple[float, float, str]]:
    words = line.split()
    step = (seconds - 0.6) / max(1, len(words))
    return [(0.3 + i * step, 0.3 + (i + 1) * step, w) for i, w in enumerate(words)]


def video(tid: str, out: Path, work: Path) -> Path:
    t = templates.get(tid)
    look = templates.look(tid, {"brand_text": "@yourchannel"})
    segs, transitions = [], []
    for k, s in enumerate(SHOTS[tid]):
        d = work / f"shot{k}"
        d.mkdir()
        ex = {x: s[x] for x in ("role", "text", "label", "layout", "transition", "focus", "timelapse") if s.get(x)}
        size = templates.split_size(ex, look)
        shot = d / "shot.mp4"
        src = s["source"]
        if src == "plain":
            footage.plain(shot, seconds=s["seconds"], look=look, size=size)
        elif src == "chart":
            still = footage.chart_still(s["chart"], d / "chart.png", look, size)
            footage.ken_burns(still, shot, seconds=s["seconds"], layout="cover", zoom=0.04, size=size)
        elif src == "image":
            pic = _picture("image", d / "pic.png", 1)
            footage.ken_burns(pic, shot, seconds=s["seconds"], idx=k, credit="Photo: sample", size=size,
                              zoom=look.ken_burns)
        elif src == "clip":
            raw = _picture("clip", d / "raw.mp4", 16 if s.get("timelapse") else s["seconds"] + 1)
            footage.compose_clip(raw, shot, seconds=s["seconds"], start=0, end=16 if s.get("timelapse") else 0,
                                 credit="Video: sample", focus=s.get("focus"), timelapse=bool(s.get("timelapse")),
                                 size=size, audio="mute")
        else:                                                  # stands in for a GPU shot
            _picture("generate", d / "gen.mp4", s["seconds"], size=(704, 1280), hue=_hue(tid, k))
            shot = d / "gen.mp4"
        words = _words(s["words"], s["seconds"]) if s.get("words") else None
        v, a = d / "seg.mp4", d / "seg.wav"
        assemble.build_segment(shot, v, a, words=words, look=look, extras=ex)
        segs.append((v, a))
        transitions.append(ex.get("transition") or look.transition)
    assemble.join_segments(segs, out, log=lambda m: None, transitions=transitions, loop=look.loop)
    return out


def carousel(tid: str, out_dir: Path, work: Path) -> list[Path]:
    look = templates.look(tid, {"brand_text": "@yourchannel"})
    layout = look.slides.layout if look.slides else "educational"
    deck = SLIDES[tid]
    pics = []
    for i, s in enumerate(deck):
        visual = {"source": "chart", "chart": s["chart"]} if s.get("chart") else {"source": "asset" if s.get(
            "picture") else "none"}
        slide = {"heading": s["heading"], "body": s["body"], "visual": visual}
        pic = (_picture("generate", work / f"p{i}.png", 1, size=(1600, 1200), hue=_hue(tid, i))
               if s.get("picture") else None)
        pics.append(slides.render(slide, i, len(deck), layout=layout, look=look, out=out_dir / f"{tid}-{i + 1}.jpg",
                                  picture=pic, credit="Photo: sample" if pic else None))
    return pics


def poster(src: Path, out: Path, at: float | None = None) -> Path:
    """One 9:16 picture: a frame of a video, or a slide blur-padded to 9:16."""
    args = ["-ss", f"{at:.2f}"] if at is not None else []
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args, "-i", str(src), "-frames:v", "1", "-vf",
                    "split[a][b];[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8[bg];"
                    "[b]scale=270:480:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2",
                    "-q:v", "5", str(out)], check=True, capture_output=True)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ids", nargs="*", help="template ids (default: all)")
    ap.add_argument("--out", default="template-demos", help="where the demos go")
    ap.add_argument("--posters", help="also write <id>.jpg posters here (apps/web/public/templates)")
    a = ap.parse_args(argv)
    ids = a.ids or sorted(templates.registry())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for tid in ids:
        t = templates.get(tid)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            if t.content_type == "video":
                mp4 = video(tid, out / f"{tid}.mp4", work)
                made, frame = mp4, poster(mp4, work / "poster.jpg", at=min(2.0, SHOTS[tid][0]["seconds"] * 0.7))
            else:
                pages = carousel(tid, out, work)
                made, frame = pages[0], poster(pages[0], work / "poster.jpg")
            if a.posters:
                Path(a.posters).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(frame, Path(a.posters) / f"{tid}.jpg")
        print(f"{tid:32} -> {made}")


if __name__ == "__main__":
    main()
