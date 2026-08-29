#!/usr/bin/env python3
"""Automate complete Libri order submission from TikTok order data.

Workflow:
1. Check a persistent local state file so an order cannot be submitted twice
2. Add prepared order EANs to Libri basket
3. Fill customer data from kundenadresse.csv
4. Select "Direktversand zum Kunden" (Direct shipping to customer)
5. Validate the Libri confirmation page
6. Submit the final confirmation page to Libri
7. Record the successful submission in the persistent state file

Usage:
  python scripts/libri_customer_submit.py --order-dir outputs/order_automation/<run>/<order-id> --env .env
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_libri_product_pages import fetch, login  # noqa: E402


ORDER_PAGE_URL = "https://mein.libri.de/Bestellen/Auftragserfassung.html"
DEFAULT_STATE_PATH = Path(".automation") / "libri_order_state.json"


class FormParser(HTMLParser):
    """Small stdlib-only form parser for Libri confirmation pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[dict[str, object]] = []
        self._current: dict[str, object] | None = None
        self._select_name = ""
        self._select_value = ""
        self._select_has_selected = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        if tag == "form":
            self._current = {
                "method": attrs_dict.get("method", "post"),
                "action": attrs_dict.get("action", "?"),
                "fields": {},
            }
            return
        if self._current is None:
            return

        fields = self._current["fields"]
        assert isinstance(fields, dict)

        if tag == "input":
            name = attrs_dict.get("name", "")
            if not name:
                return
            input_type = attrs_dict.get("type", "text").lower()
            if input_type in {"submit", "button", "image", "file", "reset"}:
                return
            if input_type in {"checkbox", "radio"} and "checked" not in attrs_dict:
                return
            fields[name] = attrs_dict.get("value", "")
        elif tag == "textarea":
            name = attrs_dict.get("name", "")
            if name:
                fields.setdefault(name, "")
        elif tag == "select":
            self._select_name = attrs_dict.get("name", "")
            self._select_value = ""
            self._select_has_selected = False
        elif tag == "option" and self._select_name:
            value = attrs_dict.get("value", "")
            if "selected" in attrs_dict or not self._select_has_selected:
                self._select_value = value
                self._select_has_selected = "selected" in attrs_dict

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._current is not None:
            self.forms.append(self._current)
            self._current = None
        elif tag == "select" and self._current is not None and self._select_name:
            fields = self._current["fields"]
            assert isinstance(fields, dict)
            fields.setdefault(self._select_name, self._select_value)
            self._select_name = ""
            self._select_value = ""
            self._select_has_selected = False


def clean(value: object) -> str:
    return str(value or "").strip()


def normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", clean(value)).casefold()


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


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


def order_identity(order_dir: Path) -> tuple[str, str]:
    order_json = order_dir / "tiktok_order.json"
    if not order_json.exists():
        return "", ""
    try:
        order = json.loads(order_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "", ""
    order_id = clean(order.get("order_id") or order.get("id"))
    package_id = clean(order.get("package_id"))
    return order_id, package_id


def state_already_submitted(state: dict, order_id: str) -> bool:
    if not order_id:
        return False
    entry = state.get("libri_submissions", {}).get(order_id, {})
    return isinstance(entry, dict) and entry.get("status") == "submitted"


def mark_submitted(state_path: Path, order_dir: Path, eans: list[str]) -> None:
    order_id, package_id = order_identity(order_dir)
    if not order_id:
        print("No TikTok order_id found; Libri submission state was not updated.")
        return
    state = load_state(state_path)
    submissions = state.setdefault("libri_submissions", {})
    submissions[order_id] = {
        "status": "submitted",
        "submitted_at": now_utc(),
        "package_id": package_id,
        "eans": list(dict.fromkeys(eans)),
        "source": "libri_customer_submit.py",
    }
    save_state(state_path, state)
    print(f"Recorded Libri submission state for TikTok order {order_id}.")


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
    reference = clean(order.get("order_id") or order.get("buyer_username") or order_address.get("name"))
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


def basket_article_numbers(page_html: str) -> list[str]:
    return re.findall(r"\b97[89]\d{10}\b", html.unescape(page_html))


def basket_matches_expected(page_html: str, eans: list[str]) -> bool:
    found = Counter(basket_article_numbers(page_html))
    expected = Counter(eans)
    return bool(found) and found == expected


def add_eans_to_basket(opener, eans: list[str], output_dir: Path) -> str:
    """Add EANs to basket and return basket HTML."""
    _, page_html = fetch(opener, ORDER_PAGE_URL)
    if not basket_is_empty(page_html):
        if basket_matches_expected(page_html, eans):
            (output_dir / "libri_add_to_basket_response.html").write_text(page_html, encoding="utf-8")
            return page_html
        raise SystemExit("Libri basket is not empty and does not match this TikTok order.")
    payload = {
        "module_fnc[primary]": "AddEanListToBasketFromTextField",
        "eanList": "\n".join(eans),
        "cmsauthenticitytoken": csrf_token(page_html),
    }
    _, response_html = fetch(opener, ORDER_PAGE_URL, payload)
    (output_dir / "libri_add_to_basket_response.html").write_text(response_html, encoding="utf-8")
    return response_html


def ensure_eans_in_basket(opener, page_html: str, eans: list[str], output_dir: Path) -> str:
    requested = Counter(eans)
    current = {item["ean"]: int(item["quantity"] or "1") for item in parse_basket_items(page_html)}
    present = {ean: current[ean] for ean in requested if ean in current}
    wrong_quantity = {ean: (present[ean], requested[ean]) for ean in present if present[ean] != requested[ean]}
    if wrong_quantity:
        detail = ", ".join(f"{ean}: basket {actual}, order {expected}" for ean, (actual, expected) in wrong_quantity.items())
        raise SystemExit("Target EAN already exists in Libri basket with a different quantity: " + detail)
    if len(present) == len(requested):
        return page_html
    missing: list[str] = []
    for ean, quantity in requested.items():
        if ean not in present:
            missing.extend([ean] * quantity)
    return add_eans_to_basket(opener, missing, output_dir)


def parse_basket_items(page_html: str) -> list[dict[str, str]]:
    """Extract basket row IDs, EANs, and quantities."""
    decoded = html.unescape(page_html)
    items: list[dict[str, str]] = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", decoded, re.IGNORECASE | re.DOTALL):
        ean_match = re.search(r'class="column-article_number"[^>]*>\s*(\d{13})\s*<', row, re.IGNORECASE)
        quantity_match = re.search(
            r'name="item\[([^\]]+)\]\[quantity\]"[^>]*value="([^"]*)"',
            row,
            re.IGNORECASE,
        )
        if ean_match and quantity_match:
            items.append(
                {
                    "item_id": quantity_match.group(1),
                    "ean": ean_match.group(1),
                    "quantity": quantity_match.group(2) or "1",
                }
            )
    return items


def select_order_items(page_html: str, eans: list[str]) -> dict[str, str]:
    requested = Counter(eans)
    selected: dict[str, str] = {}
    found: set[str] = set()
    for item in parse_basket_items(page_html):
        ean = item["ean"]
        if ean in requested:
            selected[item["item_id"]] = str(requested[ean])
            found.add(ean)
    missing = sorted(set(requested) - found)
    if missing:
        raise SystemExit("Expected EANs not found in Libri basket after adding: " + ", ".join(missing))
    return selected


def post_customer_checkout_step(
    opener, basket_html: str, eans: list[str], reference: str, output_dir: Path
) -> tuple[str, str, dict[str, str]]:
    """Post checkout and reach customer data step.

    Returns the step URL, its HTML, and the selected item quantities.
    """
    decoded = html.unescape(basket_html)
    token = csrf_token(decoded)
    item_quantities = select_order_items(decoded, eans)
    if not item_quantities:
        raise SystemExit("No basket item quantity fields found after adding EANs.")

    payload: dict[str, str] = {
        "module_fnc[primary]": "checkoutOrUpdate",
        "checkout": "1",
        "cmsauthenticitytoken": token,
    }
    for item in parse_basket_items(decoded):
        item_id = item["item_id"]
        payload[f"item[{item_id}][quantity]"] = item["quantity"]
    for item_id in item_quantities:
        payload[f"item[{item_id}][order]"] = "1"
        payload[f"data[confirm][orderReference][positionReference][{item_id}]"] = reference

    step2_url, response_html = fetch(opener, ORDER_PAGE_URL, payload)
    (output_dir / "libri_customer_step2.html").write_text(response_html, encoding="utf-8")
    (output_dir / "libri_customer_step2_url.txt").write_text(step2_url + "\n", encoding="utf-8")
    return step2_url, response_html, item_quantities


def page_has_success_text(page_html: str) -> bool:
    text = normalized_text(html.unescape(page_html))
    success_markers = [
        "vielen dank für ihre bestellung",
        "auftragsbestätigung",
        "bestellung erfolgreich",
        "auftrag wurde erfasst",
        "ihr auftrag wurde",
    ]
    return any(marker in text for marker in success_markers)


def validate_confirmation_page(page_html: str, eans: list[str], customer_data: dict[str, str]) -> None:
    decoded = html.unescape(page_html)
    text = normalized_text(decoded)
    if Counter(basket_article_numbers(decoded)) != Counter(eans):
        raise SystemExit("Confirmation page does not show exactly the expected EAN(s).")

    required_customer_values = {
        "name": customer_data["name"],
        "street": customer_data["strasse"],
        "zip": customer_data["plz"],
        "city": customer_data["ort"],
    }
    missing_labels = [
        label for label, value in required_customer_values.items() if normalized_text(value) not in text
    ]
    if missing_labels:
        raise SystemExit("Confirmation page is missing expected customer field(s): " + ", ".join(missing_labels))


def parse_forms(page_html: str) -> list[dict[str, object]]:
    parser = FormParser()
    parser.feed(html.unescape(page_html))
    return parser.forms


def choose_final_confirmation_payload(page_html: str) -> dict[str, str]:
    forms = parse_forms(page_html)
    candidates: list[dict[str, str]] = []
    for form in forms:
        fields = form.get("fields", {})
        if not isinstance(fields, dict):
            continue
        payload = {str(key): str(value) for key, value in fields.items()}
        # Do not treat the customer-data page as the final order page.
        if any(key.startswith("data[customer-drop]") or key.startswith("data[customer-pickup]") for key in payload):
            continue
        if any(key.startswith("module_fnc") or key == "cmsauthenticitytoken" for key in payload):
            candidates.append(payload)

    if not candidates:
        raise SystemExit("Could not find a final confirmation form to submit.")
    if len(candidates) > 1:
        candidates.sort(key=lambda payload: ("cmsauthenticitytoken" in payload, len(payload)), reverse=True)
    return candidates[0]


def country_value(country: str) -> str:
    normalized = clean(country).casefold()
    values = {
        "de": "1",
        "deutschland": "1",
        "germany": "1",
        "at": "26",
        "österreich": "26",
        "austria": "26",
        "ch": "2",
        "schweiz": "2",
        "switzerland": "2",
    }
    if normalized not in values:
        raise SystemExit(f"Unsupported Libri destination country: {country}")
    return values[normalized]


def post_customer_data(
    opener, step2_url: str, step2_html: str, customer_data: dict[str, str], output_dir: Path
) -> tuple[str, str]:
    """Fill the verified Libri direct-shipping fields and open the review step."""
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
        "data[customer-drop][country]": country_value(customer_data["country"]),
        "data[customer-drop][parcelDelivery]": "1",
    }
    print("Submitting Libri customer data.")
    review_url, review_html = fetch(opener, step2_url, payload)
    (output_dir / "libri_review_step3.html").write_text(review_html, encoding="utf-8")
    (output_dir / "libri_confirm_order.html").write_text(review_html, encoding="utf-8")
    (output_dir / "libri_confirm_order_url.txt").write_text(review_url + "\n", encoding="utf-8")
    return review_url, review_html

def visible_text(page_html: str) -> str:
    decoded = html.unescape(page_html)
    decoded = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", decoded)
    decoded = re.sub(r"(?s)<[^>]+>", " ", decoded)
    return re.sub(r"\s+", " ", decoded).strip()


def verify_review(
    review_html: str, eans: list[str], customer_data: dict[str, str], order_dir: Path
) -> str:
    validate_confirmation_page(review_html, eans, customer_data)
    text = visible_text(review_html)
    required = [customer_data["name"], customer_data["strasse"], customer_data["plz"], customer_data["ort"]]
    missing = [value for value in required if value and value.casefold() not in text.casefold()]
    if "Kundenbestellung überprüfen" not in text:
        missing.append("Libri review step")
    order = json.loads((order_dir / "tiktok_order.json").read_text(encoding="utf-8"))
    titles = [clean(line.get("product_name")) for line in order.get("lines", []) if clean(line.get("ean")) in set(eans)]
    title_stems = [title.split(" - ", 1)[0] for title in titles]
    missing.extend(title for title in title_stems if title and title.casefold() not in text.casefold())
    expected_eans = set(eans)
    reviewed_eans = set(re.findall(r"(?<!\d)97[89]\d{10}(?!\d)", text))
    if reviewed_eans != expected_eans:
        missing.append(
            "reviewed EANs " + ",".join(sorted(reviewed_eans)) + " (expected " + ",".join(sorted(expected_eans)) + ")"
        )
    if missing:
        raise SystemExit("Libri review could not be verified; missing: " + ", ".join(missing))
    return text


def final_form_payload(review_html: str) -> dict[str, str]:
    decoded = html.unescape(review_html)
    form_match = re.search(r'(?is)<form\b[^>]*id="checkoutForm"[^>]*>(.*?)</form>', decoded)
    if not form_match:
        raise SystemExit("Could not find Libri checkout confirmation form.")
    form = form_match.group(1)
    payload: dict[str, str] = {}
    for tag in re.findall(r"(?is)<input\b[^>]*>", form):
        name_match = re.search(r'\bname="([^"]+)"', tag, re.IGNORECASE)
        if not name_match:
            continue
        input_type = (re.search(r'\btype="([^"]+)"', tag, re.IGNORECASE) or [None, "text"])[1].casefold()
        if input_type in {"checkbox", "radio"} and not re.search(r"\bchecked\b", tag, re.IGNORECASE):
            continue
        value_match = re.search(r'\bvalue="([^"]*)"', tag, re.IGNORECASE)
        payload[name_match.group(1)] = value_match.group(1) if value_match else ""
    if "cmsauthenticitytoken" not in payload:
        raise SystemExit("Could not find Libri confirmation token.")
    payload["module_fnc[secondary]"] = "processStep"
    return payload


def submit_reviewed_order(opener, review_url: str, review_html: str, output_dir: Path) -> bool:
    try:
        payload = final_form_payload(review_html)
    except SystemExit:
        # Preserve the more tolerant upstream parser for harmless Libri markup variations.
        payload = choose_final_confirmation_payload(review_html)
    print("Submitting final Libri confirmation.")
    _, response_html = fetch(opener, review_url, payload)
    (output_dir / "libri_submit_response.html").write_text(response_html, encoding="utf-8")
    if page_has_success_text(response_html):
        print("✓ Order successfully submitted to Libri!")
        return True
    print("⚠ Final response received but success was not confirmed. Check libri_submit_response.html")
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automate complete Libri order submission from TikTok order.")
    parser.add_argument("--order-dir", required=True, help="outputs/order_automation/<run>/<order-id>")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="Persistent JSON state for submitted Libri orders.")
    parser.add_argument("--allow-existing-basket", action="store_true", help="Allow non-empty basket")
    submission_mode = parser.add_mutually_exclusive_group()
    submission_mode.add_argument(
        "--submit",
        action="store_true",
        help="Submit after verifying the Libri review step (the legacy default).",
    )
    submission_mode.add_argument(
        "--review-only",
        action="store_true",
        help="Prepare and verify the Libri review step without placing the order.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    order_dir = Path(args.order_dir)
    state_path = Path(args.state)
    output_dir = order_dir / "libri_submission"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading order from {order_dir}")
    eans, reference, customer_data = read_order_dir(order_dir)
    order_id, _ = order_identity(order_dir)
    state = load_state(state_path)
    if state_already_submitted(state, order_id):
        print(f"TikTok order {order_id} is already recorded as submitted to Libri. Skipping.")
        return 0

    print(f"Logging in to Libri...")
    opener = login(Path(args.env))

    _, page_html = fetch(opener, ORDER_PAGE_URL)
    (output_dir / "libri_initial_basket.html").write_text(page_html, encoding="utf-8")

    if not basket_is_empty(page_html) and not basket_matches_expected(page_html, eans):
        raise SystemExit("Libri basket is not empty and does not match this TikTok order.")

    print(f"Ensuring {len(eans)} items are in basket...")
    basket_html = ensure_eans_in_basket(opener, page_html, eans, output_dir)

    print(f"Moving to checkout with reference: {reference}")
    step2_url, step2_html, item_quantities = post_customer_checkout_step(
        opener, basket_html, eans, reference, output_dir
    )

    print("Filling customer data and opening Libri review step...")
    review_url, review_html = post_customer_data(opener, step2_url, step2_html, customer_data, output_dir)
    review_text = verify_review(review_html, eans, customer_data, order_dir)
    (output_dir / "libri_review_summary.txt").write_text(review_text, encoding="utf-8")

    should_submit = args.submit or not args.review_only
    if not should_submit:
        print(f"Review prepared and verified. No order submitted. See {output_dir}.")
        return 0

    print("Submitting the verified order to Libri...")
    if submit_reviewed_order(opener, review_url, review_html, output_dir):
        mark_submitted(state_path, order_dir, eans)
        print(f"Order submission completed. See {output_dir} for details.")
        return 0
    print(f"Order submission response was not confirmed. Review {output_dir}/libri_submit_response.html")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
