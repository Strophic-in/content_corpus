"""Preview pictures of every caption style and thumbnail style, for Settings → Styles
(apps/web/public/styles/). No model calls, no GPU:

    python -m corpus.style_previews ../apps/web/public/styles
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .config import settings
from .media import assemble

LINE = "A historic spire collapsed in flames tonight"


def backdrop(path: Path, size=(1080, 1920), seed: int = 0) -> Path:
    """A stand-in photo: a dusk sky, a building with a spire, warm windows."""
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(40 + 120 * t), int(50 + 40 * t), int(110 - 60 * t)))
    d.rectangle((w * 0.18, h * 0.42, w * 0.82, h), fill=(52, 44, 48))
    d.polygon([(w * 0.46, h * 0.42), (w * 0.54, h * 0.42), (w * 0.5, h * 0.2)], fill=(40, 34, 40))
    for r in range(4):
        for c in range(5):
            x, y = w * (0.24 + c * 0.11), h * (0.5 + r * 0.1)
            d.rectangle((x, y, x + w * 0.05, y + h * 0.04), fill=(255, 190, 90) if (r + c + seed) % 3 else (90, 70, 60))
    img.filter(ImageFilter.GaussianBlur(1.2)).save(path)
    return path


def caption_preview(style_file: Path, out: Path, work: Path) -> Path:
    spec = json.loads(style_file.read_text(encoding="utf-8"))
    style = assemble.CaptionStyle(**spec["style"])
    words, t = [], 0.0
    for w in LINE.split():
        words.append((t, t + 0.35, w.upper() if style.uppercase else w))
        t += 0.35
    doc = assemble.captions_ass(words, set(), style)
    (work / "c.ass").write_text(doc, encoding="utf-8")
    if not (work / "fonts").exists():
        shutil.copytree(assemble.FONTS_DIR, work / "fonts")
    bg = backdrop(work / "bg.png")
    # 0.5 s in: the second word is being said (its highlight shows).
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", "1", "-i", bg.name, "-vf",
                    "ass=c.ass:fontsdir=fonts", "-ss", "0.5", "-frames:v", "1", "-update", "1", "tmp.png"],
                   cwd=work, check=True)
    Image.open(work / "tmp.png").convert("RGB").resize((540, 960)).save(out, "JPEG", quality=82)
    return out


def main(dest: str) -> None:
    root = Path(dest)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for f in sorted((settings().prompts_dir / "caption_styles").glob("*.json")):
            caption_preview(f, root / f"caption-{f.stem}.jpg", work)
            print("caption", f.stem)
        from .media import thumbnail
        for f in sorted((settings().prompts_dir / "thumb_styles").glob("*.json")):
            spec = json.loads(f.read_text(encoding="utf-8"))
            pic, before = backdrop(work / "p.png", (1600, 1000), 1), backdrop(work / "b.png", (1600, 1000), 2)
            thumbnail.render(work / "t.jpg", line=spec.get("sample", "Spire gone in minutes"), kicker="Breaking",
                             picture=pic, before=before if f.stem == "before_now" else None, brand="Trendcaster",
                             style=f.stem)
            Image.open(work / "t.jpg").resize((540, 960)).save(root / f"thumb-{f.stem}.jpg", "JPEG", quality=82)
            print("thumb", f.stem)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "previews")
