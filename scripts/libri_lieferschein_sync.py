#!/usr/bin/env python3
"""Check Mein.Libri for delivery notes and hand tracking back to TikTok Shop.

The script keeps all operational state in .automation/libri_order_state.json.
It intentionally stores only order/package IDs, EANs, delivery-note metadata, and
tracking values. It does not print customer addresses or secrets.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_libri_product_pages import fetch, load_env_file, login  # noqa: E402
from tiktok_order_automation import TikTokApiError, TikTokShopClient, clean, env_value  # noqa: E402


DEFAULT_STATE_PATH = Path(".automation") / "libri_order_state.json"
DEFAULT_OUTPUT_DIR = Path("outputs") / "libri_lieferschein_sync"
DEFAULT_DOCUMENT_URLS = [
    "https://mein.libri.de/Service/Lieferscheine.html",
    "https://mein.libri.de/Service/Belege.html",
    "https://mein.libri.de/Service/Rechnungen.html",
    "https://mein.libri.de/Service/Dokumente.html",
    "https://mein.libri.de/Mein-Konto/Belege.html",
]
LINK_HINT_RE = re.compile(r"(?i)(lieferschein|beleg|rechnung|dokument|download|pdf|sendung|tracking)")
TRACKING_CONTEXT_RE = re.compile(
    r"(?i)(?:sendungs(?:nummer)?|tracking(?:nummer)?|paket(?:nummer)?|dhl|dpd|ups|hermes|sendung)[^\n<]{0,180}"
)
TOKEN_RE = re.compile(r"\b[A-Z0-9][A-Z0-9 \-]{8,48}[A-Z0-9]\b", re.IGNORECASE)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def normalize(value: object) -> str:
    return re.sub(r"\s+", " ", clean(value)).casefold()


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"libri_submissions": {}, "delivery_notes": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("libri_submissions", {})
    state.setdefault("delivery_notes", {})
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def document_urls(env: dict[str, str]) -> list[str]:
    configured = env_value(env, "LIBRI_DELIVERY_NOTE_URLS")
    if configured:
        return [part.strip() for part in re.split(r"[,\n]", configured) if part.strip()]
    return DEFAULT_DOCUMENT_URLS


def safe_file_name(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")[:40]
    return f"{label or 'page'}_{digest}.html"


def save_page(output_dir: Path, url: str, body: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / safe_file_name(url)).write_text(body, encoding="utf-8")


def discover_links(base_url: str, body: str) -> list[str]:
    links: list[str] = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', body, flags=re.IGNORECASE):
        decoded = html.unescape(href)
        if LINK_HINT_RE.search(decoded):
            links.append(urljoin(base_url, decoded))
    return list(dict.fromkeys(links))


def fetch_document_pages(opener, urls: list[str], output_dir: Path, max_pages: int) -> list[tuple[str, str]]:
    queue = list(dict.fromkeys(urls))
    seen: set[str] = set()
    pages: list[tuple[str, str]] = []
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            final_url, body = fetch(opener, url)
        except Exception as exc:
            print(f"Libri document page fetch failed for configured URL #{len(seen)}: {type(exc).__name__}")
            continue
        if "Login.html" in final_url or "Mein.Libri - Login" in body:
            print("Libri document page redirected to login; skipping that page.")
            continue
        save_page(output_dir, final_url, body)
        pages.append((final_url, body))
        for link in discover_links(final_url, body):
            if link not in seen and link not in queue:
                queue.append(link)
    return pages


def order_keys(order_id: str, submission: dict) -> list[str]:
    keys = [order_id, clean(submission.get("package_id"))]
    eans = submission.get("eans") if isinstance(submission.get("eans"), list) else []
    keys.extend(clean(ean) for ean in eans)
    return [key for key in keys if key]


def page_mentions_order(body: str, order_id: str, submission: dict) -> bool:
    decoded = html.unescape(body)
    text = normalize(decoded)
    if not any(word in text for word in ["lieferschein", "sendung", "tracking", "paket", "versand"]):
        return False
    keys = order_keys(order_id, submission)
    return any(key and key in decoded for key in keys)


def infer_carrier(context: str, default_carrier: str) -> str:
    upper = context.upper()
    if "DHL" in upper:
        return "DHL"
    if "DPD" in upper:
        return "DPD"
    if "HERMES" in upper:
        return "Hermes"
    if "UPS" in upper:
        return "UPS"
    return default_carrier


def normalize_tracking_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def plausible_tracking(token: str, known_values: set[str]) -> bool:
    if not (10 <= len(token) <= 40):
        return False
    if not any(ch.isdigit() for ch in token):
        return False
    if token in known_values:
        return False
    if re.fullmatch(r"97[89]\d{10}", token):
        return False
    return True


def extract_tracking(body: str, known_values: set[str], default_carrier: str) -> tuple[str, str]:
    decoded = html.unescape(body)
    for context in TRACKING_CONTEXT_RE.findall(decoded):
        for raw_token in TOKEN_RE.findall(context):
            token = normalize_tracking_token(raw_token)
            if plausible_tracking(token, known_values):
                return token, infer_carrier(context, default_carrier)
    return "", ""


def create_issue(title: str, body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("GitHub issue not created because GITHUB_TOKEN or GITHUB_REPOSITORY is missing.")
        return
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body}).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "libri-lieferschein-sync",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        issue = json.loads(response.read().decode("utf-8"))
    print(f"Created GitHub issue: {issue.get('html_url')}")


def tiktok_fulfillment_payloads(package_id: str, tracking_number: str, carrier: str, env: dict[str, str]) -> list[dict]:
    provider_id = env_value(env, "TIKTOK_SHIPPING_PROVIDER_ID")
    provider_name = env_value(env, "TIKTOK_SHIPPING_PROVIDER_NAME", carrier or "DHL")
    base = {
        "tracking_number": tracking_number,
        "shipping_provider_name": provider_name,
    }
    if provider_id:
        base["shipping_provider_id"] = provider_id
    return [
        {**base, "package_id": package_id},
        dict(base),
    ]


def tiktok_fulfillment_paths(client: TikTokShopClient, package_id: str, env: dict[str, str]) -> list[str]:
    configured = env_value(env, "TIKTOK_SHIP_PACKAGE_PATH_TEMPLATE")
    if configured:
        return [configured.format(version=client.version, package_id=package_id)]
    return [
        f"/fulfillment/{client.version}/packages/{package_id}/ship",
        f"/fulfillment/{client.version}/packages/{package_id}/shipping_info",
    ]


def send_tracking_to_tiktok(order_id: str, package_id: str, tracking_number: str, carrier: str, env: dict[str, str], env_path: Path) -> tuple[bool, str]:
    if not package_id:
        return False, "missing_package_id"
    if not tracking_number:
        return False, "missing_tracking_number"
    client = TikTokShopClient(env, env_path)
    shop_cipher = client.ensure_shop_cipher()
    errors: list[str] = []
    for path in tiktok_fulfillment_paths(client, package_id, env):
        for body in tiktok_fulfillment_payloads(package_id, tracking_number, carrier, env):
            try:
                client.request("POST", path, params={"shop_cipher": shop_cipher}, body=body)
                return True, path
            except TikTokApiError as exc:
                errors.append(f"{path}: {str(exc)[:240]}")
    return False, " | ".join(errors[-3:]) or "unknown_tiktok_api_error"


def submitted_unfulfilled_orders(state: dict) -> dict[str, dict]:
    submissions = state.get("libri_submissions", {})
    delivery_notes = state.get("delivery_notes", {})
    result: dict[str, dict] = {}
    for order_id, submission in submissions.items():
        if not isinstance(submission, dict) or submission.get("status") != "submitted":
            continue
        note = delivery_notes.get(order_id, {}) if isinstance(delivery_notes, dict) else {}
        if isinstance(note, dict) and note.get("tiktok_status") == "fulfilled":
            continue
        result[order_id] = submission
    return result


def write_summary(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["order_id", "package_id", "delivery_note_status", "tracking_status", "tiktok_status", "detail"]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check Mein.Libri Lieferschein pages and update TikTok with tracking.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--update-tiktok", action="store_true")
    parser.add_argument("--create-issues", action="store_true")
    parser.add_argument("--default-carrier", default="DHL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = Path(args.env)
    env = load_env_file(env_path)
    state_path = Path(args.state)
    state = load_state(state_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pending = submitted_unfulfilled_orders(state)
    if not pending:
        print("No submitted Libri orders are waiting for TikTok fulfillment.")
        write_summary(output_dir / "summary.csv", [])
        return 0

    opener = login(env_path)
    pages = fetch_document_pages(opener, document_urls(env), output_dir, args.max_pages)
    delivery_notes = state.setdefault("delivery_notes", {})
    rows: list[dict[str, str]] = []
    failures = 0

    for order_id, submission in pending.items():
        package_id = clean(submission.get("package_id"))
        known = set(order_keys(order_id, submission))
        match = next(((url, body) for url, body in pages if page_mentions_order(body, order_id, submission)), None)
        if not match:
            rows.append(
                {
                    "order_id": order_id,
                    "package_id": package_id,
                    "delivery_note_status": "not_found",
                    "tracking_status": "not_checked",
                    "tiktok_status": "not_updated",
                    "detail": "No matching Libri delivery-note page yet.",
                }
            )
            continue

        url, body = match
        tracking_number, carrier = extract_tracking(body, known, args.default_carrier)
        doc_key = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:16]
        note = delivery_notes.setdefault(order_id, {})
        note.update(
            {
                "delivery_note_status": "found",
                "found_at": now_utc(),
                "document_key": doc_key,
                "document_url_hash": hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
                "package_id": package_id,
            }
        )

        if not tracking_number:
            note["tracking_status"] = "missing"
            rows.append(
                {
                    "order_id": order_id,
                    "package_id": package_id,
                    "delivery_note_status": "found",
                    "tracking_status": "missing",
                    "tiktok_status": "not_updated",
                    "detail": "Delivery note found, but no tracking number was detected.",
                }
            )
            if args.create_issues and not note.get("tracking_issue_reported"):
                create_issue(
                    f"Libri Lieferschein found but tracking missing ({order_id})",
                    "A Libri delivery-note page was found for this TikTok order, but the automation could not detect a tracking number. No customer address data is included in this issue.",
                )
                note["tracking_issue_reported"] = now_utc()
            failures += 1
            continue

        note.update({"tracking_status": "found", "tracking_number": tracking_number, "carrier": carrier})
        if not args.update_tiktok:
            rows.append(
                {
                    "order_id": order_id,
                    "package_id": package_id,
                    "delivery_note_status": "found",
                    "tracking_status": "found",
                    "tiktok_status": "dry_run",
                    "detail": "Tracking found, but TikTok update was not requested.",
                }
            )
            continue

        ok, detail = send_tracking_to_tiktok(order_id, package_id, tracking_number, carrier, env, env_path)
        if ok:
            note.update({"tiktok_status": "fulfilled", "fulfilled_at": now_utc(), "tiktok_api_path": detail})
            rows.append(
                {
                    "order_id": order_id,
                    "package_id": package_id,
                    "delivery_note_status": "found",
                    "tracking_status": "found",
                    "tiktok_status": "fulfilled",
                    "detail": "Tracking handed back to TikTok Shop.",
                }
            )
        else:
            note.update({"tiktok_status": "failed", "last_tiktok_error": detail, "last_tiktok_attempt_at": now_utc()})
            rows.append(
                {
                    "order_id": order_id,
                    "package_id": package_id,
                    "delivery_note_status": "found",
                    "tracking_status": "found",
                    "tiktok_status": "failed",
                    "detail": detail,
                }
            )
            if args.create_issues and not note.get("tiktok_issue_reported"):
                create_issue(
                    f"TikTok tracking update failed ({order_id})",
                    "A Libri tracking number was found, but TikTok fulfillment update failed. No customer address data is included in this issue. Check the workflow logs and .automation/libri_order_state.json for the technical status.",
                )
                note["tiktok_issue_reported"] = now_utc()
            failures += 1

    save_state(state_path, state)
    write_summary(output_dir / "summary.csv", rows)
    print(f"Libri Lieferschein sync checked {len(pending)} submitted order(s); failures needing attention: {failures}.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
