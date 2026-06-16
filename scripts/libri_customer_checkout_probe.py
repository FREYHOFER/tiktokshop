#!/usr/bin/env python3
"""Open a prepared TikTok order in Mein.Libri customer checkout step 2.

This script is intentionally a probe:
- It can add one prepared order to the Libri basket.
- It clicks/posts "Kundenbestellung" to reach the customer-data step.
- It saves the resulting HTML and field names.
- It does not submit the final Libri order.

Run only when the Libri basket is empty or pass --allow-existing-basket.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_libri_product_pages import fetch, login  # noqa: E402


ORDER_PAGE_URL = "https://mein.libri.de/Bestellen/Auftragserfassung.html"


def clean(value: object) -> str:
    return str(value or "").strip()


def read_order_dir(order_dir: Path) -> tuple[list[str], str]:
    order_json = order_dir / "tiktok_order.json"
    import_csv = order_dir / "libri_kundenbestellung_import.csv"
    if not order_json.exists():
        raise SystemExit(f"Missing {order_json}")
    if not import_csv.exists():
        raise SystemExit(f"Missing {import_csv}")

    order = json.loads(order_json.read_text(encoding="utf-8"))
    reference = clean(order.get("buyer_username") or (order.get("address") or {}).get("name") or order.get("order_id"))
    reference = (reference + "; tiktokshop")[:80] if reference else "tiktokshop"

    eans: list[str] = []
    with import_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            ean = clean(row.get("Artikel Nr"))
            qty_text = clean(row.get("Menge")) or "1"
            try:
                qty = max(int(float(qty_text.replace(",", "."))), 1)
            except ValueError:
                qty = 1
            eans.extend([ean] * qty)
    eans = [ean for ean in eans if ean]
    if not eans:
        raise SystemExit("No EAN values found in Libri import CSV.")
    return eans, reference


def csrf_token(page_html: str) -> str:
    match = re.search(r'name="cmsauthenticitytoken"\s+value="([^"]+)"', page_html)
    if not match:
        raise SystemExit("Could not find Libri cmsauthenticitytoken.")
    return html.unescape(match.group(1))


def basket_is_empty(page_html: str) -> bool:
    return "Es befinden sich keine Artikel im Warenkorb" in page_html


def add_eans_to_basket(opener, eans: list[str], output_dir: Path) -> str:
    _, page_html = fetch(opener, ORDER_PAGE_URL)
    payload = {
        "module_fnc[primary]": "AddEanListToBasketFromTextField",
        "eanList": "\n".join(eans),
        "cmsauthenticitytoken": csrf_token(page_html),
    }
    _, response_html = fetch(opener, ORDER_PAGE_URL, payload)
    (output_dir / "libri_add_to_basket_response.html").write_text(response_html, encoding="utf-8")
    return response_html


def parse_basket_items(page_html: str) -> dict[str, str]:
    decoded = html.unescape(page_html)
    items: dict[str, str] = {}
    pattern = re.compile(r'name="item\[([^\]]+)\]\[quantity\]"[^>]*value="([^"]*)"', re.IGNORECASE)
    for item_id, quantity in pattern.findall(decoded):
        items[item_id] = quantity or "1"
    return items


def post_customer_checkout_step(opener, basket_html: str, reference: str, output_dir: Path) -> Path:
    decoded = html.unescape(basket_html)
    token = csrf_token(decoded)
    item_quantities = parse_basket_items(decoded)
    if not item_quantities:
        raise SystemExit("No basket item quantity fields found after adding EANs.")

    payload: dict[str, str] = {
        "module_fnc[primary]": "checkoutOrUpdate",
        "checkout": "1",
        "cmsauthenticitytoken": token,
    }
    for item_id, quantity in item_quantities.items():
        payload[f"item[{item_id}][quantity]"] = quantity
        payload[f"item[{item_id}][order]"] = "1"
        payload[f"data[confirm][orderReference][positionReference][{item_id}]"] = reference

    _, response_html = fetch(opener, ORDER_PAGE_URL, payload)
    step2_path = output_dir / "libri_customer_step2.html"
    step2_path.write_text(response_html, encoding="utf-8")
    write_field_report(output_dir / "libri_customer_step2_fields.txt", response_html)
    return step2_path


def write_field_report(path: Path, page_html: str) -> None:
    decoded = html.unescape(page_html)
    names = sorted(set(re.findall(r'\bname="([^"]+)"', decoded)))
    ids = sorted(set(re.findall(r'\bid="([^"]+)"', decoded)))
    buttons = sorted(set(re.findall(r'<button[^>]*name="([^"]+)"[^>]*value="([^"]*)"', decoded, re.IGNORECASE)))
    lines = ["# Field names", *names, "", "# IDs", *ids, "", "# Button name/value", *[f"{name}={value}" for name, value in buttons]]
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Mein.Libri customer checkout step 2 for one prepared order.")
    parser.add_argument("--order-dir", required=True, help="outputs/order_automation/<run>/<order-id>")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--allow-existing-basket", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    order_dir = Path(args.order_dir)
    output_dir = order_dir / "libri_checkout_probe"
    output_dir.mkdir(parents=True, exist_ok=True)
    eans, reference = read_order_dir(order_dir)
    opener = login(Path(args.env))
    _, page_html = fetch(opener, ORDER_PAGE_URL)
    (output_dir / "libri_initial_basket.html").write_text(page_html, encoding="utf-8")
    if not args.allow_existing_basket and not basket_is_empty(page_html):
        raise SystemExit(
            "Libri basket is not empty. Clear it manually or rerun with --allow-existing-basket after checking it."
        )
    basket_html = add_eans_to_basket(opener, eans, output_dir)
    step2_path = post_customer_checkout_step(opener, basket_html, reference, output_dir)
    print(f"Saved customer checkout step 2: {step2_path.resolve()}")
    print("No final Libri order was submitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
