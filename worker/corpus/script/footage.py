"""What a script may show besides generated shots, and how the writer is told.

A post's footage is its assets — the accepted idea's video or picture, when the
owner chose to use it (approved, fetched, analysed) — plus stock video when a
Pexels key is set. The writer sees them as a numbered list with what each shows
and when (the analysis: moments with times, what is said), so it can pick a
clip's window from facts rather than guess. Without any footage the rules say
"generate" for every shot, and normalize() makes sure of it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .llm import GENERATED, MAX_CLIP_SECONDS, NO_CHART, Footage, ScriptOut

# How long write_script waits for footage still being fetched or analysed before
# writing without it.
WAIT_MINUTES = 30
# What having no footage resets (the on-screen fields stay).
FOOTAGE_FIELDS = ("source", "asset", "start", "end", "keep_audio", "stock_query")


def load(c, post_id, stock: bool) -> tuple[Footage, list[dict]]:
    """(the footage a script may use, assets still being fetched, analysed or drawn).

    An original the owner has not approved (they chose an AI version) is a
    reference: described to the writer, never shown."""
    rows = c.execute("""select id, n, kind, origin, credit, rights, state, w, h, seconds, has_audio,
                               analysis, created_at, made_from, fetch_from->'found'->>'before' as before
                          from assets where post_id = %s order by n""", (post_id,)).fetchall()
    usable = [dict(r) for r in rows if r["state"] == "ready" and r["rights"] == "approved"]
    references = [dict(r) for r in rows if r["state"] == "ready" and r["rights"] == "needs_review"]
    waiting = [dict(r) for r in rows if r["state"] == "pending" and r["rights"] != "rejected"]
    return Footage(assets=usable, stock=stock, references=references), waiting


def still_worth_waiting(waiting: list[dict]) -> bool:
    now = datetime.now(timezone.utc)
    return any((now - a["created_at"]).total_seconds() < WAIT_MINUTES * 60 for a in waiting)


def _clock(s: float) -> str:
    s = max(0.0, float(s))
    return f"{int(s // 60)}:{s % 60:04.1f}"


def _describe(a: dict, label: str | None = None) -> str:
    an = a.get("analysis") or {}
    w, h = a.get("w") or 0, a.get("h") or 0
    shape = "portrait" if h > w * 1.1 else "landscape" if w > h * 1.1 else "square"
    head = label or f"{a['n']}."
    if a["kind"] == "image":
        lines = [f"{head} picture, {shape} {w}×{h} — {a['credit'] or a['origin']}"]
    else:
        lines = [f"{head} video, {float(a['seconds'] or 0):.1f} s, {shape} {w}×{h}, "
                 f"own sound: {'yes' if a.get('has_audio') else 'no'} — {a['credit'] or a['origin']}"]
    summary = an.get("summary") or (an.get("card") or {}).get("summary") or an.get("description")
    if summary:
        lines.append(f"   Shows: {summary}")
    if float(a.get("before") or 0) >= 0.6:
        lines.append("   BEFORE: shows the place as it was before the event - use it as the before picture")
    for m in (an.get("moments") or [])[:12]:
        if isinstance(m, dict):
            lines.append(f"   {_clock(m.get('at', 0))} {m.get('what', '')}")
    said = [f"{_clock(t['start'])}–{_clock(t['end'])} \"{t['text'].strip()}\""
            for t in (an.get("transcript") or [])[:20] if t.get("text", "").strip()]
    if said:
        lines.append("   Said: " + " · ".join(said))
    flags = []
    if an.get("logos_or_watermarks"):
        flags.append("carries a logo or watermark" + (f" ({', '.join(an.get('logo_names') or [])})"
                                                     if an.get("logo_names") else ""))
    if an.get("graphic"):
        flags.append("graphic in places — avoid those moments")
    if flags:
        lines.append("   Note: " + "; ".join(flags))
    return "\n".join(lines)


# The video model sees only a shot's `visual` (plus the look): a one-line visual gives a
# flat, generic take (live: "a symbolic spire tilts and drops", ~20 words). Written like a
# cinematographer's shot note it gets the details, the depth and a deliberate camera.
GENERATE_GUIDE = """

## Generated shots: write each one like a cinematographer's shot note
For every shot whose `source` is "generate", `visual` is the video model's whole brief: 50-110 words,
one continuous take, present tense, in this order:
1. Shot size and lens: extreme close-up, close-up, medium, wide or aerial; "macro", "85mm", "24mm wide".
2. The subject and its one action, with the small physical details that make it feel real: textures
   (cracked plaster, wet cobblestones, frayed rope), particles (embers, dust in a light beam, rain,
   steam), reflections, wind in fabric or leaves, tiny movements.
3. Depth: what is in the foreground, the middle and the background.
4. The camera move, with its speed and direction and what it reveals: slow push-in, lateral dolly
   left, low-angle tilt up, slow 30-degree orbit, gentle handheld drift, crane down, rack focus.
5. Light and colour: time of day, where the light comes from, contrast, one colour accent.
6. The beat the take settles on at the end, so the next shot can cut from it.
Use generated shots as B-roll: cutaways that show what the narration describes but footage cannot -
a detail, the scale, the consequence. Vary shot sizes across the reel (wide, then close, then a
detail) and never use the same camera move twice in a row.
Example of the length and detail wanted: "Close-up, 85mm: raindrops gather on a rusted iron railing
above a flooded street at dusk; each drop swells, trembles and falls into the brown water below,
sending out slow rings. The camera racks focus from the drops to the water, then cranes down toward
a plastic chair drifting past a half-submerged shop shutter. Cool blue dusk light, warm streetlamp
reflections streaking across the ripples; the take settles on the chair turning slowly in the current."
The rules above still hold: no lifelike real people, no words, numbers or logos in the picture."""


def prompt_section(footage: Footage, narrated: bool) -> str:
    """Appended to the format's script prompt: the shot sources this reel has."""
    unused = ("Fields a source does not use take these values: asset 0, start 0, end 0, keep_audio false, "
              "stock_query \"\", and a chart with kind \"\", an empty title, no labels, no values and unit \"\" "
              "(a generated shot may set `asset` to animate a picture, below).")
    chart = ("- \"chart\": a chart, for a story that turns on a few numbers — `chart` has its `kind` (\"bar\": "
             "2-6 labels; \"stat\": one big number; \"compare\": 2-3 side by side; \"line\": 3-12 points in time "
             "order), a short title, the labels and their values in the same order, and a unit (\"%\", \"crore\", "
             "\"deaths\", or \"\"). Only numbers stated in the sources; never estimates.")
    if not footage.any:
        return ("\n\n## Shot sources\nEach shot has a `source`:\n- \"generate\": the AI video model renders its "
                f"`visual`.\n{chart}\n{unused}" + GENERATE_GUIDE)
    videos = any(a["kind"] == "video" for a in footage.assets)
    images = any(a["kind"] == "image" for a in footage.assets)
    lines = ["", "", "## Shot sources",
             "Each shot has a `source`:",
             "- \"generate\": the AI video model renders `visual`, as described above."]
    if videos:
        lines.append(
            "- \"clip\": a window of one of the videos below — `asset` is its number, `start` and `end` the "
            "window in seconds (use the times listed). The picture is the real footage; `visual` says in a few "
            "words what the window shows. Set `keep_audio` true when its own sound matters (someone speaking, "
            "the moment itself): then "
            + ("`narration` is \"\" and " if narrated else "")
            + f"the window sets the shot's length (at most {MAX_CLIP_SECONDS} s). Otherwise "
            + ("the narration plays over the clip's lowered sound, so choose a window at least as long as the "
               "line takes to say." if narrated else "the clip's sound plays under the scene.")
            + " Give each clip shot its own part of the video, mostly in order, and use all of it before "
              "showing any part twice. A moment marked KEY (the collapse, the explosion) is the heart of the "
              "story: a clip window must include it, starting a second or two before.")
    if images:
        lines.append("- \"image\": one of the pictures below, shown with a slow camera move; `asset` is its "
                     "number" + ("; the narration plays over it." if narrated else "."))
        lines.append("- \"generate\" with `asset` set to a picture's number animates that picture on the GPU: the "
                     "video starts from it and moves as `visual` describes (a slow push-in, drifting smoke, people "
                     "walking). Use it where motion adds something; a plain \"image\" shot costs nothing.")
    lines.append(chart)
    if footage.stock:
        lines.append("- \"stock\": a stock video found by `stock_query` — 2 to 5 plain words naming something "
                     "filmable (\"city traffic at night\", \"hospital corridor\"). Stock shows the setting or "
                     "the subject in general, never the actual event or an identifiable person.")
    lines.append(unused)
    if footage.assets:
        lines += ["Real footage is the strongest proof: show the actual event with clips and pictures where they "
                  "fit, and generate only what the footage cannot show. Each piece of footage is credited on "
                  "screen automatically (an AI picture as \"AI illustration\"); never mention credits in the "
                  "script.",
                  "", "## Footage you may use"]
        lines += [_describe(a) for a in footage.assets]
    if footage.references:
        lines += ["", "## Footage you may not show — recreate it",
                  "The owner chose an AI version of the original media below: it must not appear in the reel. "
                  "Recreate a video's moments as generated shots that follow its log closely — what happens, in "
                  "order, and where — and they are labelled \"AI reconstruction\" on screen. The narration never calls them \"this clip\", \"the video\" or \"the footage\": the viewer sees a reconstruction. Show people as "
                  "figures from behind or at a distance, never a lifelike face. A picture's AI version, when "
                  "there is one, is in the list above as \"AI illustration\"."]
        lines += [_describe(a, f"Original {'video' if a['kind'] == 'video' else 'picture'}:")
                  for a in footage.references]
    return "\n".join(lines) + GENERATE_GUIDE


def normalize(out: ScriptOut, footage: Footage, music: bool = False) -> None:
    """Without footage, every shot is generated or a chart — whatever the model put in
    the other fields. Without a music key, or with a mood we don't know, no music."""
    from .llm import MUSIC_MOODS, Chart

    if not music or out.music_mood not in MUSIC_MOODS:
        out.music_mood = ""
    for s in out.shots:
        if s.source != "chart":
            s.chart = Chart(**NO_CHART)
        if s.timelapse:
            s.keep_audio = False            # a sped-up window plays without its sound
        if footage.any:
            continue
        for k in FOOTAGE_FIELDS:
            if not (k == "source" and s.source in ("chart", "plain")):
                setattr(s, k, GENERATED[k])


def picture_section(footage: Footage) -> str:
    """For carousels and cards: the post's pictures a slide may show (videos can't be)."""
    pics = [a for a in footage.assets if a["kind"] == "image"]
    if not pics:
        return ("\n\n## Pictures\nThis post has no pictures of its own: slides use an AI picture (where the "
                "template allows), a chart, or \"none\".")
    return ("\n\n## Pictures you may use (`visual.source` \"asset\" with its number)\n"
            "Real pictures are the strongest: use them where they fit. Each is credited on the slide "
            "automatically; never mention credits in the text.\n" + "\n".join(_describe(a) for a in pics))
