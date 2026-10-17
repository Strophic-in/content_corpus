# Templates

A **template** is a kind of post — a narrated 3D explainer, a full-screen text
reel, a countdown, an Instagram carousel, a picture card… A **format** (the
Formats page, the `formats` table) is one template plus a channel's own prompts
and look (`formats.params`). A **category** allows some of its channel's formats
(`categories.format_ids`; none ticked = all of them) and the idea agent picks one
per idea; the owner can change it on the swipe.

Nothing is called "viral": each format's results are compared with the channel's
own usual views (the idea agent sees that, and so does the format's page).

## Where things live

| What | Where |
|---|---|
| The 22 templates: metadata and render defaults | `prompts/templates/<id>.json` |
| Each template's guide for the script writer | `prompts/templates/<id>.md` |
| Base prompts new formats start from | `prompts/script_video.md`, `script_carousel.md` (and the older `script_narrated.md`, `script_news.md`, `script_reel.md`) |
| Loading, validation, a format's resolved look | `worker/corpus/templates.py` (web: `apps/web/lib/templates.ts`) |
| What a script must satisfy per template | `worker/corpus/script/structure.py` (shots), `script/carousel.py` (slides) |
| On-screen text: headlines, beats, chips, kinetic words | `worker/corpus/media/overlays.py` (measured with `media/text.py`) |
| Split screens, transitions, loop seams | `media/assemble.py` (`build_segment`, `join_segments`) |
| Plain backgrounds, punch-ins, timelapse, charts | `media/footage.py`, charts drawn by `media/slides.py` |
| Carousels and cards (slides + YouTube slideshow) | `media/slides.py`, `handlers/render_slides.py` |
| Instagram carousel and picture posts | `publish/instagram.py` |
| The database side | `db/migrations/0021_templates.sql` |

A template file holds the fields of the shared schema (`template_id`,
`content_type`, `supported_platforms`, `aspect_ratio`,
`recommended_duration_seconds`, `recommended_slide_count`, `required_assets`,
`scene_structure`, `caption_style`, `music_mood`, `music_source_mode`,
`automation_level`, `estimated_render_cost`, `rights_requirements`, notes…) and a
`render` block of defaults: captions mode (`karaoke`, `beats`, `kinetic`,
`speech`, `none`), headline and chips, layouts (`full`, `split`), transitions,
the audio it allows (`kokoro` narration, `none`, `ltx_native`), shot sources,
chart kinds, loop, timelapse, punch-in, and `slides` for carousels and cards.
Every file is validated when it loads; a broken one stops the worker rather than
being skipped.

A format's `params` may change: captions mode, transition, layout, font
(Montserrat or Noto Serif), text/accent/background/panel colours, caption
position, side margin, music mode (`licensed_asset` = a CC0 track,
`platform_native` = none in the file and not posted automatically, `none`),
brand line, slide shape (4:5 or 1:1), slide count and when to draw AI pictures
(`cover`, `all`, `none`). Both the web form and the worker check them against
the template.

## Preview every template

No model calls, no GPU, no database — the real renderers with canned content:

```bash
cd worker
python -m corpus.demo                                   # all 22 → ./template-demos
python -m corpus.demo ranked_countdown kinetic_typography --out /tmp/demos
python -m corpus.demo --posters ../apps/web/public/templates   # the Formats gallery's pictures
```

Generated and footage shots are stood in for by abstract moving pictures, and
captions are timed evenly (there is no voice).

## Adding a template

1. `prompts/templates/<id>.json` (copy the closest one) and `<id>.md`.
2. A row in the `templates` table (a migration) with the same id and content type —
   a test checks the files and the table agree.
3. If its structure has rules a draft must meet (labels that count down, a
   required text on every shot…), add them to `script/structure.py`.
4. Its poster: `python -m corpus.demo <id> --posters ../apps/web/public/templates`.

## Tests

```bash
bash db/dev/test.sh                                   # everything, on the local test database
bash db/dev/test.sh worker/tests/test_templates.py    # the templates alone
```
