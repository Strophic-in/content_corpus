"""cpu/write_script — topic → a script version awaiting approval.

Safe to retry: the version number comes from the job (fixed at enqueue), and a
retry that finds that version already written returns it instead of paying for
another LLM call. Everything the call produces lands in one transaction. A draft
that breaks a rule (validate()) is sent back to the model with the exact problems,
up to REPAIR_ROUNDS times, before the attempt counts as failed.
"""

from __future__ import annotations

import hashlib

from psycopg.types.json import Jsonb

from .. import channels, costs, db, prompts, vault
from ..config import settings
from ..runner import Handler, JobContext, Permanent, Retryable
from ..script.llm import (NARRATOR_WORDS_PER_SECOND, OpenAIScriptWriter, ScriptWriter, Usage,
                          narration_word_cap, validate)
from ..script.review import OpenAIReviewer

# Swapped out by tests; production always talks to OpenAI with the user's key.
WRITER_FACTORY = OpenAIScriptWriter
REVIEWER_FACTORY = OpenAIReviewer
# Extra calls per attempt that hand the model its own draft and the rules it broke.
REPAIR_ROUNDS = 2


# audio_source → prompt. 'kokoro' is narrated mode: one TTS voice-over across the
# reel, visuals with sound effects only. 'ltx_native': characters speak on screen.
def _system_prompt(st: dict, target_seconds: int, revision_note: str, audio_source: str,
                   speed: float = 1.1, fmt: dict | None = None) -> str:
    """The script writer's instructions: the post's format's prompt (prompt library),
    or the shipped default for posts made before formats existed."""
    template = fmt["script_prompt"] if fmt else prompts.default(f"script:{audio_source}")
    look = fmt["visual_style"] if fmt else prompts.default("visual_style")
    shots = max(1, round(target_seconds / 8))
    cap = narration_word_cap(speed)
    return prompts.fill(template, {
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
    speed = float(st.get("narrator_speed") or 1.1)
    system = _system_prompt(st, target, revision, post["audio_source"], speed, fmt)
    user = f"Topic: {post['topic']}\nBrief: {post['brief'] or '(none)'}"
    input_sha = hashlib.sha256("\x1f".join([system, user, model]).encode()).hexdigest()

    writer: ScriptWriter = WRITER_FACTORY(key)
    billed = dict(user_id=post["user_id"], post_id=post_id, channel_id=post.get("channel_id"),
                  category_id=post.get("category_id"), job_id=ctx.job.get("id"))

    def call(prompt: str):
        try:
            out, u = writer.write(model=model, system=system, user=prompt)
        except Exception as e:  # noqa: BLE001 - classified below
            if getattr(e, "usage", None) is not None:          # answered, so it was billed
                costs.record_llm(e.usage, note="unparsable script", **billed)
            raise _classify_openai_error(e) from e
        costs.record_llm(u, note="script", **billed)              # every call, repairs included
        return out, u

    out, usage = call(user)
    problems = validate(out, target, narrated=narrated, speed=speed)
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
                      usage.cached_input_tokens + more.cached_input_tokens)
        problems = validate(out, target, narrated=narrated, speed=speed)
    if problems:
        raise Retryable("script failed validation: " + "; ".join(problems), stage="validate",
                        detail={"problems": problems})

    shot_plan = [s.model_dump() for s in out.shots]
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
                                    input_sha256, review, token_usage, format_id, format_version)
               values (%s, %s, 'awaiting_approval', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               returning id""",
            (post_id, version, out.title, out.hook, out.description, out.hashtags,
             out.intended_dialogue, Jsonb(shot_plan), out.style_prompt, usage.model, input_sha,
             Jsonb(out.review.model_dump()),
             Jsonb({"input": usage.input_tokens, "output": usage.output_tokens}),
             (fmt or {}).get("id"), (fmt or {}).get("version"))).fetchone()["id"]
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
            "held": held,
            "shots": len(shot_plan), "tokens": usage.input_tokens + usage.output_tokens}


def _desk_review(key: str, model: str, out, post: dict, billed: dict) -> list[str]:
    """[] when the script may be approved unattended; else what stops it."""
    with db.conn() as c:
        items = c.execute("select items from ideas where post_id = %s", (post["id"],)).fetchone()
    lines = [f"Topic: {post['topic']}", f"Brief: {post['brief'] or '(none)'}"]
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
