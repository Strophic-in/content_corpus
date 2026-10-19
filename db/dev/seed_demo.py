"""A demo workspace on the local TEST database, for working on the web app's screens:
a news channel with categories, idea cards to swipe, and posts at every stage (draft,
writing, waiting for review, approved, rendering, ready with its caption, scheduled,
posted with numbers, failed).

    python db/dev/seed_demo.py owner@corpus.test      # the account must exist (sign up locally first)

Refuses any database but corpus_test: the repo's .env points at production.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

URL = os.environ.get("TEST_DATABASE_URL_OWNER", "postgres://app_owner:localdev@127.0.0.1:55442/corpus_test")

IDEAS = [
    ("India", "Monsoon floods cut off 40 villages in Assam overnight",
     "Rivers rose two metres in six hours.", "The Brahmaputra and two tributaries burst their banks after 300 mm of "
     "rain; rescue teams are using boats to reach villages cut off since midnight.", "Breaking this morning"),
    ("World", "Iceland's volcano erupts again, lava heads for Grindavik",
     "The town was evacuated for the fifth time.", "A fissure opened north of Grindavik; the barriers built last "
     "year are being tested again as lava flows towards the town.", "Live footage on RÚV"),
    ("Science & Space", "ISRO's Gaganyaan crew capsule passes its last splashdown test",
     "The capsule hit the sea at 7 m/s — on target.", "The final drop test cleared the parachutes and flotation "
     "system for India's first crewed flight.", "ISRO statement, 2 h ago"),
    ("Technology & AI", "A new AI model finds 30 bugs in the Linux kernel in a week",
     "Maintainers have already merged 12 fixes.", "Researchers ran the model against the kernel's networking code; "
     "maintainers confirmed and patched a dozen of the issues.", "Hacker News front page"),
    ("India", "Delhi's air quality hits 'severe' for the first time this season",
     "AQI crossed 450 at 6 am.", "Stubble burning and still winds pushed pollution to the season's worst; schools "
     "may move online.", "CPCB data this morning"),
    ("World", "Venice's acqua alta reaches 140 cm — the barriers rise",
     "St Mark's Square stays dry for once.", "The MOSE flood barriers were raised for the fourth time this autumn as "
     "the tide hit 140 cm.", "Live from Venice"),
]

STAGES = [   # (status, topic, days from today, with script?, shots uploaded of 5, extras)
    ("draft", "Why Bengaluru's lakes are foaming again", 4, False, 0, {}),
    ("scripting", "Chandrayaan-4: what the sample-return mission will bring back", 3, False, 0, {}),
    ("awaiting_approval", "The bridge in Gujarat that collapsed twice in ten years", 2, True, 0, {}),
    ("approved", "How Tokyo's flood tunnels saved the city this week", 2, True, 0, {}),
    ("rendering", "Mumbai's coastal road: before and after the monsoon", 1, True, 3, {}),
    ("ready", "Limoges town hall spire collapses in protest fire", 1, True, 5, {"package": True}),
    ("scheduled", "Why the Northern Lights were seen from Ladakh", 0, True, 5, {"package": True}),
    ("published", "France protests: over 1,200 arrested in a night of unrest", -1, True, 5,
     {"package": True, "live": True}),
    ("failed", "Inside the world's largest solar farm in Rajasthan", -2, True, 2,
     {"error": "The GPU pod didn't start in time — try rendering again"}),
]

NARRATION = ["The BBC reports a historic town hall spire collapsed in flames.",
             "More than half a million people joined protests across France.",
             "Police report over 1,200 arrests in a single night.",
             "Officials have not said what happens next for the building.",
             "Follow for the next update on this story."]


def main(email: str) -> None:
    with psycopg.connect(URL, autocommit=True, row_factory=dict_row) as c:
        db = c.execute("select current_database() as d").fetchone()["d"]
        if db != "corpus_test":
            sys.exit(f"refusing: this is {db!r}, not corpus_test")
        u = c.execute('select id from "user" where email = %s', (email,)).fetchone()
        if not u:
            sys.exit(f"no account {email} — sign up on the local app first")
        uid = u["id"]
        ch = c.execute("select id from channels where user_id = %s order by is_default desc limit 1", (uid,)).fetchone()
        if not ch:
            sys.exit("no channel yet — open /discover once on the local app")
        chid = ch["id"]
        c.execute("""update channels set name = 'Trendcaster', niche = %s, audience = %s where id = %s""",
                  ("Daily news Shorts: the most-talked-about stories of the day, told fast and straight.",
                   "News-curious viewers aged 16-40, on their phones.", chid))
        fmt = c.execute("select id, name from formats where channel_id = %s order by is_default desc, created_at",
                        (chid,)).fetchall()
        cats = {}
        for name, color in [("India", "#f97316"), ("World", "#3b82f6"), ("Science & Space", "#14b8a6"),
                            ("Technology & AI", "#818cf8")]:
            cats[name] = c.execute(
                """insert into categories (user_id, channel_id, name, color, brief, format_ids, ideas_per_batch)
                   values (%s, %s, %s, %s, 'Demo category.', '{}', 2)
                   on conflict (channel_id, name) do update set color = excluded.color returning id""",
                (uid, chid, name, color)).fetchone()["id"]
        c.execute("delete from ideas where channel_id = %s and status = 'new'", (chid,))
        for k, (cat, title, hook, brief, why) in enumerate(IDEAS):
            c.execute("""insert into ideas (user_id, channel_id, category_id, format_id, title, hook, brief, why_now,
                                            items, format_why)
                         values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                      (uid, chid, cats[cat], fmt[k % len(fmt)]["id"], title, hook, brief, why,
                       Jsonb([{"url": f"https://www.bbc.co.uk/news/demo-{k}", "title": title}]),
                       "Jev's pick (87% sure)"))
        c.execute("delete from posts where channel_id = %s and topic = any(%s)", (chid, [s[1] for s in STAGES]))
        for status, topic, days, scripted, done, extra in STAGES:
            pid = c.execute(
                """insert into posts (user_id, channel_id, category_id, format_id, topic, brief, slot_date,
                                      publish_at, audio_source, target_seconds, research_state)
                   values (%s, %s, %s, %s, %s, %s, %s, (%s::date + time '18:00') at time zone 'Asia/Kolkata',
                           'kokoro', 30, 'ready') returning id""",
                (uid, chid, cats["World"], fmt[0]["id"], topic, f"Demo brief for: {topic}.",
                 date.today() + timedelta(days=days), date.today() + timedelta(days=days))).fetchone()["id"]
            sid = None
            if scripted:
                plan = [{"seconds": 6, "visual": "Demo shot", "audio": "", "narration": n, "source": "generate",
                         "role": "what_happened", "text": n.split(",")[0][:40]} for n in NARRATION]
                sid = c.execute(
                    """insert into scripts (post_id, version, state, title, hook, description, hashtags, shot_plan,
                                            style_prompt, model, review)
                       values (%s, 1, %s, %s, %s, %s, %s, %s, '', 'gpt-6-luna', %s) returning id""",
                    (pid, "awaiting_approval" if status == "awaiting_approval" else "approved", topic,
                     "The moment it fell.", "Demo description.", ["#news", "#shorts"], Jsonb(plan),
                     Jsonb({"score": 8, "risks": ["Numbers from one report"], "notes": "Clear and sourced."}))
                ).fetchone()["id"]
                if status != "awaiting_approval":
                    c.execute("update posts set approved_script_id = %s where id = %s", (sid, pid))
                    for i in range(5):
                        c.execute("""insert into shots (post_id, script_id, idx, prompt, seed, width, height,
                                                        num_frames, fps, source, state, narration)
                                     values (%s, %s, %s, 'demo', %s, 704, 1280, 145, 24, 'generate', %s, %s)""",
                                  (pid, sid, i, 1000 + i, "uploaded" if i < done else "planned", NARRATION[i]))
            pkg = None
            if extra.get("package"):
                pkg = {"title": topic, "hook_line": "The moment it fell, caught on camera.",
                       "caption": "What happened, why it matters, and what comes next.\nWhat do you think?",
                       "hashtags": ["#news", "#world", "#shorts"], "first_comment": "Should it be rebuilt as it was?",
                       "thumbnail_text": "SPIRE GONE", "kicker": "BREAKING", "thumbnail_key": "",
                       "sources": [{"site": "BBC News", "title": topic, "url": "https://www.bbc.co.uk/news/demo"}],
                       "made_at": "2026-10-19T10:00:00Z", "script_id": str(sid)}
            c.execute("""update posts set status = %s, package = %s, error = %s,
                                          final_key = case when %s then 'demo/final.mp4' end,
                                          final_duration_s = case when %s then 31.6 end
                          where id = %s""",
                      (status, Jsonb(pkg) if pkg else None,
                       Jsonb({"message": extra["error"], "stage": "render"}) if extra.get("error") else None,
                       status in ("ready", "scheduled", "published"), status in ("ready", "scheduled", "published"),
                       pid))
            if extra.get("live"):
                for platform, url in (("youtube", "https://youtube.com/shorts/demo"),
                                      ("instagram", "https://www.instagram.com/reel/demo/")):
                    c.execute("""insert into publish_attempts (post_id, platform, state, remote_id, remote_url, privacy)
                                 values (%s, %s, 'live', 'demo', %s, 'public')""", (pid, platform, url))
                    c.execute("""insert into post_stats (post_id, user_id, platform, views, likes, comments)
                                 values (%s, %s, %s, %s, %s, %s) on conflict do nothing""",
                              (pid, uid, platform, 18400 if platform == "youtube" else 9200, 1210, 87))
        print(f"seeded: {len(IDEAS)} idea cards, {len(STAGES)} posts on channel {chid}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "owner@corpus.test")
