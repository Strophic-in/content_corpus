"""cpu/write_script — topic → a script version awaiting approval.

A post whose accepted idea brought footage waits (Defer) until that footage is
fetched and analysed, so the writer can cut clips from what actually happens in
it; script/footage.py tells the writer what it may show. It also waits for the
story's research (research_post: the sources read in full) and writes from it.
The script picks a background-music mood when a Freesound key is set.

The post's video look (looks.py) is chosen here, once: the channel's, or on auto
Jev's pick for this story; its words are the look of every generated shot.

The post's format is one of the templates (templates.py): its prompt (or the
template's own when the owner hasn't written one), the template's guide to its
structure and on-screen fields, and its checks (script/structure.py). A carousel
or card is written as slides instead of shots (script/carousel.py) and stored in
scripts.slides.

Safe to retry: the version number comes from the job (fixed at enqueue), and a
retry that finds that version already written returns it instead of paying for
another LLM call. Everything the call produces lands in one transaction. A draft
that breaks a rule (validate()) is sent back to the model with the exact problems,
up to REPAIR_ROUNDS times, before the attempt counts as failed.
"""

from __future__ import annotations

import hashlib

from psycopg.types.json import Jsonb

from .. import channels, costs, db, jev, looks, prompts, templates, vault
from ..config import settings
from ..runner import Defer, Handler, JobContext, Permanent, Retryable
from ..script import carousel as carousel_
from ..script import footage as footage_
from ..script import structure
from ..script.llm import (MUSIC_MOODS, NARRATOR_WORDS_PER_SECOND, OpenAIScriptWriter, Usage,
                          narration_word_cap, validate)
from ..script.review import OpenAIReviewer

# Swapped out by tests; production always talks to OpenAI with the user's key.
WRITER_FACTORY = OpenAIScriptWriter
CAROUSEL_FACTORY = carousel_.OpenAICarouselWriter
REVIEWER_FACTORY = OpenAIReviewer
# Extra calls per attempt that hand the model its own draft and the rules it broke.
REPAIR_ROUNDS = 2


# audio_source → prompt. 'kokoro' is narrated mode: one TTS voice-over across the
# reel, visuals with sound effects only. 'ltx_native': characters speak on screen.
def template_of(fmt: dict | None, audio_source: str) -> templates.Template:
    """The format's template; a post made before formats (or templates) by its audio."""
    if fmt and fmt.get("template_id"):
        return templates.get(fmt["template_id"])
    return templates.get("character_dialogue" if audio_source == "ltx_native" else "cinematic_3d_explainer")


def _system_prompt(st: dict, target_seconds: int, revision_note: str, audio_source: str,
                   speed: float = 1.1, fmt: dict | None = None, slide_hint: str = "",
                   look_text: str | None = None) -> str:
    """The script writer's instructions: the post's format's prompt (prompt library) —
    or its template's shipped prompt while the owner hasn't written one — or the
    shipped default for posts made before formats existed."""
    if fmt and (fmt.get("script_prompt") or "").strip():
        template = fmt["script_prompt"]
    elif fmt:
        template = prompts.read(template_of(fmt, audio_source).base_prompt)
    else:
        template = prompts.default(f"script:{audio_source}")
    look = look_text or (fmt["visual_style"] if fmt else prompts.default("visual_style"))
    shots = max(1, round(target_seconds / 8))
    cap = narration_word_cap(speed)
    return prompts.fill(template, {
        "voice_rules": structure.voice_rules(audio_source, cap - 5, round(NARRATOR_WORDS_PER_SECOND * speed, 1)),
        "slide_count_hint": slide_hint,
        "channel_name": st.get("channel_name") or "(unnamed)",
        "channel_niche": st.get("channel_niche") or "(not set — infer from the topic)",
        "channel_audience": st.get("channel_audience") or "(general)",
        "channel_voice": st.get("channel_voice") or "(clear, engaging, concise)",
        "script_language": st.get("script_language") or "English",
        "target_seconds": target_seconds,
        "shot_count_hint": f"about {shots} shot{'s' if shots != 1 else ''}",
        "revision_note": revision_note,
        # Asked a few words under the hard cap that validate() enforces.
        "narration_words": cap - 5,
        "narration_words_per_second": round(NARRATOR_WORDS_PER_SECOND * speed, 1),
        "visual_style": look or "(none set)",
    })


def _classify_openai_error(e: Exception) -> Exception:
    import openai

    if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return Permanent("OpenAI rejected the API key — update it in Settings.", stage="llm_auth")
    if isinstance(e, openai.NotFoundError):
        return Permanent("The chosen script model is not available to this key — pick another "
                         "in Settings.", stage="llm_model")
    if isinstance(e, openai.BadRequestError):
        return Permanent(f"OpenAI refused the request: {e}", stage="llm_request")
    if isinstance(e, openai.RateLimitError):
        return Retryable("OpenAI rate limit", stage="llm_rate_limit", retry_in=120)
    return Retryable(f"OpenAI call failed: {e}", stage="llm")


def run(ctx: JobContext) -> dict:
    post_id, version = ctx.job["post_id"], int(ctx.payload["version"])
    with db.conn() as c:
        post = c.execute("select * from posts where id = %s", (post_id,)).fetchone()
        if post is None:
            raise Permanent("post was deleted", stage="input")
        if post["status"] != "scripting":
            return {"skipped": f"post is {post['status']}"}
        existing = c.execute("select id from scripts where post_id = %s and version = %s",
                             (post_id, version)).fetchone()
        if existing:
            return {"script_id": str(existing["id"]), "reused": True}
        st = c.execute("select * from app_settings where user_id = %s",
                       (post["user_id"],)).fetchone() or {}
        st = {**st, **channels.profile(c, post["user_id"], post.get("channel_id"))}
        category = _category(c, post)
        rejected = c.execute(
            """select rejection_note, title from scripts
                where post_id = %s and state = 'rejected' and rejection_note is not null
                order by version desc limit 1""", (post_id,)).fetchone()

    model = st.get("script_model")
    if not model:
        raise Permanent("Choose a script model in Settings.", stage="config")
    key = vault.secret(post["user_id"], "openai")
    if not key:
        raise Permanent("Add your OpenAI API key in Settings.", stage="config")
    if why := db.over_quota(post["user_id"]):
        raise Permanent(why[:1].upper() + why[1:] + ".", stage="quota")

    fmt = None
    if post.get("format_id"):
        with db.conn() as c:
            fmt = c.execute("select * from formats where id = %s", (post["format_id"],)).fetchone()
    target = (post["target_seconds"] or (fmt or {}).get("target_seconds")
              or st.get("default_reel_seconds") or 24)
    revision = ""
    if rejected:
        revision = (f"## Revision\nThe previous version (\"{rejected['title']}\") was rejected "
                    f"with this note — address it:\n{rejected['rejection_note']}")
    narrated = post["audio_source"] == "kokoro"
    dialogue = post["audio_source"] == "ltx_native"
    speed = float(st.get("narrator_speed") or 1.1)
    t = template_of(fmt, post["audio_source"])
    look = templates.look(t.template_id, (fmt or {}).get("params"))
    as_slides = bool(fmt) and t.content_type != "video"
    with db.conn() as c:
        footage, waiting = footage_.load(c, post_id, stock=bool(vault.secret(post["user_id"], "pexels_api_key")))
    if waiting and footage_.still_worth_waiting(waiting):
        raise Defer(f"waiting for {len(waiting)} piece(s) of footage to be fetched and analysed", retry_in=45)
    if post.get("research_state") == "pending" and footage_.still_worth_waiting([post]):
        raise Defer("waiting for the story's sources to be read", retry_in=30)
    # Platform-native music is added by the owner in the app; none is none.
    music = (bool(vault.secret(post["user_id"], "freesound_api_key"))
             and look.music_source_mode == "licensed_asset")
    look_text, judge = _video_look(post, t, category)
    if as_slides:
        system = (_system_prompt(st, target, revision, "none", speed, fmt, carousel_.count_hint(look), look_text)
                  + footage_.picture_section(footage) + _ai_pictures_note(look.ai_images) + "\n\n" + t.guide
                  + _music_section(music))
        writer = CAROUSEL_FACTORY(key)

        def tidy(o):
            carousel_.normalize(o, footage, music)

        def check(o):
            return carousel_.problems(o, t, look, footage)
    else:
        system = (_system_prompt(st, target, revision, post["audio_source"], speed, fmt, look_text=look_text)
                  + footage_.prompt_section(footage, narrated)
                  + (structure.writer_section(t, look, post["audio_source"]) if fmt else "")
                  + _music_section(music))
        writer = WRITER_FACTORY(key)

        def tidy(o):
            footage_.normalize(o, footage, music)
            if fmt:
                structure.normalize(o, t, look, post["audio_source"])

        def check(o):
            return validate(o, target, narrated=narrated, speed=speed, footage=footage, dialogue=dialogue,
                            template=t if fmt else None, look=look if fmt else None)
    user = (f"Topic: {post['topic']}\nBrief: {post['brief'] or '(none)'}" + _category_note(category)
            + sources_note(post.get("research")))
    input_sha = hashlib.sha256("\x1f".join([system, user, model]).encode()).hexdigest()

    billed = dict(user_id=post["user_id"], post_id=post_id, channel_id=post.get("channel_id"),
                  category_id=post.get("category_id"), job_id=ctx.job.get("id"))
    if judge is not None:
        judge.record("Jev: video look", **billed)

    def call(prompt: str):
        try:
            out, u = writer.write(model=model, system=system, user=prompt)
        except Exception as e:  # noqa: BLE001 - classified below
            if getattr(e, "usage", None) is not None:          # answered, so it was billed
                costs.record_llm(e.usage, note="unparsable script", **billed)
            raise _classify_openai_error(e) from e
        costs.record_llm(u, note="slides" if as_slides else "script", **billed)   # every call, repairs included
        return out, u

    out, usage = call(user)
    tidy(out)
    problems = check(out)
    # A draft that breaks a rule goes back with exactly what to fix: asking again
    # from scratch tends to repeat the same mistake (seen: one line too long, 3x).
    for _ in range(REPAIR_ROUNDS):
        if not problems:
            break
        out, more = call(f"{user}\n\n## Your previous draft\n{out.model_dump_json()}\n\n"
                         "## Fix this draft\nIt broke these rules. Return the complete script again "
                         "with exactly these problems fixed and everything else kept:\n"
                         + "\n".join(f"- {p}" for p in problems))
        usage = Usage(more.model, usage.input_tokens + more.input_tokens,
                      usage.output_tokens + more.output_tokens,
                      usage.cached_input_tokens + more.cached_input_tokens,
                      usage.cache_write_tokens + more.cache_write_tokens)
        tidy(out)
        problems = check(out)
    if problems:
        raise Retryable("script failed validation: " + "; ".join(problems), stage="validate",
                        detail={"problems": problems})

    shot_plan = [] if as_slides else [s.model_dump() for s in out.shots]
    slides = [s.model_dump() for s in out.slides] if as_slides else None
    # Automatic mode: nobody reads the script before it ships, so the desk editor does.
    held: list[str] = []
    if post.get("pipeline_mode") == "auto" and post.get("auto_approve"):
        held = _desk_review(key, model, out, post, billed)

    with db.tx() as c:
        locked = c.execute("select status, auto_approve from posts where id = %s for update",
                           (post_id,)).fetchone()
        if locked is None or locked["status"] != "scripting":
            return {"skipped": "post changed while the script was being written"}
        c.execute("""update scripts set state = 'superseded'
                      where post_id = %s and state in ('draft','awaiting_approval')""", (post_id,))
        script_id = c.execute(
            """insert into scripts (post_id, version, state, title, hook, description, hashtags,
                                    intended_dialogue, shot_plan, style_prompt, model,
                                    input_sha256, review, token_usage, format_id, format_version, music_mood,
                                    slides)
               values (%s, %s, 'awaiting_approval', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               returning id""",
            (post_id, version, out.title, out.hook, out.description, out.hashtags,
             "" if as_slides else out.intended_dialogue, Jsonb(shot_plan),
             "" if as_slides else out.style_prompt, usage.model, input_sha,
             Jsonb(out.review.model_dump()),
             Jsonb({"input": usage.input_tokens, "output": usage.output_tokens}),
             (fmt or {}).get("id"), (fmt or {}).get("version"), out.music_mood or None,
             Jsonb(slides) if slides is not None else None)).fetchone()["id"]
        c.execute("update posts set status = 'awaiting_approval', error = null where id = %s",
                  (post_id,))
        db.log_event(c, post_id, "scripting", "awaiting_approval",
                     f"worker:{settings().worker_id}", "script written",
                     {"script_id": str(script_id), "version": version, "model": usage.model})
        if locked["auto_approve"] and not held:
            c.execute("select private.approve_script(%s, 'system:auto_approve')", (script_id,))
        elif held:
            db.log_event(c, post_id, "awaiting_approval", "awaiting_approval", "system:auto",
                         "held for your review: " + "; ".join(held)[:500], {"issues": held})
    return {"script_id": str(script_id), "auto_approved": bool(locked["auto_approve"]) and not held,
            "held": held, "template": t.template_id, "slides": len(slides) if slides is not None else None,
            "shots": len(shot_plan), "tokens": usage.input_tokens + usage.output_tokens}


SOURCES_CHARS = 9000


def sources_note(research: dict | None) -> str:
    """The story's sources, read in full (research_post), for the writer and the desk editor."""
    articles = (research or {}).get("articles") or []
    if not articles:
        return ""
    per = max(1200, SOURCES_CHARS // len(articles))
    parts = [f"### {a['site']} — {a.get('title') or a['url']}\n{a['text'][:per]}" for a in articles]
    return ("\n\n## What the sources report (the only facts you may use; attribute claims to them)\n"
            + "\n\n".join(parts))


def _video_look(post: dict, t, category: dict | None):
    """(the look's words for generated shots, or None for the format's own; the Jev
    client if one decided). Chosen once per post and stored on it."""
    look_id, judge = post.get("look_id"), None
    if not look_id:
        with db.conn() as c:
            ch = (c.execute("select video_look from channels where id = %s", (post["channel_id"],)).fetchone()
                  if post.get("channel_id") else None) or {}
        setting = ch.get("video_look") or "auto"
        judge = jev.for_user(post["user_id"]) if setting == "auto" else None
        look_id, why = looks.choose(judge, setting, story=f"{post['topic']}. {post.get('brief') or ''}",
                                    category=f"{(category or {}).get('name', '')}: {(category or {}).get('brief', '')}",
                                    template=t)
        with db.conn() as c:
            c.execute("update posts set look_id = %s, look_why = %s where id = %s", (look_id, why, post["id"]))
    vl = looks.get(look_id)
    return (vl.prompt if vl else None), judge


def _ai_pictures_note(mode: str) -> str:
    """What this format allows of AI pictures, so the writer (and its caption) never claims otherwise."""
    return {"none": "\n\nThis format draws no AI pictures: never use \"ai_image\", and never say the visuals are "
                    "AI-generated.",
            "cover": "\n\nThis format draws an AI picture for the first slide only, when it has no picture of its own.",
            "all": "\n\nThis format may draw an AI picture for any slide that has no picture of its own."}[mode]


def _music_section(available: bool) -> str:
    if not available:
        return "\n\n## Music\n`music_mood` is \"\" (no background music for this reel)."
    return ("\n\n## Music\n`music_mood`: the background track's mood, one of "
            + ", ".join(m for m in MUSIC_MOODS if m)
            + ". Give almost every reel one: it fills the moments without narration or sound and dips under the "
              "voice by itself. Use \"\" only when music would be in poor taste (a death, a tragedy).")


def _category(c, post: dict) -> dict | None:
    if not post.get("category_id"):
        return None
    return c.execute("select name, brief from categories where id = %s", (post["category_id"],)).fetchone()


def _category_note(category: dict | None) -> str:
    """The owner's prompt for the category this post came from: what it is for, and its rules."""
    if not category or not (category.get("brief") or "").strip():
        return ""
    return f"\n\n## Category: {category['name']}\nThe owner's instructions for this category:\n{category['brief'].strip()}"


def _desk_review(key: str, model: str, out, post: dict, billed: dict) -> list[str]:
    """[] when the script may be approved unattended; else what stops it."""
    with db.conn() as c:
        items = c.execute("select items from ideas where post_id = %s", (post["id"],)).fetchone()
    with db.conn() as c:
        category = _category(c, post)
    lines = [f"Topic: {post['topic']}", f"Brief: {post['brief'] or '(none)'}" + _category_note(category)
             + sources_note(post.get("research"))]
    for it in (items or {}).get("items") or []:
        lines.append(f"- {it.get('source', '')}: {it.get('title', '')} — {it.get('summary', '')} ({it.get('url', '')})")
    try:
        verdict, usage = REVIEWER_FACTORY(key).review(model=model, script=out.model_dump_json(),
                                                     sources="\n".join(lines))
    except Exception as e:  # noqa: BLE001 - unreviewed means held, never approved
        if getattr(e, "usage", None) is not None:
            costs.record_llm(e.usage, note="unparsable desk review", **billed)
        return [f"the desk editor could not be reached ({type(e).__name__})"]
    costs.record_llm(usage, note="desk review", **billed)
    return [] if verdict.ok else (verdict.issues or ["the desk editor flagged it without saying why"])


def on_give_up(ctx: JobContext, err: dict) -> None:
    with db.tx() as c:
        row = c.execute("select status from posts where id = %s for update",
                        (ctx.job["post_id"],)).fetchone()
        if row and row["status"] == "scripting":
            c.execute("update posts set status = 'failed', error = %s where id = %s",
                      (Jsonb({k: err[k] for k in ("stage", "message")}), ctx.job["post_id"]))
            db.log_event(c, ctx.job["post_id"], "scripting", "failed", "system",
                         "script writing gave up", {"stage": err["stage"]})


HANDLER = Handler(run=run, on_give_up=on_give_up)
