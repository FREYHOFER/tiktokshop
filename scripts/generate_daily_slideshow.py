#!/usr/bin/env python3
"""Create one auditable, cover-first TikTok Shop photo-post draft per day.

This script deliberately stops at a local, reviewable package.  The generic
TikTok Content Posting API does not accept a TikTok Shop product anchor, so the
native Seller Center/Shop flow must add the product link when the draft is
published.  The output contains the images, copy, source information, and the
state needed for a later metrics/selection loop.

The catalog CSV may use the fields from ``inputs/first5_bestseller_manual.csv``
(``title``, ``author``, ``blurb``, ``stock``, ``price``, ``ean``, ``images``).
An optional ``cover_path`` column is also accepted for offline runs.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import random
import re
import textwrap
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


WORKSPACE = Path(__file__).resolve().parent.parent
CANVAS = (1080, 1920)
DEFAULT_CATALOG = WORKSPACE / "inputs" / "first5_bestseller_manual.csv"
DEFAULT_OUTPUT = WORKSPACE / "outputs" / "daily_slideshows"
DEFAULT_STATE = WORKSPACE / ".automation" / "content_state.json"

def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:90] or "title"


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def read_catalog(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = [dict(row) for row in csv.DictReader(fh)]
    result: list[dict[str, str]] = []
    for row in rows:
        row = {key: clean(value) for key, value in row.items()}
        title = row.get("title") or row.get("product_name")
        images = row.get("images") or row.get("image_urls") or row.get("cover_url")
        stock = as_int(row.get("stock") or row.get("quantity"))
        if not title or not images or (stock is not None and stock <= 0):
            continue
        row["title"] = title
        row["images"] = images
        result.append(row)
    if not result:
        raise ValueError(f"Keine kaufbaren Titel mit Bild in {path} gefunden.")
    return result


def read_reactions(path: Path | None) -> dict[str, list[dict[str, str]]]:
    """Read short, human-approved source excerpts without rewriting them.

    The file is intentionally an input, not an LLM output.  Each row contains
    one exact excerpt, its source label, and its public URL.  Key by EAN first,
    then by normalized title.  A separate source file keeps Reddit/API access
    replaceable and makes every on-screen claim auditable.
    """
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = csv.DictReader(fh)
        result: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            text = clean(row.get("quote") or row.get("text"))
            if not text:
                continue
            key = clean(row.get("ean")) or slugify(clean(row.get("title")))
            if not key:
                continue
            result.setdefault(key, []).append(
                {
                    "text": text,
                    "source_label": clean(row.get("source_label") or "Leserstimme"),
                    "source_url": clean(row.get("source_url")),
                }
            )
        return result


def full_libri_blurb(row: dict[str, str]) -> str:
    """Prefer the complete locally archived Libri detail text over CSV previews."""
    ean = clean(row.get("ean"))
    if ean:
        try:
            from tiktok_libri_pipeline import parse_libri_detail_html
            for directory in (WORKSPACE / "libri_product_pages", WORKSPACE / "libri_bulk_pages"):
                detail = directory / f"{ean}.html"
                if detail.exists():
                    parsed = parse_libri_detail_html(detail)
                    if clean(parsed.blurb):
                        return html.unescape(clean(parsed.blurb))
        except (ImportError, OSError, ValueError):
            pass
    return html.unescape(clean(row.get("blurb")))


def plot_only(blurb: str) -> str:
    """Keep the original plot passage while removing marketing and metadata."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean(blurb)) if part.strip()]
    marketing = (
        "booktok", "endlich auf deutsch", "für fans von", "fuer fans von", "bestseller",
        "gehypte", "sensation", "trifft auf", "leseempfehlung", "triggerwarn",
        "books that make you", "du suchst", "enthaltene tropes", "spice-level",
        "jetzt entdecken", "roman des jahres", "preisgekrönt", "preisgekroent",
    )
    kept: list[str] = []
    started = False
    for sentence in sentences:
        lowered = sentence.casefold()
        is_marketing = any(marker in lowered for marker in marketing)
        if not started and is_marketing:
            continue
        if started and is_marketing:
            break
        started = True
        kept.append(sentence)
    return " ".join(kept).strip() or clean(blurb)


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Zustandsdatei ist nicht lesbar: {path}: {exc}") from exc
    return value if isinstance(value, dict) else fallback


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.ImageFont, width: int) -> list[str]:
    words = clean(value).split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textbbox((0, 0), trial, font=face)[2] <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def palette(seed: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    top = (18 + digest[0] % 24, 20 + digest[1] % 24, 30 + digest[2] % 24)
    bottom = (70 + digest[3] % 45, 32 + digest[4] % 32, 36 + digest[5] % 32)
    return top, bottom


def background(seed: str) -> Image.Image:
    top, bottom = palette(seed)
    image = Image.new("RGB", CANVAS)
    pixels = image.load()
    for y in range(CANVAS[1]):
        ratio = y / max(1, CANVAS[1] - 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        for x in range(CANVAS[0]):
            pixels[x, y] = color
    return image


def load_cover(row: dict[str, str]) -> tuple[Image.Image, str]:
    ean = clean(row.get("ean"))
    # Prefer the embedded Libri detail cover when it is available locally.  A
    # product gallery can contain interior or back-cover images before the
    # actual front cover.
    if ean:
        try:
            from build_tiktok_quality_update_pack import extract_reference_cover_image

            for directory in (WORKSPACE / "libri_product_pages", WORKSPACE / "libri_bulk_pages"):
                detail = directory / f"{ean}.html"
                cover = extract_reference_cover_image(detail)
                if cover is not None:
                    return cover, str(detail.resolve())
        except (ImportError, OSError):
            pass
    local = clean(row.get("cover_path"))
    if local:
        path = Path(local).expanduser()
        if not path.is_absolute():
            path = WORKSPACE / path
        if path.exists():
            with Image.open(path) as source:
                return ImageOps.exif_transpose(source).convert("RGB"), str(path.resolve())
    sources = [clean(value) for value in row.get("images", "").split("|") if clean(value)]
    if not sources:
        raise ValueError(f"{row.get('title', 'Titel')}: keine Bildquelle")
    # Download a small gallery subset and score portrait-shaped candidates.
    # Libri role 1 is the known front-cover path; other providers often put an
    # interior spread first, so aspect ratio is a useful fallback signal.
    from io import BytesIO

    candidates: list[tuple[float, Image.Image, str]] = []
    for url in sources[:10]:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "TikTokShop-Libri-Automation/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read(5_000_000)
            with Image.open(BytesIO(payload)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
            ratio = image.width / image.height if image.height else 0
            role_one = bool(re.search(r"medias\.librinet\.de/dl/[^/]+/1/", url, re.I))
            portrait = 1.0 if 0.50 <= ratio <= 0.90 else 0.0
            score = (100.0 if role_one else 0.0) + (20.0 if portrait else -20.0) - abs(ratio - 0.66) * 10
            candidates.append((score, image, url))
        except Exception:  # noqa: BLE001 - keep trying the remaining gallery images
            continue
    if candidates:
        _score, image, source = max(candidates, key=lambda item: item[0])
        return image, source
    raise ValueError(f"{row.get('title', 'Titel')}: Bildquellen konnten nicht geladen werden")


def fit_cover(image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    image = ImageOps.contain(image, max_size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", max_size, "white")
    canvas.paste(image, ((max_size[0] - image.width) // 2, (max_size[1] - image.height) // 2))
    return canvas


def draw_label(image: Image.Image, text: str, y: int, color: tuple[int, int, int] = (245, 232, 199)) -> int:
    draw = ImageDraw.Draw(image)
    face = font(58, bold=True)
    lines = wrap(draw, text, face, CANVAS[0] - 152)
    for line in lines:
        draw.text((76, y), line, font=face, fill=color)
        y += 72
    return y


def render_slide(
    row: dict[str, str],
    cover: Image.Image,
    index: int,
    title: str,
    cards: list[dict[str, str]],
) -> Image.Image:
    image = background(f"{row.get('ean')}-{index}").convert("RGBA")
    draw = ImageDraw.Draw(image)
    author = clean(row.get("author"))
    blurb = html.unescape(clean(row.get("blurb")))
    group = clean(row.get("product_group"))
    card = cards[index % len(cards)] if cards else {"text": "", "source_label": "", "source_url": ""}
    if index == 0:
        image.alpha_composite(ImageOps.contain(cover, (650, 980), method=Image.Resampling.LANCZOS).convert("RGBA"), (215, 390))
        draw_label(image, card.get("source_label") or "LESESTIMMEN", 120)
        quote_face = font(38)
        quote = f'„{clean(card.get("text"))[:180]}“'
        y_quote = 250
        for line in wrap(draw, quote, quote_face, CANVAS[0] - 152)[:2]:
            draw.text((76, y_quote), line, font=quote_face, fill=(225, 214, 201))
            y_quote += 50
        title_face = font(48, bold=True)
        y = 1430
        for line in wrap(draw, title, title_face, 928):
            draw.text((76, y), line, font=title_face, fill=(255, 250, 242))
            y += 60
        if author:
            draw.text((76, min(y + 20, 1735)), f"von {author}", font=font(34), fill=(225, 214, 201))
    elif index == 1:
        draw_label(image, card.get("source_label") or "KLAPPENTEXT", 170)
        text = card.get("text") or blurb
        face = font(52)
        y = 590
        for line in wrap(draw, text[:360], face, 900):
            draw.text((76, y), line, font=face, fill=(255, 250, 242))
            y += 68
        image.alpha_composite(ImageOps.contain(cover, (340, 500), method=Image.Resampling.LANCZOS).convert("RGBA"), (670, 1170))
    elif index == 2:
        draw_label(image, card.get("source_label") or "BUCHDATEN", 170)
        mood = group.split("/")[-1] if group else "Belletristik"
        badge = (76, 590, 1004, 760)
        draw.rounded_rectangle(badge, radius=32, fill=(246, 232, 199, 235))
        draw.text((120, 635), mood[:42], font=font(54, bold=True), fill=(34, 25, 24))
        image.alpha_composite(ImageOps.contain(cover, (360, 550), method=Image.Resampling.LANCZOS).convert("RGBA"), (360, 950))
    elif index == 3:
        draw_label(image, card.get("source_label") or "AUTOR & AUSGABE", 170)
        if author:
            draw.text((76, 620), author, font=font(64, bold=True), fill=(255, 250, 242))
        details = []
        if clean(row.get("binding")):
            details.append(clean(row["binding"]))
        if clean(row.get("pages")):
            details.append(f"{row['pages']} Seiten")
        if details:
            draw.text((76, 745), " · ".join(details), font=font(38), fill=(225, 214, 201))
        image.alpha_composite(ImageOps.contain(cover, (430, 650), method=Image.Resampling.LANCZOS).convert("RGBA"), (570, 990))
    else:
        draw_label(image, "DEINE MEINUNG?", 170)
        title_face = font(62, bold=True)
        y = 620
        for line in wrap(draw, title, title_face, 900):
            draw.text((76, y), line, font=title_face, fill=(255, 250, 242))
            y += 78
        price = as_float(row.get("price"))
        price_text = f"{price:.2f} € im TikTok Shop" if price is not None else "Im TikTok Shop erhältlich"
        draw.text((76, 950), price_text, font=font(44, bold=True), fill=(246, 232, 199))
        image.alpha_composite(ImageOps.contain(cover, (400, 590), method=Image.Resampling.LANCZOS).convert("RGBA"), (340, 1160))
    # Keep the product anchor native; do not burn URLs, QR codes, or watermarks into the image.
    return image.convert("RGB")


def choose_row(
    rows: list[dict[str, str]], state: dict[str, Any], today: str, rng: random.Random, preferred_ean: str = ""
) -> tuple[dict[str, str], str]:
    posts = state.setdefault("posts", {})
    recent_eans = {
        str(entry.get("ean"))
        for entry in posts.values()
        if isinstance(entry, dict) and entry.get("status") in {"draft", "posted"}
        and str(entry.get("date", "")) >= (dt.date.fromisoformat(today) - dt.timedelta(days=13)).isoformat()
    }
    preferred = next((row for row in rows if preferred_ean and clean(row.get("ean")) == preferred_ean), None)
    candidates = [row for row in rows if clean(row.get("ean")) not in recent_eans] or rows
    if preferred is not None:
        candidates = [preferred]
    metrics = state.get("metrics", {})

    def score(row: dict[str, str]) -> float:
        rank = as_float(row.get("rank"), 999.0) or 999.0
        ean = clean(row.get("ean"))
        metric = metrics.get(ean, {}) if isinstance(metrics, dict) else {}
        learned = as_float(metric.get("learning_score"), 0.0) if isinstance(metric, dict) else 0.0
        # Rank provides a deterministic cold-start signal; learned data is a small bonus.
        return 1.0 / (1.0 + rank) + max(-0.25, min(0.75, learned or 0.0)) + rng.random() * 0.03

    row = max(candidates, key=score)
    return row, "source_backed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Erzeugt eine tägliche Cover-first TikTok-Foto-Slideshow.")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="Lokales Shop-Datum YYYY-MM-DD")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--slides", type=int, default=5)
    parser.add_argument("--ean", default="", help="Optional: bestimmten Katalogtitel per EAN wählen")
    parser.add_argument("--force", action="store_true", help="Vorhandenen Entwurf für das Datum ersetzen")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        raise SystemExit("--date muss YYYY-MM-DD sein.")
    if args.slides < 2 or args.slides > 8:
        raise SystemExit("--slides muss zwischen 2 und 8 liegen.")

    state = load_json(args.state, {"posts": {}, "metrics": {}, "hook_variants": {}})
    existing = state.setdefault("posts", {}).get(args.date)
    if existing and not args.force:
        print(f"Entwurf existiert bereits: {existing.get('manifest', '')}")
        return 0
    rows = read_catalog(args.catalog)
    rng = random.Random(args.seed if args.seed is not None else args.date)
    preferred_ean = clean(args.ean) or (clean(existing.get("ean")) if isinstance(existing, dict) and args.force else "")
    row, _mode = choose_row(rows, state, args.date, rng, preferred_ean=preferred_ean)
    title = clean(row.get("title"))
    source_blurb = full_libri_blurb(row)
    blurb = plot_only(source_blurb)
    # Strictly source-only mode: every spoken/on-screen claim comes directly
    # from the Libri blurb. No generated hooks, paraphrases or reader quotes.
    cards = [{"text": part.strip(), "source_label": "LIBRI-KLAPPENTEXT", "source_url": ""} for part in re.split(r"(?<=[.!?])\s+", blurb)[:2] if part.strip()]
    if not cards:
        cards = [{"text": title, "source_label": "TITEL", "source_url": ""}]
    cover, cover_source = load_cover(row)
    identity = clean(row.get("ean")) or slugify(title)
    output_dir = args.output_root / f"{args.date}_{slugify(title)}_{identity}"
    output_dir.mkdir(parents=True, exist_ok=True)
    photos: list[str] = []
    for index in range(args.slides):
        path = output_dir / f"slide_{index + 1:02d}.jpg"
        render_slide(row, cover, index, title, cards).save(path, quality=94, optimize=True)
        photos.append(str(path.resolve()))
    description = f"{title} – jetzt im TikTok Shop entdecken. #booktok #buchempfehlung"
    manifest = {
        "date": args.date,
        "status": "draft",
        "title": title,
        "ean": clean(row.get("ean")),
        "seller_sku": f"LIBRI-{clean(row.get('ean'))}" if clean(row.get("ean")) else "",
        "author": clean(row.get("author")),
        "source_blurb": source_blurb,
        "spoken_text": blurb,
        "content_mode": "libri_blurb_only",
        "source_cards": cards,
        "description": description,
        "photo_cover_index": 0,
        "photos": photos,
        "cover_source": cover_source,
        "gallery_sources": [clean(value) for value in row.get("images", "").split("|") if clean(value)],
        "product_anchor_required": True,
        "product_anchor_note": "Native TikTok Shop anchor must be added by Seller Center/approved Shop flow.",
        "features": {"slide_count": args.slides, "cover_first": True, "generated_copy": False},
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    state["posts"][args.date] = {**manifest, "manifest": str(manifest_path.resolve())}
    save_json(args.state, state)
    print(f"Slideshow: {manifest_path.resolve()}")
    print(f"Titel: {title} | EAN: {clean(row.get('ean')) or 'unbekannt'} | Quellenkarten: {len(cards)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
