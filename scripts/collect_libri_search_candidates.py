#!/usr/bin/env python3
"""Collect ranked ISBN candidates from Mein.Libri search commodity groups.

These rows are intended as a fallback after explicit bestseller and BookTok
lists. Scores start after the curated list scores so bestseller candidates keep
priority when the CSVs are merged.
"""

from __future__ import annotations

import argparse
import csv
import html
import math
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from collect_libri_candidates import Source, parse_article_blocks, parse_total
from fetch_libri_product_pages import fetch, login


BASE_URL = "https://mein.libri.de/Bestellen/Suchen.html"


@dataclass(frozen=True)
class SearchSource:
    label: str
    commodity_group: str
    priority: int
    max_pages: int = 8


SOURCES = [
    SearchSource("libri_search_hc_romane_erzaehlungen", "11110", 100, 20),
    SearchSource("libri_search_tb_romane_erzaehlungen", "21110", 101, 20),
    SearchSource("libri_search_hc_kriminalromane", "11200", 102, 20),
    SearchSource("libri_search_tb_kriminalromane", "21200", 103, 20),
    SearchSource("libri_search_hc_scifi_fantasy", "11300", 104, 20),
    SearchSource("libri_search_tb_scifi_fantasy", "21300", 105, 20),
    SearchSource("libri_search_hc_jugendromane", "12500", 106, 20),
    SearchSource("libri_search_tb_jugendromane", "22500", 107, 20),
]


def build_url(source: SearchSource, page: int, page_size: int, sort_by: str) -> str:
    params = {
        "searchInitiated": "1",
        "commodityGroup": source.commodity_group,
        "ps": str(page_size),
        "p": str(page),
    }
    if sort_by:
        params["sort_by"] = sort_by
    return BASE_URL + "?" + urllib.parse.urlencode(params)


def collect(args: argparse.Namespace) -> list[dict[str, str | int]]:
    opener = login(Path(args.env))
    collected: dict[str, dict[str, str | int]] = {}

    for search_source in SOURCES:
        source = Source(
            search_source.label,
            "Search",
            search_source.commodity_group,
            search_source.priority,
            search_source.max_pages,
        )
        first_url = build_url(search_source, page=1, page_size=args.page_size, sort_by=args.sort_by)
        _, first_body = fetch(opener, first_url)
        decoded = html.unescape(first_body)
        total = parse_total(decoded) or args.page_size
        pages = min(search_source.max_pages, max(1, math.ceil(total / args.page_size)))

        for page in range(1, pages + 1):
            if page == 1:
                page_body = decoded
            else:
                _, body = fetch(opener, build_url(search_source, page=page, page_size=args.page_size, sort_by=args.sort_by))
                page_body = html.unescape(body)

            for row in parse_article_blocks(page_body, source, page, args.page_size):
                ean = str(row["ean"])
                score = (search_source.priority * 10000) + int(row["source_rank"])
                if ean not in collected:
                    row["score"] = score
                    row["sources"] = search_source.label
                    row["source"] = search_source.label
                    row["source_group"] = "Search"
                    row["source_krz"] = search_source.commodity_group
                    row["source_priority"] = search_source.priority
                    collected[ean] = row
                else:
                    existing = collected[ean]
                    existing["sources"] = str(existing["sources"]) + "|" + search_source.label
                    if score < int(existing["score"]):
                        for key in ["source", "source_group", "source_krz", "source_rank", "source_priority", "score"]:
                            existing[key] = row.get(key, score)

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
    parser = argparse.ArgumentParser(description="Collect Libri search fallback candidates.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--output", default="outputs/research_next_400/libri_candidate_search_fallback.csv")
    parser.add_argument("--limit", type=int, default=3000)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--sort-by", default="Rel")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = collect(args)
    write_csv(Path(args.output), rows)
    print(f"Collected {len(rows)} unique search fallback candidates -> {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
