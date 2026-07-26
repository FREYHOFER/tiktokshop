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
from typing import Any
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_libri_product_pages import fetch, load_env_file, login  # noqa: E402
from tiktok_order_automation import TikTokShopClient, clean, env_value  # noqa: E402
from update_tiktok_quantities_from_libri import TikTokInventoryClient  # noqa: E402


DEFAULT_OUTPUT_ROOT = Path("outputs") / "tiktok_shop_ops_audit"
DEFAULT_LIBRI_BASE_URL = "https://mein.libri.de/"
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
ISSUE_TITLE = "TikTok/Libri integration needs configuration"
ISSUE_FINGERPRINT = "tiktok-libri-integration-config"
SENSITIVE_DETAIL_KEY_RE = re.compile(
    r"(?i)([\"']?(?:access_token|refresh_token|app_secret|password|signature|authorization|cookie|phone|email|address|recipient|buyer|customer|shop_cipher)[\"']?\s*[:=]\s*)([\"'][^\"']*[\"']|[^,\s&}]+)"
)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def csv_list(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,\n]", clean(value)) if part.strip()]


def configured_list(value: str) -> list[str]:
    text = clean(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [clean(item).strip("\"'") for item in parsed if clean(item)]
    return [part.strip().strip("\"'") for part in re.split(r"[,\n;]", text) if part.strip()]


def normalize_libri_url(value: str) -> str:
    text = clean(value).strip("\"'")
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("mein.libri.de"):
        return "https://" + text
    return urljoin(DEFAULT_LIBRI_BASE_URL, text)


def libri_document_urls(env: dict[str, str]) -> list[str]:
    configured = [normalize_libri_url(item) for item in configured_list(env_value(env, "LIBRI_DELIVERY_NOTE_URLS"))]
    configured = [url for url in configured if url]
    return list(dict.fromkeys(configured or DEFAULT_LIBRI_DOCUMENT_URLS))


def path_version(path: str) -> str:
    match = re.search(r"/(\d{6})(?:/|$)", path)
    return match.group(1) if match else ""


def audit_required_config(env: dict[str, str], rows: list[dict[str, str]]) -> None:
    missing = [
        key
        for key in [
            "LIBRI_CUSTOMER_NUMBER",
            "LIBRI_USERNAME",
            "LIBRI_PASSWORD",
            "TIKTOK_APP_KEY",
            "TIKTOK_APP_SECRET",
        ]
        if not env_value(env, key)
    ]
    if not env_value(env, "TIKTOK_ACCESS_TOKEN") and not env_value(env, "TIKTOK_REFRESH_TOKEN"):
        missing.append("TIKTOK_ACCESS_TOKEN or TIKTOK_REFRESH_TOKEN")

    if missing:
        rows.append(
            row(
                "required_secrets",
                "failed",
                "Missing GitHub Environment secret(s): " + ", ".join(missing),
                "Set the missing values in the shop environment; do not paste them into logs or issues.",
            )
        )


def safe_detail(exc: Exception | str) -> str:
    text = str(exc)
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._\-]+", "Bearer <redacted>", text)
    text = SENSITIVE_DETAIL_KEY_RE.sub(
        lambda match: match.group(1)
        + (
            f"{match.group(2)[0]}<redacted>{match.group(2)[0]}"
            if match.group(2).startswith(("\"", "'"))
            else "<redacted>"
        ),
        text,
    )
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<redacted-email>", text)
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


def github_json_request(url: str, token: str, method: str = "GET", payload: dict | None = None) -> dict | list:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "tiktok-shop-integration-audit",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def find_existing_issues(repo: str, token: str, fingerprint: str, title: str) -> list[dict[str, Any]]:
    marker = f"<!-- {fingerprint} -->"
    query = urllib.parse.urlencode({"state": "open", "per_page": "100"})
    issues = github_json_request(f"https://api.github.com/repos/{repo}/issues?{query}", token)
    if not isinstance(issues, list):
        return []
    matches: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict) or "pull_request" in issue:
            continue
        if marker in str(issue.get("body") or "") or clean(issue.get("title")) == title:
            matches.append(issue)
    matches.sort(key=lambda issue: (marker not in str(issue.get("body") or ""), int(issue.get("number") or 0)))
    return matches


def close_duplicate_issue(repo: str, token: str, duplicate: dict[str, Any], primary_url: str) -> None:
    number = duplicate.get("number")
    if not number:
        return
    github_json_request(
        f"https://api.github.com/repos/{repo}/issues/{number}/comments",
        token,
        method="POST",
        payload={"body": f"Closing as a duplicate of the current integration configuration tracker: {primary_url}"},
    )
    github_json_request(
        f"https://api.github.com/repos/{repo}/issues/{number}",
        token,
        method="PATCH",
        payload={"state": "closed", "state_reason": "not_planned"},
    )


def create_issue_once(title: str, body: str, fingerprint: str) -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print(f"Issue not created ({fingerprint}): missing GitHub token/repo.")
        return
    marker = f"<!-- {fingerprint} -->"
    try:
        existing_issues = find_existing_issues(repo, token, fingerprint, title)
        if existing_issues:
            existing = existing_issues[0]
            issue_number = existing.get("number")
            github_json_request(
                f"https://api.github.com/repos/{repo}/issues/{issue_number}",
                token,
                method="PATCH",
                payload={"title": title, "body": marker + "\n" + body},
            )
            for duplicate in existing_issues[1:]:
                close_duplicate_issue(repo, token, duplicate, str(existing.get("html_url") or ""))
            print(f"Updated existing issue: {existing.get('html_url')}")
            return
        issue = github_json_request(
            f"https://api.github.com/repos/{repo}/issues",
            token,
            method="POST",
            payload={"title": title, "body": marker + "\n" + body},
        )
        if isinstance(issue, dict):
            print(f"Created issue: {issue.get('html_url')}")
    except Exception as exc:
        print(f"Issue create/update failed ({fingerprint}): {type(exc).__name__}")


def find_values_by_key(source: Any, keys: set[str], depth: int = 0) -> list[str]:
    if depth > 8:
        return []
    values: list[str] = []
    if isinstance(source, dict):
        for key, value in source.items():
            if str(key) in keys:
                if isinstance(value, dict):
                    values.extend(find_values_by_key(value, {"id", "delivery_option_id"}, depth + 1))
                elif isinstance(value, list):
                    values.extend(find_values_by_key(value, keys, depth + 1))
                else:
                    item = clean(value)
                    if item:
                        values.append(item)
            else:
                values.extend(find_values_by_key(value, keys, depth + 1))
    elif isinstance(source, list):
        for item in source:
            values.extend(find_values_by_key(item, keys, depth + 1))
    return list(dict.fromkeys(values))


def provider_label(provider: dict[str, Any]) -> str:
    return clean(
        provider.get("name")
        or provider.get("shipping_provider_name")
        or provider.get("provider_name")
        or provider.get("display_name")
    )


def provider_id(provider: dict[str, Any]) -> str:
    return clean(provider.get("id") or provider.get("shipping_provider_id") or provider.get("provider_id"))


def extract_provider_candidates(source: Any, depth: int = 0) -> list[dict[str, str]]:
    if depth > 8:
        return []
    candidates: list[dict[str, str]] = []
    if isinstance(source, dict):
        item_id = provider_id(source)
        item_name = provider_label(source)
        if item_id and item_name:
            candidates.append({"id": item_id, "name": item_name})
        for value in source.values():
            candidates.extend(extract_provider_candidates(value, depth + 1))
    elif isinstance(source, list):
        for item in source:
            candidates.extend(extract_provider_candidates(item, depth + 1))

    deduped: dict[tuple[str, str], dict[str, str]] = {}
    for candidate in candidates:
        deduped.setdefault((candidate["id"], candidate["name"]), candidate)
    return list(deduped.values())


def shipping_provider_probe_paths(client: TikTokShopClient, delivery_option_ids: list[str]) -> list[tuple[str, dict[str, object]]]:
    probes: list[tuple[str, dict[str, object]]] = []
    for delivery_option_id in delivery_option_ids[:5]:
        probes.extend(
            [
                (
                    f"/logistics/{client.version}/delivery_options/{delivery_option_id}/shipping_providers",
                    {},
                ),
                (
                    f"/fulfillment/{client.version}/delivery_options/{delivery_option_id}/shipping_providers",
                    {},
                ),
                (
                    f"/logistics/{client.version}/shipping_providers",
                    {"delivery_option_id": delivery_option_id},
                ),
            ]
        )
    probes.extend(
        [
            (f"/logistics/{client.version}/shipping_providers", {}),
            (f"/fulfillment/{client.version}/shipping_providers", {}),
        ]
    )
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, dict[str, object]]] = []
    for path, params in probes:
        marker = (path, json.dumps(params, sort_keys=True))
        if marker not in seen:
            seen.add(marker)
            unique.append((path, params))
    return unique


def discover_shipping_provider_id(
    client: TikTokShopClient,
    env: dict[str, str],
    orders: list[dict],
    provider_name: str,
) -> tuple[str, str]:
    shop_cipher = client.ensure_shop_cipher()
    delivery_option_ids = find_values_by_key(
        orders,
        {
            "delivery_option",
            "delivery_option_id",
            "shipping_service",
            "shipping_service_id",
            "delivery_service",
            "delivery_service_id",
        },
    )
    errors: list[str] = []
    for path, extra_params in shipping_provider_probe_paths(client, delivery_option_ids):
        params = {"shop_cipher": shop_cipher, **extra_params}
        try:
            response = client.request("GET", path, params=params, body=None)
        except Exception as exc:
            errors.append(f"{path}: {safe_detail(exc)}")
            continue
        providers = extract_provider_candidates(response)
        match = next(
            (
                provider
                for provider in providers
                if provider_name.casefold() in provider["name"].casefold()
                or provider["name"].casefold() in provider_name.casefold()
            ),
            None,
        )
        if match:
            return match["id"], f"{match['name']} via {path}"
        if providers:
            labels = ", ".join(f"{provider['name']} ({provider['id']})" for provider in providers[:5])
            errors.append(f"{path}: DHL not found; available providers: {labels}")
    if not delivery_option_ids:
        errors.append("No delivery_option_id-like value was visible in current order data.")
    return "", " | ".join(errors[-3:])[:900]


def audit_tiktok_orders(env: dict[str, str], env_path: Path, rows: list[dict[str, str]]) -> tuple[TikTokShopClient | None, list[dict]]:
    try:
        client = TikTokShopClient(env, env_path)
        shop_cipher = client.ensure_shop_cipher()
        rows.append(row("tiktok_auth", "ok", "Shop authorization works."))
        orders = client.search_awaiting_orders(env_value(env, "TIKTOK_ORDER_STATUS", "AWAITING_SHIPMENT"), page_size=20, hours_back=168)
        rows.append(row("tiktok_orders", "ok", f"Awaiting-shipment search returned {len(orders)} order(s)."))
        if not shop_cipher:
            rows.append(row("tiktok_shop_cipher", "warning", "Shop cipher was empty after auth.", "Set TIKTOK_SHOP_CIPHER."))
        return client, orders
    except Exception as exc:
        rows.append(row("tiktok_orders", "failed", safe_detail(exc), "Refresh TikTok token and check app scopes for order read access."))
        return None, []


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
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        rows.append(row("libri_login", "failed", safe_detail(exc), "Check LIBRI_CUSTOMER_NUMBER, LIBRI_USERNAME, LIBRI_PASSWORD."))
        return

    configured = bool(configured_list(env_value(env, "LIBRI_DELIVERY_NOTE_URLS")))
    urls = libri_document_urls(env)
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
        version = path_version(path)
        base_params: dict[str, object] = {"page_size": 10}
        if version:
            base_params["version"] = version
        param_variants: list[dict[str, object]] = []
        if shop_cipher:
            param_variants.append({**base_params, "shop_cipher": shop_cipher})
        param_variants.append(dict(base_params))
        last_error = ""
        for params in param_variants:
            try:
                client.request("POST", path, params=params, body={})
                successes += 1
                last_error = ""
                break
            except Exception as exc:
                last_error = safe_detail(exc)
        if last_error:
            failures.append(f"{path}: {last_error}")
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


def audit_shipping_provider_id(
    env: dict[str, str],
    env_path: Path,
    rows: list[dict[str, str]],
    client: TikTokShopClient | None,
    orders: list[dict],
) -> None:
    provider_name = env_value(env, "TIKTOK_SHIPPING_PROVIDER_NAME", "DHL")
    provider_id_value = env_value(env, "TIKTOK_SHIPPING_PROVIDER_ID")
    if provider_id_value:
        rows.append(row("tiktok_shipping_provider_id", "ok", "TikTok shipping provider ID is configured."))
        return
    if not provider_name:
        rows.append(row("tiktok_shipping_provider_id", "warning", "Shipping provider name is empty.", "Set TIKTOK_SHIPPING_PROVIDER_NAME to DHL."))
        return
    if client is None:
        rows.append(row("tiktok_shipping_provider_id", "blocked", "TikTok auth/order audit did not produce a client.", "Fix TikTok API auth first."))
        return

    try:
        discovered_id, detail = discover_shipping_provider_id(client, env, orders, provider_name)
    except Exception as exc:
        rows.append(row("tiktok_shipping_provider_id", "warning", safe_detail(exc), "Set TIKTOK_SHIPPING_PROVIDER_ID manually if TikTok fulfillment requires it."))
        return
    if discovered_id:
        rows.append(
            row(
                "tiktok_shipping_provider_id",
                "warning",
                f"Discovered {provider_name} shipping provider ID candidate: {discovered_id}. Source: {detail}",
                f"Set TIKTOK_SHIPPING_PROVIDER_ID to {discovered_id}.",
            )
        )
    else:
        rows.append(
            row(
                "tiktok_shipping_provider_id",
                "warning",
                detail or "DHL shipping provider ID was not discovered.",
                "Use TikTok Seller Center/API logistics settings to confirm DHL's shipping provider ID.",
            )
        )


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

    audit_required_config(env, rows)
    audit_fulfillment_config(env, rows)
    tiktok_client, orders = audit_tiktok_orders(env, env_path, rows)
    audit_shipping_provider_id(env, env_path, rows, tiktok_client, orders)
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
        create_issue_once(ISSUE_TITLE, "\n".join(body_lines), ISSUE_FINGERPRINT)

    print(f"TikTok Shop integration audit complete: {len(attention)} item(s) need attention. Output: {run_dir}")
    return 1 if any(item["status"] == "failed" for item in attention) else 0


if __name__ == "__main__":
    raise SystemExit(main())
