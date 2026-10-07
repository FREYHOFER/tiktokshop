#!/usr/bin/env python3
"""Fetch Mein.Libri product detail pages after logging in.

Credentials are read from .env:
- LIBRI_CUSTOMER_NUMBER
- LIBRI_USERNAME
- LIBRI_PASSWORD

The script saves product pages as HTML. It does not print secrets.
"""

from __future__ import annotations

import argparse
import csv
import html
import http.cookiejar
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


LOGIN_URL = "https://mein.libri.de/Login.html"
PRODUCT_URL = "https://mein.libri.de/produkt/{ean}/?source=bestseller"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def required_env(env: dict[str, str]) -> tuple[str, str, str]:
    customer_number = env.get("LIBRI_CUSTOMER_NUMBER", "")
    username = env.get("LIBRI_USERNAME", "")
    password = env.get("LIBRI_PASSWORD", "")
    missing = [
        key
        for key, value in [
            ("LIBRI_CUSTOMER_NUMBER", customer_number),
            ("LIBRI_USERNAME", username),
            ("LIBRI_PASSWORD", password),
        ]
        if not value
    ]
    if missing:
        raise SystemExit("Missing values in .env: " + ", ".join(missing))
    return customer_number, username, password


def read_isbns(args: argparse.Namespace) -> list[str]:
    isbns: list[str] = []
    isbns.extend(args.isbn)

    for csv_path in args.isbn_csv:
        path = Path(csv_path)
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                value = row.get("ean") or row.get("isbn") or row.get("gtin_code") or ""
                if value:
                    isbns.append(value)

    cleaned = []
    for value in isbns:
        digits = re.sub(r"\D", "", value)
        if len(digits) in {10, 13}:
            cleaned.append(digits)
    return list(dict.fromkeys(cleaned))[: args.limit if args.limit else None]


def fetch(opener, url: str, data: dict[str, str] | None = None) -> tuple[str, str]:
    encoded = urllib.parse.urlencode(data).encode("utf-8") if data else None
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with opener.open(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.geturl(), body


def extract_login_payload(login_html: str, customer_number: str, username: str, password: str) -> dict[str, str]:
    payload = {
        "module_fnc[primary]": "Login",
        "sSuccessURL": "",
        "sFailureURL": "",
        "sConsumer": "loginBox",
        "customerNumber": customer_number,
        "slogin": username,
        "password": password,
    }
    token_match = re.search(r'name="cmsauthenticitytoken"\s+value="([^"]+)"', login_html)
    if token_match:
        payload["cmsauthenticitytoken"] = html.unescape(token_match.group(1))
    return payload


def login(env_path: Path, retries: int = 4, retry_delay: float = 2.0):
    """Open a fresh authenticated Libri session, retrying transient rejections.

    Libri sometimes returns the login form again for otherwise valid credentials,
    especially after several sessions were opened close together. Each retry uses
    a new cookie jar. Diagnostics deliberately contain no credentials or response
    body.
    """
    env = load_env_file(env_path)
    customer_number, username, password = required_env(env)
    attempts = max(retries, 0) + 1
    last_reason = "unknown"

    for attempt in range(attempts):
        try:
            cookie_jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
            _, login_html = fetch(opener, LOGIN_URL)
            payload = extract_login_payload(login_html, customer_number, username, password)
            final_url, result_html = fetch(opener, LOGIN_URL, payload)
            stayed_on_login = "Login.html" in final_url or "<title>Mein.Libri - Login</title>" in result_html
            if not stayed_on_login or "Logout" in result_html:
                return opener
            last_reason = "login_form_returned"
        except urllib.error.HTTPError as exc:
            last_reason = f"http_{exc.code}"
        except (urllib.error.URLError, TimeoutError) as exc:
            last_reason = type(exc).__name__.lower()

        if attempt + 1 < attempts:
            delay = min(max(retry_delay, 0.0) * (2**attempt), 30.0)
            print(
                f"Libri login attempt {attempt + 1}/{attempts} failed ({last_reason}); "
                f"retrying in {delay:g}s.",
                file=sys.stderr,
            )
            if delay:
                time.sleep(delay)

    raise SystemExit(
        f"Libri login failed after {attempts} attempts ({last_reason}). "
        "Credentials are present, but Libri did not establish a session; retry later and check the account only if this persists."
    )


def save_product_pages(
    opener,
    isbns: list[str],
    output_dir: Path,
    env_path: Path,
    retries: int = 3,
    session_refresh_every: int = 20,
) -> list[tuple[str, str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, str, str]] = []
    requests_in_session = 0
    for isbn in isbns:
        path = output_dir / f"{isbn}.html"
        if path.exists() and path.stat().st_size > 0:
            results.append((isbn, "exists", str(path)))
            continue
        url = PRODUCT_URL.format(ean=isbn)
        last_error = ""
        for attempt in range(max(retries, 0) + 1):
            try:
                if session_refresh_every > 0 and requests_in_session >= session_refresh_every:
                    opener = login(env_path)
                    requests_in_session = 0
                final_url, body = fetch(opener, url)
                requests_in_session += 1
                if "Login.html" not in final_url and "<title>Mein.Libri - Login</title>" not in body:
                    break
                last_error = "redirected_to_login"
            except Exception as exc:
                last_error = str(exc)[:500]
            if attempt < max(retries, 0):
                time.sleep(min(2**attempt, 8))
                opener = login(env_path)
                requests_in_session = 0
        else:
            results.append((isbn, "failed", last_error or "fetch_failed"))
            continue
        path.write_text(body, encoding="utf-8")
        results.append((isbn, "saved", str(path)))
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Login to Mein.Libri and save product detail pages by ISBN/EAN.")
    parser.add_argument("--env", default=".env", help="Path to .env with Libri credentials.")
    parser.add_argument("--isbn", action="append", default=[], help="ISBN/EAN to fetch. Can be repeated.")
    parser.add_argument("--isbn-csv", action="append", default=[], help="CSV containing ean/isbn/gtin_code. Can be repeated.")
    parser.add_argument("--output-dir", default="libri_product_pages", help="Where to save fetched HTML pages.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max ISBN count.")
    parser.add_argument("--retries", type=int, default=3, help="Re-login and retry failed product-page requests.")
    parser.add_argument("--session-refresh-every", type=int, default=20, help="Renew the Libri session after this many requests.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    isbns = read_isbns(args)
    if not isbns:
        raise SystemExit("No ISBN/EAN values found.")
    env_path = Path(args.env)
    opener = login(env_path)
    results = save_product_pages(
        opener,
        isbns,
        Path(args.output_dir),
        env_path,
        retries=args.retries,
        session_refresh_every=args.session_refresh_every,
    )
    for isbn, status, detail in results:
        print(f"{isbn}: {status} - {detail}")
    return 0 if all(status in {"saved", "exists"} for _, status, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
