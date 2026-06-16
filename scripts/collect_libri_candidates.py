#!/usr/bin/env python3
"""Collect ranked ISBN candidates from Mein.Libri bestseller/list pages."""

from __future__ import annotations

import argparse
import csv
import html
import math
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_libri_product_pages import fetch, login  # noqa: E402


BASE_URL = "https://mein.libri.de/Bestellen/Bestseller.html"


@dataclass(frozen=True)
class Source:
    label: str
    group: str
    krz: str
    priority: int
    max_pages: int = 3


SOURCES = [
    Source("thalia_proxy_booktok_libri_booktok", "BookTok", "BOOKT", 1, 2),
    Source("thalia_proxy_booktok_new_adult", "BookTok", "BOOKN", 2, 2),
    Source("thalia_proxy_booktok_young_adult", "BookTok", "BOOKY", 3, 2),
    Source("thalia_proxy_booktok_english", "BookTok", "BOOKE", 4, 2),
    Source("libri_bestseller_belletristik_hardcover", "Bestseller", "BELHC", 10, 5),
    Source("libri_bestseller_belletristik_taschenbuch", "Bestseller", "BELTB", 11, 5),
    Source("libri_bestseller_krimi_thriller", "Bestseller", "KRIMI", 12, 5),
    Source("libri_bestseller_scifi_fantasy", "Bestseller", "SCIFI", 13, 5),
    Source("libri_bestseller_kinder_jugendbuch", "Bestseller", "KIBU", 14, 3),
    Source("libri_novitaeten_belletristik_hardcover", "Novitäten", "NOVBH", 20, 4),
    Source("libri_novitaeten_belletristik_taschenbuch", "Novitäten", "NOVBT", 21, 4),
    Source("libri_novitaeten_krimi", "Novitäten", "NOVKR", 22, 4),
    Source("libri_novitaeten_scifi_fantasy", "Novitäten", "NOVSF", 23, 4),
    Source("libri_novitaeten_kinder_jugendbuch", "Novitäten", "NOVKI", 24, 3),
    Source("libri_bestseller_sprachen_woerterbuecher", "Bestseller", "SPRA", 35, 1),
    Source("libri_novitaeten_sprache_woerterbuecher", "Novitäten", "NOVSE", 36, 1),
    Source("libri_bestseller_sachbuch", "Bestseller", "SACH", 40, 1),
    Source("libri_bestseller_ratgeber", "Bestseller", "RATG", 41, 1),
    Source("libri_bestseller_geschichte", "Bestseller", "GEST", 42, 1),
    Source("libri_bestseller_gesundheit", "Bestseller", "GESU", 43, 1),
    Source("libri_bestseller_philosophie", "Bestseller", "PHIL", 44, 1),
    Source("libri_bestseller_wirtschaft", "Bestseller", "WIRT", 45, 1),
    Source("libri_novitaeten_sachbuch", "Novitäten", "NOVSA", 60, 2),
    Source("libri_novitaeten_ratgeber", "Novitäten", "NOVRL", 61, 2),
    Source("libri_novitaeten_geschichte", "Novitäten", "NOVGG", 62, 2),
    Source("libri_novitaeten_gesundheit", "Novitäten", "NOVGS", 63, 2),
    Source("libri_novitaeten_philosophie", "Novitäten", "NOVPH", 64, 2),
    Source("libri_novitaeten_wirtschaft", "Novitäten", "NOVWI", 65, 2),
    Source("libri_bestseller_kochen", "Bestseller", "KOCH", 80, 1),
    Source("libri_bestseller_reise", "Bestseller", "REIS", 81, 1),
    Source("libri_bestseller_erziehung", "Bestseller", "ERZ", 82, 1),
    Source("libri_novitaeten_kochen", "Novitäten", "NOVKO", 90, 2),
    Source("libri_novitaeten_reise", "Novitäten", "NOVRS", 91, 2),
    Source("libri_novitaeten_erziehung", "Novitäten", "NOVKI", 92, 2),
]


def build_url(source: Source, page: int | None = None, page_size: int = 50) -> str:
    params = {
        "group": source.group,
        "krz": source.krz,
        "p": "" if page in (None, 1) else str(page),
        "ps": str(page_size),
    }
    return BASE_URL + "?" + urllib.parse.urlencode(params)


def text_from_html(value: str) -> str:
    value = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_total(decoded_html: str) -> int:
    match = re.search(r'class="total-results">(\d+)', decoded_html)
    return int(match.group(1)) if match else 0


def parse_article_blocks(decoded_html: str, source: Source, page: int, page_size: int) -> list[dict[str, str | int]]:
    blocks = re.findall(r'<div class="article-display">([\s\S]*?)(?=<div class="article-display">|</div>\s*</div>\s*</div>\s*<div class="list-pager"|<p class="search-count")', decoded_html)
    rows: list[dict[str, str | int]] = []
    fallback_eans = list(dict.fromkeys(re.findall(r"/produkt/(\d{10,13})/", decoded_html)))

    if not blocks:
        for idx, ean in enumerate(fallback_eans, start=1):
            rows.append(
                {
                    "ean": ean,
                    "title": "",
                    "author": "",
                    "source": source.label,
                    "source_group": source.group,
                    "source_krz": source.krz,
                    "source_rank": ((page - 1) * page_size) + idx,
                    "source_priority": source.priority,
                }
            )
        return rows

    for idx, block in enumerate(blocks, start=1):
        ean_match = re.search(r"/produkt/(\d{10,13})/", block)
        if not ean_match:
            continue
        title_match = re.search(r'<div class="article-title">\s*<a[^>]*>([\s\S]*?)</a>', block)
        author_match = re.search(r'<div class="article-author">\s*([\s\S]*?)</div>', block)
        price_match = re.search(r'<div class="article-price">\s*([\s\S]*?)</div>', block)
        rows.append(
            {
                "ean": ean_match.group(1),
                "title": text_from_html(title_match.group(1)) if title_match else "",
                "author": text_from_html(author_match.group(1)) if author_match else "",
                "source_price_text": text_from_html(price_match.group(1)) if price_match else "",
                "source": source.label,
                "source_group": source.group,
                "source_krz": source.krz,
                "source_rank": ((page - 1) * page_size) + idx,
                "source_priority": source.priority,
            }
        )
    return rows


def collect(args: argparse.Namespace) -> list[dict[str, str | int]]:
    opener = login(Path(args.env))
    collected: dict[str, dict[str, str | int]] = {}

    for source in SOURCES:
        first_url = build_url(source, page=1, page_size=args.page_size)
        _, first_body = fetch(opener, first_url)
        decoded = html.unescape(first_body)
        total = parse_total(decoded) or args.page_size
        pages = min(source.max_pages, max(1, math.ceil(total / args.page_size)))

        for page in range(1, pages + 1):
            if page == 1:
                page_body = decoded
            else:
                _, body = fetch(opener, build_url(source, page=page, page_size=args.page_size))
                page_body = html.unescape(body)
            for row in parse_article_blocks(page_body, source, page, args.page_size):
                ean = str(row["ean"])
                score = (int(row["source_priority"]) * 10000) + int(row["source_rank"])
                if ean not in collected:
                    row["score"] = score
                    row["sources"] = str(row["source"])
                    collected[ean] = row
                else:
                    existing = collected[ean]
                    existing["sources"] = str(existing["sources"]) + "|" + str(row["source"])
                    if score < int(existing["score"]):
                        for key in ["source", "source_group", "source_krz", "source_rank", "source_priority", "score"]:
                            existing[key] = row[key] if key in row else score
                        if row.get("title"):
                            existing["title"] = row["title"]
                        if row.get("author"):
                            existing["author"] = row["author"]

    rows = sorted(collected.values(), key=lambda item: (int(item["score"]), str(item.get("title", ""))))
    return rows[: args.limit]


def write_csv(path: Path, rows: list[dict[str, str | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ean",
        "title",
        "author",
        "source_price_text",
        "source",
        "sources",
        "source_group",
        "source_krz",
        "source_rank",
        "source_priority",
        "score",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Libri bestseller candidate ISBNs.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--output", default="outputs/research_1000/libri_candidate_1000.csv")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--page-size", type=int, default=50)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = collect(args)
    write_csv(Path(args.output), rows)
    print(f"Collected {len(rows)} unique candidates -> {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
