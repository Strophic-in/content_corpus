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

from .. import db, vault
from ..config import settings
from ..runner import Handler, JobContext, Permanent, Retryable
from ..script.llm import (NARRATOR_WORDS_PER_SECOND, OpenAIScriptWriter, ScriptWriter, Usage,
                          narration_word_cap, validate)

# Swapped out by tests; production always talks to OpenAI with the user's key.
WRITER_FACTORY = OpenAIScriptWriter
# Extra calls per attempt that hand the model its own draft and the rules it broke.
REPAIR_ROUNDS = 2


# audio_source → prompt. 'kokoro' is narrated mode: one TTS voice-over across the
# reel, visuals with sound effects only. 'ltx_native': characters speak on screen.
TEMPLATES = {"ltx_native": "script_reel.md", "kokoro": "script_narrated.md"}


def _system_prompt(st: dict, target_seconds: int, revision_note: str, audio_source: str,
                   speed: float = 1.1) -> str:
    template = (settings().prompts_dir / TEMPLATES[audio_source]).read_text(encoding="utf-8")
    shots = max(1, round(target_seconds / 8))
    cap = narration_word_cap(speed)
    return template.format_map({
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

    target = post["target_seconds"] or st.get("default_reel_seconds") or 24
    revision = ""
    if rejected:
        revision = (f"## Revision\nThe previous version (\"{rejected['title']}\") was rejected "
                    f"with this note — address it:\n{rejected['rejection_note']}")
    narrated = post["audio_source"] == "kokoro"
    speed = float(st.get("narrator_speed") or 1.1)
    system = _system_prompt(st, target, revision, post["audio_source"], speed)
    user = f"Topic: {post['topic']}\nBrief: {post['brief'] or '(none)'}"
    input_sha = hashlib.sha256("\x1f".join([system, user, model]).encode()).hexdigest()

    writer: ScriptWriter = WRITER_FACTORY(key)

    def call(prompt: str):
        try:
            return writer.write(model=model, system=system, user=prompt)
        except Exception as e:  # noqa: BLE001 - classified below
            raise _classify_openai_error(e) from e

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
                      usage.output_tokens + more.output_tokens)
        problems = validate(out, target, narrated=narrated, speed=speed)
    if problems:
        raise Retryable("script failed validation: " + "; ".join(problems), stage="validate",
                        detail={"problems": problems})

    shot_plan = [s.model_dump() for s in out.shots]
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
                                    input_sha256, review, token_usage)
               values (%s, %s, 'awaiting_approval', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               returning id""",
            (post_id, version, out.title, out.hook, out.description, out.hashtags,
             out.intended_dialogue, Jsonb(shot_plan), out.style_prompt, usage.model, input_sha,
             Jsonb(out.review.model_dump()),
             Jsonb({"input": usage.input_tokens, "output": usage.output_tokens}))).fetchone()["id"]
        c.execute("update posts set status = 'awaiting_approval', error = null where id = %s",
                  (post_id,))
        db.log_event(c, post_id, "scripting", "awaiting_approval",
                     f"worker:{settings().worker_id}", "script written",
                     {"script_id": str(script_id), "version": version, "model": usage.model})
        if locked["auto_approve"]:
            c.execute("select private.approve_script(%s, 'system:auto_approve')", (script_id,))
    return {"script_id": str(script_id), "auto_approved": bool(locked["auto_approve"]),
            "shots": len(shot_plan), "tokens": usage.input_tokens + usage.output_tokens}


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
