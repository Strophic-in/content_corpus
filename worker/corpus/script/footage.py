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

from .llm import GENERATED, MAX_CLIP_SECONDS, Footage, ScriptOut

# How long write_script waits for footage still being fetched or analysed before
# writing without it.
WAIT_MINUTES = 30


def load(c, post_id, stock: bool) -> tuple[Footage, list[dict]]:
    """(the footage a script may use, assets still being fetched, analysed or drawn).

    An original the owner has not approved (they chose an AI version) is a
    reference: described to the writer, never shown."""
    rows = c.execute("""select id, n, kind, origin, credit, rights, state, w, h, seconds, has_audio,
                               analysis, created_at, made_from
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


def prompt_section(footage: Footage, narrated: bool) -> str:
    """Appended to the format's script prompt: the shot sources this reel has."""
    unused = ("Fields a source does not use take these values: asset 0, start 0, end 0, keep_audio false, "
              "stock_query \"\" (a generated shot may set `asset` to animate a picture, below).")
    if not footage.any:
        return ("\n\n## Shot sources\nEvery shot's `source` is \"generate\": the AI video model renders "
                f"its `visual`. {unused}")
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
              "showing any part twice.")
    if images:
        lines.append("- \"image\": one of the pictures below, shown with a slow camera move; `asset` is its "
                     "number" + ("; the narration plays over it." if narrated else "."))
        lines.append("- \"generate\" with `asset` set to a picture's number animates that picture on the GPU: the "
                     "video starts from it and moves as `visual` describes (a slow push-in, drifting smoke, people "
                     "walking). Use it where motion adds something; a plain \"image\" shot costs nothing.")
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
                  "order, and where — and they are labelled \"AI reconstruction\" on screen. Show people as "
                  "figures from behind or at a distance, never a lifelike face. A picture's AI version, when "
                  "there is one, is in the list above as \"AI illustration\"."]
        lines += [_describe(a, f"Original {'video' if a['kind'] == 'video' else 'picture'}:")
                  for a in footage.references]
    return "\n".join(lines)


def normalize(out: ScriptOut, footage: Footage) -> None:
    """Without footage, every shot is generated — whatever the model put in the fields."""
    if footage.any:
        return
    for s in out.shots:
        for k, v in GENERATED.items():
            setattr(s, k, v)
