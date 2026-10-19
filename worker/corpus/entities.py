"""Who and what a story names, and their pictures: a company's logo, a person's or a
place's photo — from Wikipedia and Wikidata, before the script.

A story about Jio Platforms' IPO is about Jio: the reel should show Jio's logo when
it names Jio, not an "unmarked glass tower" (live, 2026-10-19: a reel about the Jio
and Paras Healthcare IPOs had only abstract generated shots). So research_post asks
the script model for the story's named companies, people, products and places
(extract), and for each looks up its Wikipedia article and that article's Wikidata
item: the logo (P154) of a company, organisation or product, the image (P18) of a
person or place (lookup). The file comes from Wikimedia Commons, which also renders
SVG logos as PNG at any width, with its licence and author for the credit.

A place also brings its flag (P41) and its locator map (P242): news happens anywhere,
and "where" is often the first thing a viewer needs. A Wikipedia search can land on the wrong article ("Paras" → a mountain), so a match
must carry the name's own words in its title (_same_name). A logo is drawn on a
clean card at reel size (logo_card) — a transparent PNG would otherwise come out on
black — and LTX can't draw a logo, so the writer shows it as a still picture.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from .research import sig_tokens

log = logging.getLogger("corpus.entities")

WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
UA = "ContentCorpus/1.0 (asset finder; https://content-corpus.strophic.in)"
MAX_ENTITIES = 5
LOGO_KINDS = ("company", "organisation", "product")
PHOTO_KINDS = ("person", "place")


class Named(BaseModel):
    name: str = Field(description="As Wikipedia would title it: 'Jio Platforms', 'Narendra Modi', 'Limoges'")
    kind: Literal["company", "organisation", "product", "person", "place"]
    central: bool = Field(description="True if the story is about this one; false for a passing mention")


class NamedOut(BaseModel):
    names: list[Named]


EXTRACT_PROMPT = f"""List the companies, organisations, products, people and places this news story names, at most
{MAX_ENTITIES}, the most important first. Use each one's full proper name as its Wikipedia article would title it.
Leave out generic things ("investors", "the market", "a hospital"), media outlets that only report the story,
and anything not named in the text."""


@dataclass
class Entity:
    name: str
    kind: str
    central: bool


def extract(api_key: str, model: str, text: str) -> tuple[list[Entity], object | None]:
    """(the story's named entities, the model call's usage for the ledger)."""
    from openai import OpenAI

    from .script.llm import Usage

    client = OpenAI(api_key=api_key, timeout=60, max_retries=1)
    r = client.responses.parse(model=model, instructions=EXTRACT_PROMPT, input=text[:6000], text_format=NamedOut)
    out = r.output_parsed.names if r.output_parsed else []
    seen, ents = set(), []
    for n in out:
        key = n.name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            ents.append(Entity(n.name.strip(), n.kind, n.central))
    return ents[:MAX_ENTITIES], Usage.of(r)


def _same_name(name: str, title: str) -> bool:
    """The article is about this name: every significant word of the name is in its title
    ("Jio Platforms" ✓ "Jio Platforms"; "Paras Healthcare" ✗ "Paras (mountain)")."""
    want = sig_tokens(name)
    return bool(want) and want <= sig_tokens(title)


def _article(client: httpx.Client, name: str) -> tuple[str, str, str] | None:
    """(the Wikipedia article's title, its Wikidata item id, its lead picture's file name
    or "") for `name`, or None."""
    r = client.get(WIKIPEDIA, params={"action": "query", "generator": "search", "gsrsearch": name, "gsrlimit": 3,
                                      "prop": "pageprops|pageimages", "ppprop": "wikibase_item", "piprop": "name",
                                      "redirects": 1, "format": "json"}, headers={"User-Agent": UA}, timeout=20)
    pages = sorted(((r.json().get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        qid = (p.get("pageprops") or {}).get("wikibase_item")
        if qid and _same_name(name, p.get("title", "")):
            return p["title"], qid, p.get("pageimage") or ""
    return None


# A country's or a region's lead picture is often a map, a flag or a seal: kept, as what it is.
_MAP = re.compile(r"map|locator|location|orthographic|relief", re.I)
_FLAG = re.compile(r"flag", re.I)
_EMBLEM = re.compile(r"coat[_ ]of[_ ]arms|emblem|seal[_ .]", re.I)
# Graphics, drawn on a card and shown still: the video model warps their lines and letters.
GRAPHIC_ROLES = ("logo", "flag", "map")


def _is_logo(file: str) -> bool:
    return bool(re.search(r"logo|wordmark|emblem|\.svg$", file, re.I))


def _claim_file(client: httpx.Client, qid: str, prop: str) -> str | None:
    """The item's current file for `prop`: the preferred one, else the last that has no
    end date (Meta Platforms lists Facebook's old logos too, ended, besides its own)."""
    r = client.get(WIKIDATA, params={"action": "wbgetclaims", "entity": qid, "property": prop, "format": "json"},
                   headers={"User-Agent": UA}, timeout=20)
    current = []
    for c in (r.json().get("claims") or {}).get(prop) or []:
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, str) and v and c.get("rank") != "deprecated" and "P582" not in (c.get("qualifiers") or {}):
            current.append((c.get("rank") == "preferred", v))
    return max(current, key=lambda x: x[0])[1] if current else None


def _commons_file(client: httpx.Client, file: str, width: int) -> dict | None:
    r = client.get(COMMONS, params={"action": "query", "titles": f"File:{file}", "prop": "imageinfo",
                                    "iiprop": "url|extmetadata", "iiurlwidth": width, "format": "json"},
                   headers={"User-Agent": UA}, timeout=20)
    for page in ((r.json().get("query") or {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        if not info.get("thumburl"):
            continue
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
        artist = " ".join(artist.splitlines()[0].split()) if artist else ""
        if len(artist) > 50 or re.search(r"description|this (map|file|image)|\.(png|jpe?g|svg)", artist, re.I):
            artist = ""                    # a description pasted into the author field, not a name
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        return {"url": info["thumburl"], "page": info.get("descriptionurl"), "artist": artist, "license": lic}
    return None


def _role(file: str, kind: str) -> str:
    """What a picture file is: a map or a flag (a country's lead picture often is), an
    emblem (as a logo), or a photo of the person or place."""
    if _MAP.search(file):
        return "map"
    if _FLAG.search(file):
        return "flag"
    if _EMBLEM.search(file):
        return "logo"
    return "place" if kind in LOGO_KINDS else kind


def _hit(client: httpx.Client, file: str, role: str, title: str, e: Entity) -> dict | None:
    f = _commons_file(client, file, 1200 if role in GRAPHIC_ROLES else 1600)
    if not f:
        return None
    what = {"logo": f"{title} logo", "flag": f"Flag of {title}", "map": f"Map of {title}"}.get(role)
    lic = f["license"] or "see source"
    credit = f"{what} / Wikimedia Commons" if role in ("logo", "flag") else \
        f"{what or f['artist'] or 'Unknown'}{' — ' + f['artist'] if what and f['artist'] else ''} / Wikimedia Commons, {lic}"
    return {"url": f["url"], "page": f["page"], "origin": "wikidata", "credit": credit[:120],
            "license": "cc0" if re.search(r"public domain|cc0", f["license"], re.I) else "third_party",
            "role": role, "entity": title, "central": e.central}


def lookup(client: httpx.Client, e: Entity) -> list[dict]:
    """The entity's pictures as finder candidates — {url, page, origin, credit, license,
    role, entity} — first the main one: a company's logo (else a photo of it), a
    person's photo, a place's photo; then, for a place, its flag and its locator map.
    [] when Wikipedia has none."""
    try:
        art = _article(client, e.name)
        if not art:
            return []
        title, qid, lead = art
        files: list[tuple[str, str]] = []
        if e.kind in LOGO_KINDS:
            # Wikidata's logo; else the article's lead picture, which for a company is
            # usually its logo in the infobox (Jio Platforms has no P154; its article
            # leads with Reliance_Jio_Logo.svg); else a photo of it (Reliance's logo is non-free).
            logo = _claim_file(client, qid, "P154") or (lead if _is_logo(lead) else "")
            if logo:
                files.append((logo, "logo"))
            elif photo := lead or _claim_file(client, qid, "P18"):
                files.append((photo, _role(photo, e.kind)))
        else:
            if photo := _claim_file(client, qid, "P18") or lead:
                files.append((photo, _role(photo, e.kind)))
            if e.kind == "place":
                for prop, role in (("P41", "flag"), ("P242", "map")):
                    f = _claim_file(client, qid, prop)
                    if f and all(f != x for x, _ in files) and all(r != role for _, r in files):
                        files.append((f, role))
        return [h for f, role in files if (h := _hit(client, f, role, title, e))]
    except Exception as ex:  # noqa: BLE001 - one missing picture is fine
        log.warning("entities: %s: %s", e.name, ex)
        return []


# ── a logo on a clean card, at reel size ──────────────────────────────────────────

W, H = 1080, 1920


def logo_card(raw: bytes, out: Path, box: tuple[float, float] = (0.72, 0.30)) -> Path:
    """The logo (or flag, or map) centred on a light card — a transparent PNG on black
    would vanish — with a soft glow, as a 1080x1920 JPEG. `box`: the most of the
    card's width and height it may fill."""
    from PIL import Image, ImageDraw, ImageFilter, ImageStat

    logo = Image.open(io.BytesIO(raw)).convert("RGBA")
    box_w, box_h = int(W * box[0]), int(H * box[1])
    scale = min(box_w / logo.width, box_h / logo.height)
    logo = logo.resize((max(1, int(logo.width * scale)), max(1, int(logo.height * scale))), Image.LANCZOS)
    # Light logos (white text) need a dark card; everything else sits on near-white.
    solid = logo.getchannel("A").point(lambda a: 255 if a > 200 else 0)
    light = False
    if solid.getbbox():
        r, g, b = ImageStat.Stat(logo.convert("RGB"), mask=solid).mean
        light = 0.299 * r + 0.587 * g + 0.114 * b > 200
    bg = (18, 20, 26) if light else (246, 246, 243)
    card = Image.new("RGB", (W, H), bg)
    # A faint radial glow behind the logo.
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((W * 0.1, H * 0.3, W * 0.9, H * 0.7), fill=40)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    tint = Image.new("RGB", (W, H), (255, 255, 255) if light else (205, 210, 220))
    card = Image.composite(tint, card, glow)
    x, y = (W - logo.width) // 2, (H - logo.height) // 2
    card.paste(logo, (x, y), logo)
    out.parent.mkdir(parents=True, exist_ok=True)
    card.save(out, "JPEG", quality=92)
    return out
