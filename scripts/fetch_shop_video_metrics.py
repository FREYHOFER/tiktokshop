#!/usr/bin/env python3
"""Fetch T-1 shoppable-video metrics for the daily content feedback loop.

TikTok Shop exposes video performance through the seller Analytics API.  This
is read-only and intentionally separate from publishing: the seller token can
read metrics, while the native Seller Center remains responsible for product
anchors and Auto-post in the German beta.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tiktok_order_automation import TikTokApiError, TikTokShopClient  # noqa: E402
from fetch_libri_product_pages import load_env_file  # noqa: E402


WORKSPACE = Path(__file__).resolve().parent.parent
ENDPOINT = "/analytics/202605/shop_videos/performance"
FIELDS = [
    "video_id",
    "title",
    "username",
    "video_post_time",
    "views",
    "click_through_rate",
    "product_clicks",
    "items_sold",
    "sku_orders",
    "gmv_amount",
    "gmv_currency",
    "raw_json",
]
DEFAULT_STATE = WORKSPACE / ".automation" / "content_state.json"


def clean(value: Any) -> str:
    return str(value or "").strip()


def nested(value: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = value
        valid = True
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                valid = False
                break
            current = current[part]
        if valid and current not in (None, ""):
            return current
    return ""


def metric_row(video: dict[str, Any]) -> dict[str, str]:
    gmv = nested(video, "gmv", "gross_merchandise_value", "performance.gmv")
    return {
        "video_id": clean(video.get("id") or video.get("video_id")),
        "title": clean(video.get("title") or video.get("video_description")),
        "username": clean(video.get("username") or nested(video, "creator.user_name", "creator.nick_name")),
        "video_post_time": clean(video.get("video_post_time") or video.get("post_time")),
        "views": clean(nested(video, "views", "view_count", "performance.views")),
        "click_through_rate": clean(nested(video, "click_through_rate", "ctr", "performance.click_through_rate")),
        "product_clicks": clean(nested(video, "product_clicks", "performance.product_clicks")),
        "items_sold": clean(nested(video, "items_sold", "performance.items_sold")),
        "sku_orders": clean(nested(video, "sku_orders", "orders", "performance.sku_orders")),
        "gmv_amount": clean(gmv.get("amount") if isinstance(gmv, dict) else gmv),
        "gmv_currency": clean(gmv.get("currency") if isinstance(gmv, dict) else ""),
        "raw_json": json.dumps(video, ensure_ascii=False, separators=(",", ":")),
    }


def number(value: str) -> float:
    value = clean(value).replace("%", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return 0.0


def update_state(state_path: Path, metric_rows: list[dict[str, str]], metric_date: str) -> int:
    """Attach rows to generated posts when a video id or title is known.

    A Shop Analytics response has no ISBN/EAN.  Matching therefore prefers a
    manually recorded ``video_id`` and falls back to the post title.  Unmatched
    rows remain in the CSV for later mapping instead of being guessed.
    """
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"posts": {}, "metrics": {}}
    posts = state.setdefault("posts", {})
    matched = 0
    for row in metric_rows:
        row_id = clean(row.get("video_id"))
        row_title = clean(row.get("title")).casefold()
        target = None
        for post in posts.values():
            if not isinstance(post, dict):
                continue
            if row_id and row_id == clean(post.get("video_id")):
                target = post
                break
            if row_title and row_title == clean(post.get("title")).casefold():
                target = post
        if target is None:
            continue
        metrics = {key: value for key, value in row.items() if key not in {"raw_json"}}
        views = number(row.get("views", ""))
        ctr = number(row.get("click_through_rate", ""))
        if "%" not in row.get("click_through_rate", "") and ctr:
            ctr *= 100
        gmv = number(row.get("gmv_amount", ""))
        metrics["metric_date"] = metric_date
        metrics["learning_score"] = round(min(1.0, views / 10000) * 0.1 + min(1.0, ctr / 10) * 0.3 + min(1.0, gmv / 100) * 0.6, 4)
        target["metrics"] = metrics
        if clean(target.get("ean")):
            state.setdefault("metrics", {})[clean(target["ean"])] = metrics
        hook = clean(target.get("hook"))
        if hook:
            state.setdefault("hook_variants", {}).setdefault(hook, {})["learning_score"] = metrics["learning_score"]
        matched += 1
    temporary = state_path.with_suffix(state_path.suffix + ".tmp")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(state_path)
    return matched


def fetch(client: TikTokShopClient, start_date: str, end_date: str, page_size: int) -> list[dict[str, Any]]:
    shop_cipher = client.ensure_shop_cipher()
    rows: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params: dict[str, object] = {
            "shop_cipher": shop_cipher,
            "start_date_ge": start_date,
            "end_date_lt": end_date,
            "page_size": page_size,
            "sort_field": "gmv",
            "sort_order": "DESC",
            "currency": "LOCAL",
            "account_type": "ALL",
        }
        if page_token:
            params["page_token"] = page_token
        response = client.request("GET", ENDPOINT, params=params)
        data = response.get("data") or {}
        rows.extend(data.get("videos") or data.get("video_list") or [])
        page_token = clean(data.get("next_page_token") or data.get("page_token"))
        if not page_token:
            break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Importiert TikTok-Shop-Video-Metriken (T-1) als CSV.")
    parser.add_argument("--date", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    parser.add_argument("--end-date", default=dt.date.today().isoformat(), help="Exklusives Ende YYYY-MM-DD")
    parser.add_argument("--env", type=Path, default=WORKSPACE / ".env")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="Content-State für gematchte Posts")
    parser.add_argument("--no-state-update", action="store_true")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true", help="Endpoint und Parameter prüfen, keine API-Anfrage")
    args = parser.parse_args()
    if args.page_size < 1 or args.page_size > 100:
        raise SystemExit("--page-size muss zwischen 1 und 100 liegen.")
    if dt.date.fromisoformat(args.end_date) <= dt.date.fromisoformat(args.date):
        raise SystemExit("--end-date muss nach --date liegen.")

    params = {
        "start_date_ge": args.date,
        "end_date_lt": args.end_date,
        "page_size": args.page_size,
        "sort_field": "gmv",
        "sort_order": "DESC",
        "currency": "LOCAL",
        "account_type": "ALL",
    }
    if args.dry_run:
        print(json.dumps({"endpoint": ENDPOINT, "params": params}, ensure_ascii=False, indent=2))
        return 0

    env = {**load_env_file(args.env), **os.environ}
    client = TikTokShopClient(env, args.env)
    client.version = "202605"
    videos = fetch(client, args.date, args.end_date, args.page_size)
    output = args.output or WORKSPACE / "outputs" / "metrics" / f"shop_video_metrics_{args.date}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = [metric_row(video) for video in videos]
    with output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    matched = 0 if args.no_state_update else update_state(args.state, rows, args.date)
    print(f"Metriken: {output.resolve()} ({len(videos)} Videos)")
    if not args.no_state_update:
        print(f"State-Matches: {matched} Posts aktualisiert")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TikTokApiError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
