#!/usr/bin/env python3
"""Automate complete Libri order submission from TikTok order data.

Workflow:
1. Add prepared order EANs to Libri basket
2. Fill customer data from kundenadresse.csv
3. Select "Direktversand zum Kunden" (Direct shipping to customer)
4. Submit final order to Libri

Usage:
  python scripts/libri_customer_submit.py --order-dir outputs/order_automation/<run>/<order-id> --env .env
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_libri_product_pages import fetch, login  # noqa: E402


ORDER_PAGE_URL = "https://mein.libri.de/Bestellen/Auftragserfassung.html"


def clean(value: object) -> str:
    return str(value or "").strip()


def first_value(source: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = clean(source.get(key))
        if value:
            return value
    return ""


def country_name(value: str) -> str:
    text = clean(value)
    mapping = {
        "DE": "Deutschland",
        "DEU": "Deutschland",
        "AT": "Österreich",
        "AUT": "Österreich",
        "CH": "Schweiz",
        "CHE": "Schweiz",
    }
    return mapping.get(text.upper(), text or "Deutschland")


def infer_city(*values: str) -> str:
    combined = " ".join(clean(value) for value in values if clean(value))
    if "Hamburg" in combined:
        return "Hamburg"
    if "Berlin" in combined:
        return "Berlin"
    return ""


def read_single_csv_row(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    return rows[0] if rows else {}


def read_order_dir(order_dir: Path) -> tuple[list[str], str, dict[str, str]]:
    """Read order EANs, reference, and customer data from order directory."""
    order_json = order_dir / "tiktok_order.json"
    import_csv = order_dir / "libri_kundenbestellung_import.csv"
    address_csv = order_dir / "kundenadresse.csv"

    if not order_json.exists():
        raise SystemExit(f"Missing {order_json}")
    if not import_csv.exists():
        raise SystemExit(f"Missing {import_csv}")
    if not address_csv.exists():
        raise SystemExit(f"Missing {address_csv}")

    order = json.loads(order_json.read_text(encoding="utf-8"))
    order_address = order.get("address") if isinstance(order.get("address"), dict) else {}
    reference = clean(order.get("buyer_username") or order_address.get("name") or order.get("order_id"))
    reference = (reference + "; tiktokshop")[:80] if reference else "tiktokshop"

    # Read EANs
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

    # Read customer address. The generated kundenadresse.csv uses English, lowercase headers and comma delimiters;
    # older manual files may use German headers and semicolon delimiters.
    row = read_single_csv_row(address_csv)
    full_address = first_value(row, "full_address", "Full Address", "Adresse") or clean(order_address.get("full_address"))
    district = first_value(row, "district", "District") or clean(order_address.get("district"))
    state = first_value(row, "state", "State", "Bundesland") or clean(order_address.get("state"))
    city = (
        first_value(row, "city", "Ort", "Stadt", "City")
        or clean(order_address.get("city"))
        or infer_city(full_address, district, state)
    )

    customer_data: dict[str, str] = {
        "name": first_value(row, "name", "Name", "Nachname, Vorname") or clean(order_address.get("name")),
        "firma": first_value(row, "firma", "Firma"),
        "strasse": (
            first_value(row, "street", "Straße", "Strasse", "Straße, Nr.", "Address Line 1")
            or clean(order_address.get("street"))
            or full_address
        ),
        "plz": first_value(row, "zipcode", "zip", "PLZ", "Postal Code") or clean(order_address.get("zipcode")),
        "ort": city,
        "country": country_name(first_value(row, "country", "Country", "Land") or clean(order_address.get("country"))),
    }

    missing = [label for label, key in [("Name", "name"), ("Straße", "strasse"), ("PLZ", "plz"), ("Ort", "ort")] if not customer_data.get(key)]
    if missing:
        raise SystemExit("Missing customer address fields in kundenadresse.csv/tiktok_order.json: " + ", ".join(missing))

    return eans, reference, customer_data


def csrf_token(page_html: str) -> str:
    match = re.search(r'name="cmsauthenticitytoken"\s+value="([^"]+)"', page_html)
    if not match:
        raise SystemExit("Could not find Libri cmsauthenticitytoken.")
    return html.unescape(match.group(1))


def basket_is_empty(page_html: str) -> bool:
    return "Es befinden sich keine Artikel im Warenkorb" in page_html


def add_eans_to_basket(opener, eans: list[str], output_dir: Path) -> str:
    """Add EANs to basket and return basket HTML."""
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
    """Extract item ID -> quantity mapping from basket HTML."""
    decoded = html.unescape(page_html)
    items: dict[str, str] = {}
    pattern = re.compile(r'name="item\[([^\]]+)\]\[quantity\]"[^>]*value="([^"]*)"', re.IGNORECASE)
    for item_id, quantity in pattern.findall(decoded):
        items[item_id] = quantity or "1"
    return items


def post_customer_checkout_step(
    opener, basket_html: str, reference: str, output_dir: Path
) -> tuple[str, dict[str, str]]:
    """Post checkout and reach customer data step. Return (response_html, item_quantities)."""
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
    (output_dir / "libri_customer_step2.html").write_text(response_html, encoding="utf-8")
    return response_html, item_quantities


def fill_customer_data_and_submit(
    opener, step2_html: str, customer_data: dict[str, str], item_quantities: dict[str, str], output_dir: Path
) -> bool:
    """Fill customer data form and continue."""
    decoded = html.unescape(step2_html)
    token = csrf_token(decoded)

    payload: dict[str, str] = {
        "cmsauthenticitytoken": token,
        "module_fnc[secondary]": "processStep",
        "data[shipping-type]": "drop",
        "data[customer-drop][name]": customer_data["name"],
        "data[customer-drop][company]": customer_data["firma"],
        "data[customer-drop][address]": customer_data["strasse"],
        "data[customer-drop][zip]": customer_data["plz"],
        "data[customer-drop][city]": customer_data["ort"],
        "data[customer-drop][country]": "1",
    }

    print("Submitting Libri customer data.")

    try:
        _, response_html = fetch(opener, ORDER_PAGE_URL, payload)
        (output_dir / "libri_submit_response.html").write_text(response_html, encoding="utf-8")

        if (
            "vielen Dank für Ihre Bestellung" in response_html
            or "Auftragsbestätigung" in response_html
            or "Bestellung erfolgreich" in response_html
        ):
            print("✓ Order successfully submitted to Libri!")
            return True
        else:
            print("⚠ Response received but success not confirmed. Check libri_submit_response.html")
            return False
    except Exception as e:
        print(f"✗ Error submitting order: {e}")
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automate complete Libri order submission from TikTok order.")
    parser.add_argument("--order-dir", required=True, help="outputs/order_automation/<run>/<order-id>")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--allow-existing-basket", action="store_true", help="Allow non-empty basket")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    order_dir = Path(args.order_dir)
    output_dir = order_dir / "libri_submission"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading order from {order_dir}")
    eans, reference, customer_data = read_order_dir(order_dir)

    print(f"Logging in to Libri...")
    opener = login(Path(args.env))

    _, page_html = fetch(opener, ORDER_PAGE_URL)
    (output_dir / "libri_initial_basket.html").write_text(page_html, encoding="utf-8")

    if not args.allow_existing_basket and not basket_is_empty(page_html):
        raise SystemExit(
            "Libri basket is not empty. Clear it manually or rerun with --allow-existing-basket after checking it."
        )

    print(f"Adding {len(eans)} items to basket...")
    basket_html = add_eans_to_basket(opener, eans, output_dir)

    print(f"Moving to checkout with reference: {reference}")
    step2_html, item_quantities = post_customer_checkout_step(opener, basket_html, reference, output_dir)

    print(f"Filling customer data and submitting order...")
    success = fill_customer_data_and_submit(opener, step2_html, customer_data, item_quantities, output_dir)

    if success:
        print(f"Order submission completed. See {output_dir} for details.")
        return 0
    else:
        print(f"Order submission may have failed. Review {output_dir}/libri_submit_response.html")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
