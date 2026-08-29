#!/usr/bin/env python3
"""Create simple 3D-style book marketing renders from Libri product pages."""

from __future__ import annotations

import argparse
import base64
import html
import math
import re
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


DEFAULT_HTML_DIRS = ["libri_product_pages", "libri_bulk_pages"]
CANVAS_SIZE = (1080, 1920)
GIF_SIZE = (540, 960)


@dataclass
class CoverSource:
    kind: str
    value: str


def clean(value: object) -> str:
    return str(value or "").strip()


def extract_cover_sources(html_text: str) -> list[CoverSource]:
    sources: list[CoverSource] = []
    for match in re.finditer(r"https?&#x3A;.*?PJFONS78FHL", html_text):
        url = html.unescape(match.group(0))
        if "medias.librinet.de" in url:
            sources.append(CoverSource("url", url))
    for match in re.finditer(r"data:image/[^;]+;base64,([^\"']+)", html_text):
        sources.append(CoverSource("base64", match.group(1)))
    return sources


def load_cover(ean: str, html_dirs: list[str]) -> Image.Image:
    page = None
    for raw_dir in html_dirs:
        candidate = Path(raw_dir) / f"{ean}.html"
        if candidate.exists():
            page = candidate
            break
    if page is None:
        raise SystemExit(f"No Libri HTML page found for EAN {ean}.")

    html_text = page.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    candidates: list[tuple[float, Image.Image]] = []
    for source in extract_cover_sources(html_text):
        try:
            if source.kind == "url":
                with urllib.request.urlopen(source.value, timeout=20) as response:
                    payload = response.read()
            else:
                payload = base64.b64decode(source.value)
            image = Image.open(BytesIO(payload)).convert("RGB")
            if image.width >= 100 and image.height >= 150:
                ratio = image.width / image.height
                portrait_score = abs(ratio - 0.66)
                size_bonus = min(image.width * image.height / 400000, 1.0)
                source_bonus = 0.12 if source.kind == "base64" else 0.0
                candidates.append((portrait_score - size_bonus * 0.08 - source_bonus, image))
        except Exception as exc:
            errors.append(str(exc))
            continue
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]
    joined = "; ".join(errors[:3])
    raise SystemExit(f"Could not load a usable cover for EAN {ean}. {joined}")


def load_cover_url(url: str) -> Image.Image:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read()
    return Image.open(BytesIO(payload)).convert("RGB")


def fit_cover(image: Image.Image, target_ratio: float = 0.68) -> Image.Image:
    width, height = image.size
    ratio = width / height
    if ratio > target_ratio:
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        image = image.crop((left, 0, left + new_width, height))
    elif ratio < target_ratio:
        new_height = int(width / target_ratio)
        top = max((height - new_height) // 2, 0)
        image = image.crop((0, top, width, min(top + new_height, height)))
    return image


def perspective_coefficients(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> list[float]:
    matrix = []
    vector = []
    for (x, y), (u, v) in zip(dst, src):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        vector.append(u)
        vector.append(v)
    return np.linalg.solve(np.array(matrix), np.array(vector)).tolist()


def warp_to_quad(image: Image.Image, size: tuple[int, int], quad: list[tuple[float, float]]) -> Image.Image:
    src = [(0, 0), (image.width, 0), (image.width, image.height), (0, image.height)]
    coeffs = perspective_coefficients(src, quad)
    return image.transform(size, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)


def gradient_background(size: tuple[int, int], mood: str) -> Image.Image:
    width, height = size
    top = (20, 22, 28)
    bottom = (68, 25, 31) if mood == "thriller" else (28, 44, 60)
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        for x in range(width):
            vignette = 1 - 0.28 * math.hypot((x / width) - 0.5, (y / height) - 0.45)
            color = tuple(int((top[i] * (1 - t) + bottom[i] * t) * vignette) for i in range(3))
            pixels[x, y] = color
    return image


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font_obj: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = clean(f"{current} {word}")
        bbox = draw.textbbox((0, 0), trial, font=font_obj)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text_block(image: Image.Image, hook: str, title: str, shop_line: str) -> None:
    draw = ImageDraw.Draw(image)
    margin = 76
    hook_font = font(58, bold=True)
    title_font = font(34, bold=False)
    shop_font = font(30, bold=True)

    y = 114
    for line in wrap_text(draw, hook, hook_font, image.width - margin * 2):
        draw.text((margin, y), line, font=hook_font, fill=(250, 248, 241))
        y += 70

    y += 28
    for line in wrap_text(draw, title, title_font, image.width - margin * 2):
        draw.text((margin, y), line, font=title_font, fill=(221, 209, 193))
        y += 44

    pill = (margin, image.height - 160, margin + 355, image.height - 94)
    draw.rounded_rectangle(pill, radius=28, fill=(246, 232, 199))
    draw.text((pill[0] + 30, pill[1] + 16), shop_line, font=shop_font, fill=(31, 24, 22))


def render_book(
    cover: Image.Image,
    output_size: tuple[int, int],
    hook: str,
    title: str,
    shop_line: str,
    mood: str,
    angle: float = 0.0,
    scale: float = 1.0,
) -> Image.Image:
    canvas = gradient_background(output_size, mood).convert("RGBA")
    width, height = output_size
    cover = fit_cover(cover).resize((620, 912), Image.Resampling.LANCZOS)

    book_w = 520 * scale
    book_h = 765 * scale
    cx = width * (0.50 + 0.05 * math.sin(angle))
    cy = height * 0.57
    skew = 70 * math.cos(angle) * scale
    lean = 42 * math.sin(angle) * scale
    depth = 78 * scale

    tl = (cx - book_w / 2 + lean, cy - book_h / 2)
    tr = (cx + book_w / 2 + skew + lean, cy - book_h / 2 + 34 * scale)
    br = (cx + book_w / 2 - skew * 0.15 + lean, cy + book_h / 2 + 42 * scale)
    bl = (cx - book_w / 2 + lean, cy + book_h / 2)
    quad = [tl, tr, br, bl]

    shadow = Image.new("RGBA", output_size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse(
        (
            int(cx - book_w * 0.70),
            int(cy + book_h * 0.43),
            int(cx + book_w * 0.82),
            int(cy + book_h * 0.65),
        ),
        fill=(0, 0, 0, 126),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(34 * scale)))
    canvas.alpha_composite(shadow)

    side = Image.new("RGBA", output_size, (0, 0, 0, 0))
    side_draw = ImageDraw.Draw(side)
    spine = [
        (tl[0] - depth, tl[1] + 26 * scale),
        tl,
        bl,
        (bl[0] - depth, bl[1] - 28 * scale),
    ]
    pages = [
        tr,
        (tr[0] + depth * 0.55, tr[1] + 24 * scale),
        (br[0] + depth * 0.55, br[1] - 18 * scale),
        br,
    ]
    side_draw.polygon(spine, fill=(28, 21, 24, 255))
    side_draw.polygon(pages, fill=(226, 218, 202, 255))
    for offset in range(8, int(depth * 0.5), 8):
        side_draw.line(
            [(tr[0] + offset, tr[1] + 25 * scale), (br[0] + offset, br[1] - 20 * scale)],
            fill=(178, 167, 151, 90),
            width=max(1, int(2 * scale)),
        )
    canvas.alpha_composite(side)

    warped = warp_to_quad(cover.convert("RGBA"), output_size, quad)
    canvas.alpha_composite(warped)

    gloss = Image.new("RGBA", output_size, (0, 0, 0, 0))
    gloss_draw = ImageDraw.Draw(gloss)
    gloss_draw.polygon(
        [
            (tl[0] + book_w * 0.16, tl[1] + 12 * scale),
            (tl[0] + book_w * 0.35, tl[1] + 28 * scale),
            (bl[0] + book_w * 0.18, bl[1] - 10 * scale),
            (bl[0] + book_w * 0.03, bl[1] - 18 * scale),
        ],
        fill=(255, 255, 255, 33),
    )
    canvas.alpha_composite(gloss.filter(ImageFilter.GaussianBlur(max(1, int(1.5 * scale)))))

    draw_text_block(canvas, hook, title, shop_line)
    return canvas.convert("RGB")


def save_gif(cover: Image.Image, output: Path, hook: str, title: str, shop_line: str, mood: str) -> None:
    frames = []
    for idx in range(32):
        t = idx / 31
        angle = -0.72 + 0.72 * math.sin(t * math.pi / 2)
        scale = 0.89 + 0.11 * t
        frame = render_book(cover, GIF_SIZE, hook, title, shop_line, mood, angle=angle, scale=scale)
        frames.append(frame)
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=72, loop=0, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a TikTok-ready 3D-style book marketing image.")
    parser.add_argument("--ean", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--hook", required=True)
    parser.add_argument("--shop-line", default="Im TikTok Shop")
    parser.add_argument("--mood", default="thriller")
    parser.add_argument("--html-dir", action="append", default=DEFAULT_HTML_DIRS)
    parser.add_argument("--cover-url", default="", help="Optional direct cover image URL.")
    parser.add_argument("--output-dir", default="outputs/renders/book_marketing")
    parser.add_argument("--name", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or args.ean

    cover = load_cover_url(args.cover_url) if args.cover_url else load_cover(args.ean, args.html_dir)
    static_path = output_dir / f"{name}_hero.png"
    gif_path = output_dir / f"{name}_reveal.gif"

    image = render_book(cover, CANVAS_SIZE, args.hook, args.title, args.shop_line, args.mood)
    image.save(static_path, quality=94)
    save_gif(cover, gif_path, args.hook, args.title, args.shop_line, args.mood)

    print(f"Static render: {static_path.resolve()}")
    print(f"Reveal GIF: {gif_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
