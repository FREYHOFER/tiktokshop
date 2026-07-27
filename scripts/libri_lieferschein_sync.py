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
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_libri_product_pages import fetch, load_env_file, login  # noqa: E402
from tiktok_order_automation import TikTokApiError, TikTokShopClient, clean, env_value  # noqa: E402


DEFAULT_STATE_PATH = Path(".automation") / "libri_order_state.json"
DEFAULT_OUTPUT_DIR = Path("outputs") / "libri_lieferschein_sync"
DEFAULT_DELIVERY_NOTE_GRACE_HOURS = 36
DEFAULT_DOCUMENT_URLS = [
    "https://mein.libri.de/Auftrag/Bestellungen.html",
    "https://mein.libri.de/lieferung/lieferscheine-und-gutschriftanzeigen.html",
    "https://mein.libri.de/lieferung/Verlags-BS-Sendungen.html",
    "https://mein.libri.de/Service/Lieferscheine.html",
    "https://mein.libri.de/Service/Belege.html",
    "https://mein.libri.de/Service/Rechnungen.html",
    "https://mein.libri.de/Service/Dokumente.html",
    "https://mein.libri.de/Mein-Konto/Belege.html",
]
LINK_HINT_RE = re.compile(
    r"(?i)(lieferschein|beleg|rechnung|dokument|download|pdf|sendung|tracking|auftrag|auftraege|bestellung|delivery-note)"
)
TRACKING_CONTEXT_RE = re.compile(
    r"(?i)(?:sendungs(?:nummer)?|tracking(?:nummer)?|paket(?:nummer)?|dhl|dpd|ups|hermes|sendung)[^\n<]{0,180}"
)
TOKEN_RE = re.compile(r"\b[A-Z0-9][A-Z0-9 \-]{8,48}[A-Z0-9]\b", re.IGNORECASE)
EAN_RE = re.compile(r"97[89]\d{10}")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def normalize(value: object) -> str:
    return re.sub(r"\s+", " ", clean(value)).casefold()


def visible_text(body: str) -> str:
    decoded = html.unescape(body)
    decoded = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", decoded)
    decoded = re.sub(r"(?is)<[^>]+>", " ", decoded)
    return re.sub(r"\s+", " ", decoded)


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


def env_int(env: dict[str, str], name: str, default: int) -> int:
    value = env_value(env, name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        print(f"Ignoring invalid integer value for {name}; using {default}.")
        return default


def with_query(url: str, updates: dict[str, str]) -> str:
    parsed = urlparse(url)
    current = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in updates]
    current.extend((key, value) for key, value in updates.items() if value != "")
    return urlunparse(parsed._replace(query=urlencode(current)))


def search_values_for_submission(order_id: str, submission: dict) -> list[str]:
    values = [order_id, clean(submission.get("package_id")), clean(submission.get("libri_order_number"))]
    eans = submission.get("eans") if isinstance(submission.get("eans"), list) else []
    values.extend(clean(ean) for ean in eans)
    return [value for value in dict.fromkeys(values) if value]


def expanded_document_urls(base_urls: list[str], pending: dict[str, dict]) -> list[str]:
    urls: list[str] = []

    def add(url: str) -> None:
        cleaned = clean(url)
        if cleaned and cleaned not in urls:
            urls.append(cleaned)

    for url in base_urls:
        add(url)

    for url in list(urls):
        lowered = url.casefold()
        if "auftrag/bestellungen" in lowered:
            add(with_query(url, {"filter[date_interval]": "long", "filter[order_type]": "c", "ps": "200"}))
            for order_id, submission in pending.items():
                for value in search_values_for_submission(order_id, submission):
                    if EAN_RE.fullmatch(value):
                        add(
                            with_query(
                                url,
                                {
                                    "filter[date_interval]": "long",
                                    "filter[order_type]": "c",
                                    "filter[article_number]": value,
                                    "ps": "200",
                                },
                            )
                        )
                    else:
                        add(
                            with_query(
                                url,
                                {
                                    "filter[date_interval]": "long",
                                    "filter[order_type]": "c",
                                    "filter[customer_order_code]": value,
                                    "ps": "200",
                                },
                            )
                        )
                        add(
                            with_query(
                                url,
                                {
                                    "filter[date_interval]": "long",
                                    "filter[order_type]": "c",
                                    "filter[customer_order_position_code]": value,
                                    "ps": "200",
                                },
                            )
                        )
        elif "lieferschein" in lowered or "delivery-note" in lowered or "belege" in lowered:
            add(with_query(url, {"filter[date_interval]": "long", "filter[note_type]": "LIEF", "ps": "200"}))
            for order_id, submission in pending.items():
                for value in search_values_for_submission(order_id, submission):
                    add(
                        with_query(
                            url,
                            {
                                "filter[date_interval]": "long",
                                "filter[note_type]": "LIEF",
                                "filter[order_sign_position]": value,
                                "ps": "200",
                            },
                        )
                    )
                    add(
                        with_query(
                            url,
                            {
                                "filter[date_interval]": "long",
                                "filter[note_type]": "LIEF",
                                "filter[receipt_number]": value,
                                "ps": "200",
                            },
                        )
                    )
        elif "verlags-bs-sendungen" in lowered:
            add(with_query(url, {"filter[date_interval]": "long", "ps": "200"}))

    return urls


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
        decoded = html.unescape(href).strip()
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
    keys.append(clean(submission.get("libri_order_number")))
    eans = submission.get("eans") if isinstance(submission.get("eans"), list) else []
    keys.extend(clean(ean) for ean in eans)
    return [key for key in keys if key]


def page_mentions_known_order(body: str, order_id: str, submission: dict) -> bool:
    decoded = visible_text(body)
    keys = order_keys(order_id, submission)
    return any(key and key in decoded for key in keys)


def url_filters_known_order(url: str, order_id: str, submission: dict) -> bool:
    parsed = urlparse(html.unescape(url))
    values = {clean(value) for _, value in parse_qsl(parsed.query, keep_blank_values=True)}
    keys = set(order_keys(order_id, submission))
    return bool(values & keys)


def has_result_row(body: str) -> bool:
    decoded = html.unescape(body)
    return bool(re.search(r"(?is)<tbody[^>]*>\s*<tr\b", decoded) or re.search(r"(?is)<tr[^>]*class=[\"'][^\"']*\bitem\b", decoded))


def is_detail_page(url: str, body: str) -> bool:
    decoded = html.unescape(body)
    return bool(
        re.search(r"/Auftrag/auftraege/\d+", url, flags=re.IGNORECASE)
        or re.search(r"/lieferung/Verlags-BS-Sendungen/\d+", url, flags=re.IGNORECASE)
        or re.search(r"/document/delivery-note/", url, flags=re.IGNORECASE)
        or "Auftragsbestätigung" in decoded
    )


def is_delivery_context(url: str, body: str) -> bool:
    decoded = html.unescape(body)
    haystack = f"{url} {decoded}".casefold()
    return any(
        marker in haystack
        for marker in [
            "/lieferung/lieferscheine",
            "/lieferung/verlags-bs-sendungen",
            "/document/delivery-note",
            "snippetmoduledeliverynotelistoverview",
            "snippetmodulepackage",
        ]
    )


def is_order_context(url: str, body: str) -> bool:
    decoded = html.unescape(body)
    haystack = f"{url} {decoded}".casefold()
    return any(
        marker in haystack
        for marker in [
            "/auftrag/bestellungen",
            "/auftrag/auftraege/",
            "snippetmoduleorderlistoverview",
            "mein.libri - auftrag - bestellungen",
        ]
    )


def page_mentions_delivery_note(url: str, body: str, order_id: str, submission: dict) -> bool:
    if not is_delivery_context(url, body):
        return False
    text = normalize(visible_text(body))
    if not any(word in text for word in ["lieferschein", "sendungsnummer", "tracking", "paket", "verlags-bs-sendungen", "delivery-note"]):
        return False
    if not has_result_row(body) and not page_mentions_known_order(body, order_id, submission):
        return False
    return page_mentions_known_order(body, order_id, submission)


def page_mentions_libri_order(url: str, body: str, order_id: str, submission: dict) -> bool:
    if not is_order_context(url, body):
        return False
    text = normalize(visible_text(body))
    if not any(word in text for word in ["auftrag", "bestellung", "bestellzeichen", "artikel", "direktversand"]):
        return False
    if not has_result_row(body) and not is_detail_page(url, body):
        return False
    return page_mentions_known_order(body, order_id, submission) or url_filters_known_order(url, order_id, submission)


def extract_libri_order_number(url: str, body: str) -> str:
    for source in [url, html.unescape(body)]:
        match = re.search(r"/Auftrag/auftraege/(\d+)", source, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    match = re.search(r'class=["\']column-order_number["\'][^>]*>\s*(\d+)', html.unescape(body), flags=re.IGNORECASE)
    return match.group(1) if match else ""


def parse_utc_timestamp(value: object) -> dt.datetime | None:
    text = clean(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def submission_age_hours(submission: dict) -> float | None:
    submitted_at = parse_utc_timestamp(submission.get("submitted_at"))
    if submitted_at is None:
        return None
    return (dt.datetime.now(dt.timezone.utc) - submitted_at).total_seconds() / 3600


def overdue_detail(submission: dict, grace_hours: int) -> str:
    age_hours = submission_age_hours(submission)
    if age_hours is None:
        return "No matching Libri delivery-note page was found and the submission timestamp is missing."
    return f"No matching Libri delivery-note page was found {age_hours:.1f} hours after Libri submission."


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
    decoded = visible_text(body)
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
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            issue = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"GitHub issue not created: {type(exc).__name__}")
        return
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
    parser.add_argument("--max-pages", type=int, default=80)
    parser.add_argument("--update-tiktok", action="store_true")
    parser.add_argument("--create-issues", action="store_true")
    parser.add_argument("--default-carrier", default="DHL")
    parser.add_argument(
        "--delivery-note-grace-hours",
        type=int,
        default=DEFAULT_DELIVERY_NOTE_GRACE_HOURS,
        help="Hours after Libri submission before a missing delivery note becomes a failure.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = Path(args.env)
    env = load_env_file(env_path)
    state_path = Path(args.state)
    state = load_state(state_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    delivery_notes = state.setdefault("delivery_notes", {})
    meta = state.setdefault("meta", {})

    pending = submitted_unfulfilled_orders(state)
    if not pending:
        print("No submitted Libri orders are waiting for TikTok fulfillment.")
        write_summary(output_dir / "summary.csv", [])
        return 0

    try:
        opener = login(env_path)
    except SystemExit as exc:
        detail = str(exc) or "Libri login failed."
        rows = [
            {
                "order_id": order_id,
                "package_id": clean(submission.get("package_id")),
                "delivery_note_status": "login_failed",
                "tracking_status": "not_checked",
                "tiktok_status": "not_updated",
                "detail": detail,
            }
            for order_id, submission in pending.items()
        ]
        if args.create_issues and not meta.get("libri_login_issue_reported"):
            create_issue(
                "Libri delivery-note sync login failed",
                "The daily Libri delivery-note sync could not log in to Mein.Libri, so tracking could not be handed back to TikTok. No customer address data is included in this issue. Check the GitHub Actions run and the Libri credentials in the `shop` environment.",
            )
            meta["libri_login_issue_reported"] = now_utc()
        save_state(state_path, state)
        write_summary(output_dir / "summary.csv", rows)
        print(f"Libri Lieferschein sync checked {len(pending)} submitted order(s); failures needing attention: {len(pending)}.")
        return 1

    urls = expanded_document_urls(document_urls(env), pending)
    pages = fetch_document_pages(opener, urls, output_dir, args.max_pages)
    if not pages:
        rows = [
            {
                "order_id": order_id,
                "package_id": clean(submission.get("package_id")),
                "delivery_note_status": "pages_unreadable",
                "tracking_status": "not_checked",
                "tiktok_status": "not_updated",
                "detail": "No configured Mein.Libri delivery-note/order-history page could be read after login.",
            }
            for order_id, submission in pending.items()
        ]
        if args.create_issues and not meta.get("libri_document_pages_issue_reported"):
            create_issue(
                "Libri delivery-note pages could not be read",
                "The daily Libri delivery-note sync logged in but could not read any configured Mein.Libri delivery-note or order-history page. Tracking was not handed back to TikTok. No customer address data is included in this issue.",
            )
            meta["libri_document_pages_issue_reported"] = now_utc()
        save_state(state_path, state)
        write_summary(output_dir / "summary.csv", rows)
        print(f"Libri Lieferschein sync checked {len(pending)} submitted order(s); failures needing attention: {len(pending)}.")
        return 1

    rows: list[dict[str, str]] = []
    failures = 0
    grace_hours = env_int(env, "LIBRI_DELIVERY_NOTE_GRACE_HOURS", args.delivery_note_grace_hours)

    for order_id, submission in pending.items():
        package_id = clean(submission.get("package_id"))
        known = set(order_keys(order_id, submission))
        delivery_match = next(((url, body) for url, body in pages if page_mentions_delivery_note(url, body, order_id, submission)), None)
        if not delivery_match:
            order_match = next(((url, body) for url, body in pages if page_mentions_libri_order(url, body, order_id, submission)), None)
            note = delivery_notes.setdefault(order_id, {})
            note.update(
                {
                    "delivery_note_status": "not_found",
                    "last_checked_at": now_utc(),
                    "package_id": package_id,
                }
            )
            if order_match:
                order_url, order_body = order_match
                libri_order_number = extract_libri_order_number(order_url, order_body)
                submission.update(
                    {
                        "libri_order_status": "found",
                        "libri_order_checked_at": now_utc(),
                        "libri_order_page_hash": hashlib.sha256(order_url.encode("utf-8")).hexdigest()[:16],
                    }
                )
                if libri_order_number:
                    submission["libri_order_number"] = libri_order_number
                detail = "Libri order history contains the order, but no matching delivery-note page was found yet."
            else:
                submission.update({"libri_order_status": "not_found", "libri_order_checked_at": now_utc()})
                detail = "No matching Libri delivery-note page or order-history detail page was found yet."

            age_hours = submission_age_hours(submission)
            if age_hours is None or age_hours >= grace_hours:
                note["delivery_note_status"] = "missing_overdue"
                detail = overdue_detail(submission, grace_hours)
                if order_match:
                    detail += " The Libri order history match was found."
                if args.create_issues and not note.get("delivery_note_missing_issue_reported"):
                    create_issue(
                        f"Libri delivery note missing after order submission ({order_id})",
                        (
                            "A TikTok order is recorded as submitted to Libri, but the daily sync could not find a matching "
                            f"Libri delivery note after the configured {grace_hours}-hour grace period. Tracking was not handed "
                            "back to TikTok. No customer address data is included in this issue. Check the uploaded "
                            "`libri-lieferschein-sync-*` artifact and `.automation/libri_order_state.json`."
                        ),
                    )
                    note["delivery_note_missing_issue_reported"] = now_utc()
                failures += 1
            rows.append(
                {
                    "order_id": order_id,
                    "package_id": package_id,
                    "delivery_note_status": note["delivery_note_status"],
                    "tracking_status": "not_checked",
                    "tiktok_status": "not_updated",
                    "detail": detail,
                }
            )
            continue

        url, body = delivery_match
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
