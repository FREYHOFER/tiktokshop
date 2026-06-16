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


def login(env_path: Path):
    env = load_env_file(env_path)
    customer_number, username, password = required_env(env)

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    _, login_html = fetch(opener, LOGIN_URL)
    payload = extract_login_payload(login_html, customer_number, username, password)
    final_url, result_html = fetch(opener, LOGIN_URL, payload)

    if "Login.html" in final_url and "Logout" not in result_html:
        raise SystemExit("Libri login failed or stayed on login page. Check .env values.")
    return opener


def save_product_pages(opener, isbns: list[str], output_dir: Path) -> list[tuple[str, str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, str, str]] = []
    for isbn in isbns:
        path = output_dir / f"{isbn}.html"
        if path.exists() and path.stat().st_size > 0:
            results.append((isbn, "exists", str(path)))
            continue
        url = PRODUCT_URL.format(ean=isbn)
        final_url, body = fetch(opener, url)
        if "Login.html" in final_url or "<title>Mein.Libri - Login</title>" in body:
            results.append((isbn, "failed", "redirected_to_login"))
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    isbns = read_isbns(args)
    if not isbns:
        raise SystemExit("No ISBN/EAN values found.")
    opener = login(Path(args.env))
    results = save_product_pages(opener, isbns, Path(args.output_dir))
    for isbn, status, detail in results:
        print(f"{isbn}: {status} - {detail}")
    return 0 if all(status in {"saved", "exists"} for _, status, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
