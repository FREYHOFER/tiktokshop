#!/usr/bin/env python3
"""Audit TikTok Shop + Libri integration coverage without exposing secrets.

This script is deliberately read-only for TikTok and Libri except for optional
GitHub issue creation. It checks that the current automation can reach the core
surfaces needed for daily operations:
- TikTok shop authorization
- pending TikTok orders
- TikTok product/listing search
- Libri login and configured document/Lieferschein pages
- affiliate/sample API configuration probes, if configured

It writes a machine-readable CSV and a human-readable Markdown summary under
outputs/tiktok_shop_ops_audit/<timestamp>/.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_libri_product_pages import fetch, load_env_file, login  # noqa: E402
from tiktok_order_automation import TikTokApiError, TikTokShopClient, clean, env_value  # noqa: E402
from update_tiktok_quantities_from_libri import TikTokInventoryClient  # noqa: E402


DEFAULT_OUTPUT_ROOT = Path("outputs") / "tiktok_shop_ops_audit"
DEFAULT_LIBRI_DOCUMENT_URLS = [
    "https://mein.libri.de/Service/Lieferscheine.html",
    "https://mein.libri.de/Service/Belege.html",
    "https://mein.libri.de/Service/Rechnungen.html",
    "https://mein.libri.de/Service/Dokumente.html",
    "https://mein.libri.de/Mein-Konto/Belege.html",
]
DEFAULT_AFFILIATE_PROBE_PATHS = [
    "/affiliate_seller/202405/open_collaborations/search",
    "/affiliate_seller/202405/sample_applications/search",
    "/affiliate_creator/202412/sample_applications/search",
]
FIELDS = ["area", "status", "detail", "action"]


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def csv_list(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,\n]", clean(value)) if part.strip()]


def safe_detail(exc: Exception | str) -> str:
    text = str(exc)
    text = re.sub(r"(?i)(access_token|app_secret|password|signature|sign)[^,\s}]+", r"\1=<redacted>", text)
    text = re.sub(r"[A-Za-z0-9_\-]{35,}", "<redacted>", text)
    return text[:900]


def row(area: str, status: str, detail: str = "", action: str = "") -> dict[str, str]:
    return {"area": area, "status": status, "detail": detail, "action": action}


def write_outputs(run_dir: Path, rows: list[dict[str, str]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / "summary.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    counts: dict[str, int] = {}
    for item in rows:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    lines = [
        "# TikTok Shop Integration Audit",
        "",
        f"Generated UTC: {now_utc()}",
        "",
        "## Counts",
        "",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Findings", ""])
    for item in rows:
        action = f" Action: {item['action']}" if item.get("action") else ""
        lines.append(f"- **{item['area']}**: `{item['status']}` — {item.get('detail', '')}{action}")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_issue_once(title: str, body: str, fingerprint: str) -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print(f"Issue not created ({fingerprint}): missing GitHub token/repo.")
        return
    marker = f"<!-- {fingerprint} -->"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": marker + "\n" + body}).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "tiktok-shop-integration-audit",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            issue = json.loads(response.read().decode("utf-8"))
        print(f"Created issue: {issue.get('html_url')}")
    except Exception as exc:
        print(f"Issue creation failed ({fingerprint}): {type(exc).__name__}")


def audit_tiktok_orders(env: dict[str, str], env_path: Path, rows: list[dict[str, str]]) -> TikTokShopClient | None:
    try:
        client = TikTokShopClient(env, env_path)
        shop_cipher = client.ensure_shop_cipher()
        rows.append(row("tiktok_auth", "ok", "Shop authorization works."))
        orders = client.search_awaiting_orders(env_value(env, "TIKTOK_ORDER_STATUS", "AWAITING_SHIPMENT"), page_size=20, hours_back=168)
        rows.append(row("tiktok_orders", "ok", f"Awaiting-shipment search returned {len(orders)} order(s)."))
        if not shop_cipher:
            rows.append(row("tiktok_shop_cipher", "warning", "Shop cipher was empty after auth.", "Set TIKTOK_SHOP_CIPHER."))
        return client
    except Exception as exc:
        rows.append(row("tiktok_orders", "failed", safe_detail(exc), "Refresh TikTok token and check app scopes for order read access."))
        return None


def audit_products(env: dict[str, str], env_path: Path, rows: list[dict[str, str]]) -> None:
    try:
        client = TikTokInventoryClient(env, env_path)
        products = client.search_products(page_size=20, max_pages=1)
        issue_count = 0
        active_like = 0
        for product in products:
            status = clean(product.get("status") or product.get("product_status"))
            if status in {"ACTIVATE", "SELLER_DEACTIVATED"}:
                active_like += 1
            if status in {"FAILED", "FREEZE", "LOCKED", "PENDING"}:
                issue_count += 1
        rows.append(row("tiktok_products", "ok", f"Product search returned {len(products)} product(s); {issue_count} with review/error-like statuses."))
        if not products:
            rows.append(row("assortment", "warning", "No products returned by product search.", "Check product API scope and shop cipher."))
        elif active_like == 0:
            rows.append(row("assortment", "warning", "No active/seller-deactivated products found in first page.", "Check whether product status filters need adjustment."))
    except Exception as exc:
        rows.append(row("tiktok_products", "failed", safe_detail(exc), "Check product API scopes and TIKTOK_WAREHOUSE_ID."))


def audit_libri(env: dict[str, str], env_path: Path, rows: list[dict[str, str]], run_dir: Path) -> None:
    try:
        opener = login(env_path)
        rows.append(row("libri_login", "ok", "Mein.Libri login works."))
    except Exception as exc:
        rows.append(row("libri_login", "failed", safe_detail(exc), "Check LIBRI_CUSTOMER_NUMBER, LIBRI_USERNAME, LIBRI_PASSWORD."))
        return

    configured = csv_list(env_value(env, "LIBRI_DELIVERY_NOTE_URLS"))
    urls = configured or DEFAULT_LIBRI_DOCUMENT_URLS
    found_pages = 0
    for url in urls[:10]:
        try:
            final_url, body = fetch(opener, url)
            if "Login.html" in final_url or "Mein.Libri - Login" in body:
                continue
            found_pages += 1
            path = run_dir / "libri_pages" / (re.sub(r"[^A-Za-z0-9_.-]+", "_", url)[:80] + ".html")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        except Exception:
            continue
    if found_pages:
        source = "configured" if configured else "default guess"
        rows.append(row("libri_lieferschein_pages", "ok", f"Fetched {found_pages} Libri document page(s) using {source} URLs."))
    else:
        rows.append(row("libri_lieferschein_pages", "warning", "No Libri Lieferschein/document page could be fetched from current URLs.", "Set LIBRI_DELIVERY_NOTE_URLS to the exact Mein.Libri Lieferschein/Belege page after login."))


def audit_affiliate(env: dict[str, str], env_path: Path, rows: list[dict[str, str]]) -> None:
    paths = csv_list(env_value(env, "TIKTOK_AFFILIATE_AUDIT_PATHS")) or DEFAULT_AFFILIATE_PROBE_PATHS
    try:
        client = TikTokShopClient(env, env_path)
        shop_cipher = client.ensure_shop_cipher()
    except Exception as exc:
        rows.append(row("affiliate_samples", "blocked", safe_detail(exc), "Fix base TikTok API auth first."))
        return

    successes = 0
    failures: list[str] = []
    for path in paths[:6]:
        try:
            client.request("POST", path, params={"shop_cipher": shop_cipher, "page_size": 10}, body={})
            successes += 1
        except Exception as exc:
            failures.append(f"{path}: {safe_detail(exc)}")
    if successes:
        rows.append(row("affiliate_samples", "ok", f"{successes} affiliate/sample probe endpoint(s) responded successfully."))
    else:
        rows.append(row("affiliate_samples", "warning", "Affiliate/sample probes did not succeed.", "Enable Affiliate API scopes and, if needed, set TIKTOK_AFFILIATE_AUDIT_PATHS to the exact seller sample endpoints available for the app."))
        if failures:
            rows.append(row("affiliate_samples_detail", "info", " | ".join(failures[-2:])[:900]))


def audit_fulfillment_config(env: dict[str, str], rows: list[dict[str, str]]) -> None:
    provider_name = env_value(env, "TIKTOK_SHIPPING_PROVIDER_NAME", "DHL")
    provider_id = env_value(env, "TIKTOK_SHIPPING_PROVIDER_ID")
    path_template = env_value(env, "TIKTOK_SHIP_PACKAGE_PATH_TEMPLATE", "/fulfillment/{version}/packages/{package_id}/ship")
    detail = f"provider_name={provider_name or '<empty>'}; provider_id={'set' if provider_id else 'not_set'}; path_template={path_template}"
    if provider_name:
        rows.append(row("tiktok_fulfillment_config", "ok", detail))
    else:
        rows.append(row("tiktok_fulfillment_config", "warning", detail, "Set TIKTOK_SHIPPING_PROVIDER_NAME, usually DHL."))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit TikTok Shop and Libri automation integration coverage.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--create-issues", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = Path(args.env)
    env = load_env_file(env_path)
    run_dir = Path(args.output_root) / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    rows: list[dict[str, str]] = []

    audit_fulfillment_config(env, rows)
    audit_tiktok_orders(env, env_path, rows)
    audit_products(env, env_path, rows)
    audit_affiliate(env, env_path, rows)
    audit_libri(env, env_path, rows, run_dir)
    write_outputs(run_dir, rows)

    attention = [item for item in rows if item["status"] in {"failed", "warning", "blocked"}]
    if args.create_issues and attention:
        body_lines = [
            "The daily TikTok Shop integration audit found setup gaps.",
            "",
            "No secrets or customer addresses are included here.",
            "",
        ]
        for item in attention:
            body_lines.append(f"- **{item['area']}**: `{item['status']}` — {item['detail']} Action: {item.get('action', '')}")
        create_issue_once("TikTok/Libri integration needs configuration", "\n".join(body_lines), "tiktok-libri-integration-config")

    print(f"TikTok Shop integration audit complete: {len(attention)} item(s) need attention. Output: {run_dir}")
    return 1 if any(item["status"] == "failed" for item in attention) else 0


if __name__ == "__main__":
    raise SystemExit(main())
