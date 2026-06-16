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
    reference = clean(order.get("buyer_username") or (order.get("address") or {}).get("name") or order.get("order_id"))
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

    # Read customer address
    customer_data: dict[str, str] = {}
    with address_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
        if rows:
            row = rows[0]
            customer_data = {
                "name": clean(row.get("Name") or row.get("Nachname, Vorname") or ""),
                "firma": clean(row.get("Firma") or ""),
                "strasse": clean(row.get("Straße") or row.get("Straße, Nr.") or ""),
                "plz": clean(row.get("PLZ") or ""),
                "ort": clean(row.get("Ort") or row.get("Stadt") or ""),
                "country": clean(row.get("Country") or row.get("Land") or "Deutschland"),
            }

    if not customer_data.get("name"):
        raise SystemExit("Missing customer name in kundenadresse.csv")

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
    """Fill customer data form, select direct shipping, and submit order."""
    decoded = html.unescape(step2_html)
    token = csrf_token(decoded)

    # Build payload with customer data
    payload: dict[str, str] = {
        "cmsauthenticitytoken": token,
        # Select "Direktversand zum Kunden" (direct shipping to customer)
        "data[addressSelection]": "shippingAddressSelection",
        # Customer data fields (based on form field names from screenshots)
        "data[shippingAddress][name]": customer_data["name"],
        "data[shippingAddress][company]": customer_data["firma"],
        "data[shippingAddress][street]": customer_data["strasse"],
        "data[shippingAddress][zip]": customer_data["plz"],
        "data[shippingAddress][city]": customer_data["ort"],
        "data[shippingAddress][country]": customer_data["country"],
    }

    # Add item quantities
    for item_id, quantity in item_quantities.items():
        payload[f"data[orderItems][{item_id}][quantity]"] = quantity

    # Add button to submit
    payload["module_fnc[primary]"] = "submitOrder"

    print("Submitting order to Libri with customer data:")
    print(f"  Name: {customer_data['name']}")
    print(f"  Address: {customer_data['strasse']}, {customer_data['plz']} {customer_data['ort']}")
    print(f"  Country: {customer_data['country']}")

    try:
        _, response_html = fetch(opener, ORDER_PAGE_URL, payload)
        (output_dir / "libri_submit_response.html").write_text(response_html, encoding="utf-8")

        # Check for success indicators
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
