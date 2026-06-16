#!/usr/bin/env python3
"""Create photo and video worklists for TikTok book listings."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tiktok_libri_pipeline import parse_libri_detail_html  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def product_for_ean(detail_dir: Path, ean: str):
    detail_path = detail_dir / f"{ean}.html"
    if not detail_path.exists():
        return None
    return parse_libri_detail_html(detail_path)


def build_worklists(args: argparse.Namespace) -> int:
    plan_rows = read_csv(Path(args.plan))
    detail_dir = Path(args.detail_dir)

    photo_rows = []
    video_rows = []
    for row in plan_rows:
        ean = row.get("ean", "")
        product = product_for_ean(detail_dir, ean)
        title = (product.title if product else "") or row.get("current_product_name", "")
        author = product.author if product else ""
        pages = f"{product.pages} Seiten" if product and product.pages else ""
        binding = product.binding if product else ""
        release_date = product.release_date if product else ""
        current_count = int(row.get("current_image_count") or 0)
        available_count = int(row.get("available_public_image_count") or 0)
        missing_to_five = max(0, 5 - current_count)

        if row.get("needs_real_extra_photos") == "yes":
            photo_rows.append(
                {
                    "seller_sku": row.get("seller_sku", ""),
                    "ean": ean,
                    "product_name": row.get("suggested_product_name") or row.get("current_product_name", ""),
                    "current_image_count": current_count,
                    "available_public_image_count": available_count,
                    "missing_images_to_5": missing_to_five,
                    "photo_1": "Frontcover frontal auf reinweissem Hintergrund",
                    "photo_2": "Frontcover leicht schraeg mit Buchdicke sichtbar",
                    "photo_3": "Buchruecken frontal",
                    "photo_4": "Rueckseite nur nach QR-/Barcode-Pruefung; sonst Seitenkante",
                    "photo_5": "Aufgeschlagene Seiten oder Papier-/Formatdetail",
                    "note": "Keine Overlays, keine Rahmen, keine Shopnamen, kein externer Link im Bild.",
                }
            )

        cover_ready = row.get("generated_main_image_local") or row.get("selected_cover_url")
        video_status = "ready_from_cover" if cover_ready and row.get("cover_selection_method") != "no_safe_front_cover" else "needs_front_photo_first"
        facts = " | ".join(value for value in [binding, pages, release_date] if value)
        video_rows.append(
            {
                "seller_sku": row.get("seller_sku", ""),
                "ean": ean,
                "product_name": row.get("suggested_product_name") or row.get("current_product_name", ""),
                "video_status": video_status,
                "duration_seconds": "7",
                "format": "1080x1920 MP4, under 5MB",
                "scene_1": f"Cover ruhig einblenden: {title}",
                "scene_2": f"Autor zeigen: {author}" if author else "Autor aus Listingdaten zeigen",
                "scene_3": f"Bibliografische Fakten: {facts}" if facts else "Bibliografische Fakten aus Listingdaten",
                "scene_4": "Kurzer Klappentext-Auszug ohne Bestseller- oder Shop-Claim",
                "compliance_note": "Kein externer Link, keine Preiswerbung, keine subjektiven Bestseller-Zusätze.",
            }
        )

    output_dir = Path(args.output_dir)
    write_csv(
        output_dir / "extra_photo_shot_list.csv",
        photo_rows,
        [
            "seller_sku",
            "ean",
            "product_name",
            "current_image_count",
            "available_public_image_count",
            "missing_images_to_5",
            "photo_1",
            "photo_2",
            "photo_3",
            "photo_4",
            "photo_5",
            "note",
        ],
    )
    write_csv(
        output_dir / "video_storyboard.csv",
        video_rows,
        [
            "seller_sku",
            "ean",
            "product_name",
            "video_status",
            "duration_seconds",
            "format",
            "scene_1",
            "scene_2",
            "scene_3",
            "scene_4",
            "compliance_note",
        ],
    )
    print(f"Photo rows: {len(photo_rows)}")
    print(f"Video rows: {len(video_rows)}")
    print(f"Output: {output_dir.resolve()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build TikTok extra photo and video worklists.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--detail-dir", default="libri_bulk_pages")
    parser.add_argument("--output-dir", required=True)
    return build_worklists(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
