"""ideas/check_sources and ideas/suggest_sources — keep a category's sources honest.

check_sources: every source of the category not yet checked (or in error) is
tried once — Reddit communities together in one request (a community with a post
in the combined /new feed exists and is public), sites by discovering their
feeds, feeds and searches by reading them — and marked ok or with the error.

suggest_sources: the model proposes Reddit and Lemmy communities, Mastodon
hashtags and news sites that fit the category's prompt; each proposal is checked
the same way (hashtags need no check), and the owner adds the good ones from the
job's result. Nothing is added by itself.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from .. import channels, costs, db, vault
from ..ideas import reddit, sites, social, sources
from ..runner import Handler, JobContext, Permanent
from ..script.llm import Unparsed, Usage
from .suggest_ideas import _record_outcomes
from .write_script import _classify_openai_error


class Suggestion(BaseModel):
    name: str
    why: str


class SourceIdeas(BaseModel):
    communities: list[Suggestion]     # subreddit names, without r/
    lemmy: list[Suggestion]           # community@instance, e.g. technology@lemmy.world
    hashtags: list[Suggestion]        # Mastodon hashtags, without #
    sites: list[Suggestion]           # domains, e.g. reuters.com


class OpenAISuggester:
    def __init__(self, api_key: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=90, max_retries=2)

    def suggest(self, *, model: str, prompt: str) -> tuple[SourceIdeas, Usage]:
        resp = self.client.responses.parse(model=model, input=prompt, text_format=SourceIdeas)
        if resp.output_parsed is None:
            raise Unparsed("no suggestions came back", Usage.of(resp))
        return resp.output_parsed, Usage.of(resp)


# Swapped by tests.
SUGGESTER = OpenAISuggester
CHECK = sources.fetch


def _rows(category_id, only_unchecked: bool) -> list[dict]:
    with db.conn() as c:
        return c.execute(f"""select id, kind, value, options from category_sources
                             where category_id = %s and enabled
                             {"and status <> 'ok'" if only_unchecked else ""}
                             order by created_at""", (category_id,)).fetchall()


def check(ctx: JobContext) -> dict:
    rows = _rows(ctx.payload["category_id"], only_unchecked=True)
    if not rows:
        return {"checked": 0}
    user_id = db.one("select user_id from categories where id = %s", (ctx.payload["category_id"],))
    key = vault.secret(user_id["user_id"], "youtube_api_key") if user_id else None
    with httpx.Client(timeout=30) as client:
        _, outcomes = CHECK(rows, client=client, youtube_key=key,
                            log=lambda m: print(f"[check_sources] {m}", flush=True))
    _record_outcomes(outcomes)
    return {"checked": len(outcomes), "ok": sum(o.ok for o in outcomes),
            "errors": {o.source_id: o.error for o in outcomes if not o.ok}}


def suggest(ctx: JobContext) -> dict:
    with db.conn() as c:
        cat = c.execute("select * from categories where id = %s", (ctx.payload["category_id"],)).fetchone()
        if cat is None:
            return {"skipped": "category deleted"}
        st = c.execute("select script_model from app_settings where user_id = %s", (cat["user_id"],)).fetchone() or {}
        prof = channels.profile(c, cat["user_id"], cat["channel_id"])
        have = {(r["kind"], r["value"].lower()) for r in c.execute(
            "select kind, value from category_sources where category_id = %s", (cat["id"],)).fetchall()}
    key = vault.secret(cat["user_id"], "openai")
    if not key or not st.get("script_model"):
        raise Permanent("Add your OpenAI key and choose a script model in Settings.", stage="config")
    prompt = (f"A short-video channel '{prof.get('channel_name')}' ({prof.get('channel_niche') or 'no niche set'}) "
              f"has a category '{cat['name']}'.\nBrief: {cat['brief'] or '(none)'}\n"
              f"Keywords: {cat['keywords'] or '(none)'}\n\n"
              "Suggest up to 10 active, public, safe-for-work Reddit communities (names only, without r/) whose "
              "top posts of the day would feed this category with stories — prefer communities that share "
              "videos and pictures; up to 6 active Lemmy communities as name@instance (for example "
              "technology@lemmy.world); up to 6 Mastodon hashtags people use for it (without #); and up to 6 "
              "news sites (domains) that report it reliably. Real, existing ones only; say in a few words why "
              "each fits.")
    billed = dict(user_id=cat["user_id"], channel_id=cat["channel_id"], category_id=cat["id"],
                  job_id=ctx.job.get("id"))
    try:
        out, usage = SUGGESTER(key).suggest(model=st["script_model"], prompt=prompt)
    except Exception as e:  # noqa: BLE001
        if getattr(e, "usage", None) is not None:
            costs.record_llm(e.usage, note="unparsable source suggestions", **billed)
        raise _classify_openai_error(e) from e
    costs.record_llm(usage, note=f"source suggestions: {cat['name']}", **billed)

    names = [s.name.strip().removeprefix("r/").strip("/") for s in out.communities][:10]
    names = [n for n in names if n and ("reddit", n.lower()) not in have]
    live: set[str] = set()
    with httpx.Client(timeout=30) as client:
        if names:
            try:
                live = reddit.existing(client, names)
            except reddit.RedditError:
                live = set()                     # the owner can still add them; checking happens on add
        site_found = {}
        for s in out.sites[:6]:
            d = sites.host_key(sites.normalize_domain(s.name))
            if d and ("site", d) not in have:
                site_found[d] = len(sites.discover(client, d))
        lemmy_found = {}
        for s in out.lemmy[:6]:
            v = s.name.strip().removeprefix("!").removeprefix("c/").lower()
            if "@" in v and ("lemmy", v) not in have:
                lemmy_found[v] = (social.lemmy_community_exists(client, v), s.why)
    why = {s.name.strip().removeprefix("r/").strip("/").lower(): s.why for s in out.communities}
    tags = {s.name.strip().lstrip("#").replace(" ", ""): s.why for s in out.hashtags[:6]}
    return {"communities": [{"name": n, "exists": n.lower() in live, "why": why.get(n.lower(), "")}
                            for n in names],
            "lemmy": [{"name": v, "exists": ok, "why": w} for v, (ok, w) in lemmy_found.items()],
            "hashtags": [{"name": t, "why": w} for t, w in tags.items()
                         if t and ("mastodon", f"#{t}@mastodon.social".lower()) not in have],
            "sites": [{"domain": d, "feeds": n, "why": next((s.why for s in out.sites
                                                            if sites.host_key(sites.normalize_domain(s.name)) == d),
                                                           "")} for d, n in site_found.items()]}


CHECK_HANDLER = Handler(run=check)
SUGGEST_HANDLER = Handler(run=suggest)
