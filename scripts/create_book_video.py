#!/usr/bin/env python3
"""Create a reusable 3D TikTok book video from a title or ISBN."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from build_tiktok_quality_update_pack import (  # noqa: E402
    download_image,
    extract_reference_cover_image,
    select_cover_url,
    trim_plain_border,
)
from fetch_libri_product_pages import PRODUCT_URL, fetch, load_env_file, login  # noqa: E402
from tiktok_libri_pipeline import ProductRecord, parse_libri_detail_html  # noqa: E402
from update_tiktok_quantities_from_libri import TikTokInventoryClient, extract_ean  # noqa: E402


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-")[:70] or "book"


def display_author(value: str) -> str:
    parts = [part.strip() for part in value.split(",", 1)]
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 and all(parts) else value


def score_title(query: str, product: dict[str, Any]) -> float:
    wanted = normalize(query)
    title = normalize(str(product.get("title") or ""))
    if not title:
        return 0.0
    score = difflib.SequenceMatcher(None, wanted, title).ratio()
    if title == wanted:
        score += 2.0
    elif title.startswith(wanted) or wanted.startswith(title):
        score += 1.0
    elif wanted in title:
        score += 0.7
    words = set(wanted.split())
    if words:
        score += len(words.intersection(title.split())) / len(words) * 0.6
    if str(product.get("status") or "").upper() in {"ACTIVATE", "ACTIVE"}:
        score += 0.1
    return score


def ean_from_product(product: dict[str, Any]) -> str:
    for sku in product.get("skus") or []:
        if isinstance(sku, dict):
            ean = extract_ean(sku.get("seller_sku"))
            if ean:
                return ean
    return ""


def resolve_tiktok_product(title: str, env_path: Path, max_pages: int) -> tuple[dict[str, Any], str]:
    env = {**load_env_file(env_path), **os.environ}
    products = TikTokInventoryClient(env, env_path).search_products(page_size=100, max_pages=max_pages)
    ranked = sorted(((score_title(title, product), product) for product in products), key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < 0.85:
        suggestions = ", ".join(str(item[1].get("title") or "") for item in ranked[:5])
        raise RuntimeError(f"No reliable TikTok title match for {title!r}. Closest: {suggestions or 'none'}")
    product = ranked[0][1]
    ean = ean_from_product(product)
    if not ean:
        raise RuntimeError(f"TikTok product {product.get('title')!r} has no LIBRI EAN seller SKU.")
    return product, ean


def find_local_libri_page(ean: str) -> Path | None:
    preferred = [
        WORKSPACE / "libri_product_pages" / f"{ean}.html",
        WORKSPACE / "libri_bulk_pages" / f"{ean}.html",
        WORKSPACE / "outputs" / "reference_lights_out" / f"{ean}.html",
    ]
    for path in preferred:
        if path.exists() and path.stat().st_size:
            return path
    matches = [path for path in (WORKSPACE / "outputs").rglob(f"{ean}.html") if "book_videos" not in path.parts]
    return matches[0] if matches else None


def fetch_libri_page(ean: str, env_path: Path, destination: Path) -> Path:
    opener = login(env_path)
    final_url, body = fetch(opener, PRODUCT_URL.format(ean=ean))
    if "Login.html" in final_url or "<title>Mein.Libri - Login</title>" in body:
        raise RuntimeError("Libri redirected back to login while loading the product.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(body, encoding="utf-8")
    return destination


def load_cover_override(value: str) -> tuple[Image.Image, str]:
    if value.startswith(("http://", "https://")):
        return download_image(value), value
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Cover file not found: {path}")
    image = Image.open(path)
    image.load()
    return image, str(path)


def choose_cover(product: ProductRecord, detail_path: Path, override: str, title: str) -> tuple[Image.Image, str]:
    if override:
        return load_cover_override(override)
    for extension in ("jpg", "jpeg", "png", "webp"):
        cached = WORKSPACE / "book-template" / "assets" / f"{slugify(title)}-front.{extension}"
        if cached.exists():
            image = Image.open(cached)
            image.load()
            return image, f"local high-resolution cover cache: {cached}"
    reference = extract_reference_cover_image(detail_path)
    if reference is not None:
        ratio = reference.width / reference.height if reference.height else 0
        if 0.48 <= ratio <= 0.82:
            return reference, "embedded Libri flat front cover"
    selection = select_cover_url(product.image_urls, reference_image=reference, current_main_image="")
    if selection.url:
        return download_image(selection.url), f"{selection.method}: {selection.url}"
    fallback = selection.reference_image or reference
    if fallback is not None:
        return fallback, "embedded Libri reference cover"
    raise RuntimeError("Libri page contains no usable front-cover image. Use --cover <file-or-url>.")


def save_cover(image: Image.Image, destination: Path) -> tuple[int, int]:
    cleaned = trim_plain_border(ImageOps.exif_transpose(image)).convert("RGB")
    if cleaned.width < 400 or cleaned.height < 600:
        scale = max(400 / cleaned.width, 600 / cleaned.height)
        cleaned = cleaned.resize((round(cleaned.width * scale), round(cleaned.height * scale)), Image.Resampling.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(destination, format="JPEG", quality=96, optimize=True)
    return cleaned.size


def find_ffmpeg() -> Path:
    configured = os.environ.get("FFMPEG_PATH", "")
    if configured and Path(configured).exists():
        return Path(configured)
    executable = shutil.which("ffmpeg")
    if executable:
        return Path(executable)
    try:
        import imageio_ffmpeg

        return Path(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError):
        pass
    temp_tools = Path(os.environ.get("TEMP", "")) / "codex-video-tools"
    candidates = list(temp_tools.rglob("ffmpeg*.exe")) if temp_tools.exists() else []
    if candidates:
        return candidates[0]
    raise RuntimeError("ffmpeg not found. Install Python requirements or set FFMPEG_PATH.")


def find_chrome() -> Path:
    configured = os.environ.get("CHROME_PATH", "")
    candidates = [
        Path(configured) if configured else None,
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise RuntimeError("Google Chrome not found. Set CHROME_PATH.")


def node_module_paths() -> list[Path]:
    paths: list[Path] = []
    local = WORKSPACE / "node_modules"
    if local.exists():
        paths.append(local)
    runtime_root = Path.home() / ".cache" / "codex-runtimes"
    if runtime_root.exists():
        for dependencies in runtime_root.glob("*/dependencies/node"):
            for candidate in [
                dependencies / "node_modules",
                dependencies / "node_modules" / ".pnpm" / "node_modules",
            ]:
                if candidate.exists():
                    paths.append(candidate)
    return list(dict.fromkeys(paths))


def write_preview(project: dict[str, Any], cover_path: Path, slug: str) -> str:
    preview_dir = WORKSPACE / "book-template" / "generated" / slug
    preview_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cover_path, preview_dir / "cover.jpg")
    preview_project = {
        **project,
        "cover_path": "cover.jpg",
        "cover_url": f"./generated/{slug}/cover.jpg",
    }
    (preview_dir / "project.json").write_text(json.dumps(preview_project, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"http://127.0.0.1:4173/generic-video.html?project=./generated/{slug}/project.json"


def render(project_path: Path, output_dir: Path) -> None:
    environment = os.environ.copy()
    paths = node_module_paths()
    existing = environment.get("NODE_PATH", "")
    environment["NODE_PATH"] = os.pathsep.join([*(str(path) for path in paths), *([existing] if existing else [])])
    environment["FFMPEG_PATH"] = str(find_ffmpeg())
    environment["CHROME_PATH"] = str(find_chrome())
    command = [
        shutil.which("node") or "node",
        str(SCRIPT_DIR / "render_book_video.cjs"),
        "--project",
        str(project_path),
        "--output-dir",
        str(output_dir),
    ]
    subprocess.run(command, cwd=WORKSPACE, env=environment, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a 3D TikTok book video from one title.")
    parser.add_argument("title", help="Book title as listed in TikTok Shop")
    parser.add_argument("--isbn", default="", help="Skip TikTok lookup and use this ISBN/EAN")
    parser.add_argument("--cover", default="", help="Optional local cover image or public image URL")
    parser.add_argument("--author", default="")
    parser.add_argument("--hook", default="NEU FÜR DEINE LESELISTE")
    parser.add_argument("--feature", default="JETZT ENTDECKEN")
    parser.add_argument("--label", default="")
    parser.add_argument("--cta", default="TIKTOK SHOP")
    parser.add_argument("--env", type=Path, default=WORKSPACE / ".env")
    parser.add_argument("--output-root", type=Path, default=WORKSPACE / "outputs" / "book_videos")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--refresh-libri", action="store_true")
    parser.add_argument("--no-render", action="store_true", help="Prepare project and browser preview without encoding MP4")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env_path = args.env.expanduser().resolve()
    if args.isbn:
        ean = extract_ean(args.isbn, seller_sku_prefix="")
        if not ean:
            raise RuntimeError("--isbn must be a valid 13-digit ISBN/EAN beginning with 978 or 979.")
        selected_title = args.title
    else:
        tiktok_product, ean = resolve_tiktok_product(args.title, env_path, args.max_pages)
        selected_title = str(tiktok_product.get("title") or args.title)
        print(f"TikTok product: {selected_title}")
    print(f"ISBN/EAN: {ean}")

    slug = f"{slugify(args.title)}-{ean}"
    project_dir = args.output_root.expanduser().resolve() / slug
    source_dir = project_dir / "source"
    detail_path = None if args.refresh_libri else find_local_libri_page(ean)
    if detail_path is None:
        print("Loading current product data from Libri...")
        detail_path = fetch_libri_page(ean, env_path, source_dir / f"{ean}.html")
    else:
        print(f"Libri source: {detail_path}")
    product = parse_libri_detail_html(detail_path)

    cover, cover_source = choose_cover(product, detail_path, args.cover, args.title)
    cover_path = project_dir / "cover.jpg"
    cover_width, cover_height = save_cover(cover, cover_path)
    print(f"Cover source: {cover_source}")

    pages = int(product.pages or 320)
    approximate_mm = pages * 0.055 + 2.0
    project = {
        "title": args.title,
        "author": display_author(args.author or product.author),
        "isbn": ean,
        "label": args.label or product.binding or "BUCHEMPFEHLUNG",
        "hook": args.hook,
        "feature": args.feature,
        "cta_prefix": "JETZT IM",
        "cta": args.cta,
        "pages": pages,
        "cover_ratio": round(cover_width / cover_height, 5),
        "depth_ratio": round(min(0.25, max(0.075, approximate_mm / 210)), 5),
        "duration_seconds": 15,
        "cover_path": "cover.jpg",
        "cover_url": "/cover.jpg",
    }
    project_dir.mkdir(parents=True, exist_ok=True)
    project_path = project_dir / "project.json"
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    preview_url = write_preview(project, cover_path, slug)

    if not args.no_render:
        render(project_path, project_dir / "rendered")
    print(f"Project: {project_path}")
    print(f"Preview: {preview_url}")
    if not args.no_render:
        print(f"Video: {project_dir / 'rendered' / 'book-video.mp4'}")
        print(f"Hero: {project_dir / 'rendered' / 'hero.png'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
