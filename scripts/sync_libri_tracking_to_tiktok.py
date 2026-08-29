#!/usr/bin/env python3
"""Sync Mein.Libri direct-shipment delivery-note tracking to TikTok Shop.

The matching is deliberately strict: delivery-note EANs and the recipient name
must identify exactly one TikTok order that is still awaiting shipment.
Writes to TikTok happen only with --live.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import io
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_libri_product_pages import fetch, load_env_file, login  # noqa: E402
from tiktok_order_automation import (  # noqa: E402
    TikTokApiError,
    TikTokShopClient,
    clean,
    normalize_api_order,
)


LIBRI_DELIVERY_NOTES_URL = "https://mein.libri.de/lieferung/lieferscheine-und-gutschriftanzeigen.html"
DHL_TRACKING_URL = "https://www.dhl.de/int-verfolgen/data/search"
DEFAULT_OUTPUT_ROOT = Path("outputs") / "libri_tracking_sync"
DELIVERY_NOTE_PAGE_LIMIT = 20


@dataclass
class DeliveryNote:
    date: str = ""
    customer_number: str = ""
    document_number: str = ""
    tracking_number: str = ""
    description: str = ""
    value: str = ""
    pdf_url: str = ""


class DeliveryNoteTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[DeliveryNote] = []
        self.in_row = False
        self.current_column = ""
        self.current: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self.in_row = True
            self.current = {}
        elif self.in_row and tag == "td":
            self.current_column = clean(attributes.get("class"))
        elif self.in_row and tag == "a" and self.current_column == "column-avis_pdf":
            self.current["pdf_url"] = html.unescape(clean(attributes.get("href")))

    def handle_data(self, data: str) -> None:
        if self.in_row and self.current_column:
            self.current[self.current_column] = self.current.get(self.current_column, "") + data

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self.current_column = ""
        elif tag == "tr" and self.in_row:
            self.in_row = False
            note = DeliveryNote(
                date=clean(self.current.get("column-date")),
                customer_number=clean(self.current.get("column-vknr")),
                document_number=clean(self.current.get("column-number")),
                tracking_number=clean(self.current.get("column-identcode")),
                description=clean(self.current.get("column-description")),
                value=clean(self.current.get("column-value")),
                pdf_url=clean(self.current.get("pdf_url")),
            )
            if note.document_number:
                self.rows.append(note)
            self.current = {}


def normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"documents": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"documents": {}}
    state.setdefault("documents", {})
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def delivery_notes_url(page: int) -> str:
    params = {
        "filter[freshSearch]": "1",
        "filter[date_interval]": "long",
        "filter[note_type]": "LIEF",
    }
    if page > 1:
        params["p"] = str(page)
    return LIBRI_DELIVERY_NOTES_URL + "?" + urllib.parse.urlencode(params)


def fetch_delivery_notes(opener) -> list[DeliveryNote]:
    rows_by_document: dict[str, DeliveryNote] = {}
    for page in range(1, DELIVERY_NOTE_PAGE_LIMIT + 1):
        try:
            final_url, body = fetch(opener, delivery_notes_url(page))
        except urllib.error.HTTPError as exc:
            if page > 1 and exc.code == 404:
                break
            raise
        if "Login.html" in final_url or "Mein.Libri - Login" in body:
            raise RuntimeError("Mein.Libri redirected to login while reading delivery notes.")
        parser = DeliveryNoteTableParser()
        parser.feed(body)
        if not parser.rows:
            break
        for note in parser.rows:
            rows_by_document.setdefault(note.document_number, note)
    return [
        note
        for note in rows_by_document.values()
        if "direktversand" in note.description.casefold() and note.tracking_number and note.pdf_url
    ]


def download_pdf(opener, note: DeliveryNote) -> bytes:
    url = urllib.parse.urljoin(LIBRI_DELIVERY_NOTES_URL, note.pdf_url)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/pdf",
            "Referer": LIBRI_DELIVERY_NOTES_URL,
            "User-Agent": "Mozilla/5.0",
        },
    )
    with opener.open(request, timeout=60) as response:
        data = response.read()
    if not data.startswith(b"%PDF-"):
        raise RuntimeError(f"Libri document {note.document_number} did not return a PDF.")
    return data


def extract_pdf_text(pdf_data: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def pdf_eans(text: str) -> set[str]:
    return set(re.findall(r"(?<!\d)97[89]\d{10}(?!\d)", text))


def order_eans(order) -> set[str]:
    return {line.ean for line in order.lines if line.ean}


def recipient_matches(pdf_text: str, recipient: str) -> bool:
    recipient_normalized = normalized_text(recipient)
    return bool(recipient_normalized and recipient_normalized in normalized_text(pdf_text))


def unique_order_match(pdf_text: str, orders: list) -> object:
    note_eans = pdf_eans(pdf_text)
    if not note_eans:
        raise RuntimeError("No ISBN/EAN was extracted from the delivery-note PDF.")
    matches = [
        order
        for order in orders
        if order_eans(order) == note_eans and recipient_matches(pdf_text, order.address.name)
    ]
    if len(matches) != 1:
        ids = [order.order_id for order in matches]
        raise RuntimeError(f"Delivery note matched {len(matches)} TikTok orders (matches: {ids}).")
    return matches[0]


def verify_dhl_tracking(tracking_number: str) -> dict:
    query = urllib.parse.urlencode({"piececode": tracking_number, "lang": "de"})
    request = urllib.request.Request(
        f"{DHL_TRACKING_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    shipments = payload.get("sendungen") or []
    shipment = next((item for item in shipments if clean(item.get("id")) == tracking_number), None)
    if not shipment or shipment.get("reasonForRejection"):
        raise RuntimeError(f"DHL did not recognize tracking number {tracking_number}.")
    details = shipment.get("sendungsdetails") or {}
    if clean(details.get("quelle")).upper() != "PAKET" or details.get("expressSendung") is True:
        raise RuntimeError(f"Tracking number {tracking_number} is not a DHL Paket shipment.")
    history = details.get("sendungsverlauf") or {}
    return {
        "carrier": "DHL Paket",
        "status": clean(history.get("status")),
        "status_time": clean(history.get("datumAktuellerStatus")),
    }


def package_detail(client: TikTokShopClient, package_id: str, shop_cipher: str) -> dict:
    response = client.request(
        "GET",
        f"/fulfillment/202309/packages/{package_id}",
        params={"shop_cipher": shop_cipher},
    )
    return response.get("data") or {}


def shipping_provider(client: TikTokShopClient, package: dict, shop_cipher: str, provider_name: str) -> dict:
    delivery_option_id = clean(package.get("delivery_option_id"))
    if not delivery_option_id:
        raise RuntimeError("TikTok package has no delivery_option_id.")
    sender_region = clean((package.get("sender_address") or {}).get("region_code")) or "DE"
    buyer_region = clean((package.get("recipient_address") or {}).get("region_code")) or "DE"
    response = client.request(
        "GET",
        f"/logistics/202309/delivery_options/{delivery_option_id}/shipping_providers",
        params={
            "shop_cipher": shop_cipher,
            "warehouse_region": sender_region,
            "buyer_region": buyer_region,
        },
    )
    providers = (response.get("data") or {}).get("shipping_providers") or []
    matches = [provider for provider in providers if clean(provider.get("name")).casefold() == provider_name.casefold()]
    if len(matches) != 1:
        available = [clean(provider.get("name")) for provider in providers]
        raise RuntimeError(f"TikTok provider {provider_name!r} not found uniquely. Available: {available}")
    return matches[0]


def fetch_awaiting_orders(client: TikTokShopClient, hours_back: int) -> list:
    raw_orders = client.search_awaiting_orders("AWAITING_SHIPMENT", page_size=50, hours_back=hours_back)
    ids = [clean(order.get("id") or order.get("order_id")) for order in raw_orders]
    details = client.get_order_details([order_id for order_id in ids if order_id])
    return [normalize_api_order(item, "tiktok_api") for item in details]


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def process_note(
    note: DeliveryNote,
    opener,
    client: TikTokShopClient,
    shop_cipher: str,
    orders: list,
    output_root: Path,
    provider_name: str,
    live: bool,
) -> dict:
    pdf_data = download_pdf(opener, note)
    pdf_path = output_root / "delivery_notes" / f"{note.document_number}.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf_data)
    pdf_text = extract_pdf_text(pdf_data)
    order = unique_order_match(pdf_text, orders)
    if not order.package_id:
        raise RuntimeError(f"TikTok order {order.order_id} has no package ID.")

    dhl = verify_dhl_tracking(note.tracking_number)
    package = package_detail(client, order.package_id, shop_cipher)
    package_recipient = clean((package.get("recipient_address") or {}).get("name"))
    if normalized_text(package_recipient) != normalized_text(order.address.name):
        raise RuntimeError("Recipient in TikTok package detail does not match the order recipient.")
    provider = shipping_provider(client, package, shop_cipher, provider_name)

    result = {
        "status": "dry_run",
        "document": asdict(note),
        "order_id": order.order_id,
        "package_id": order.package_id,
        "eans": sorted(pdf_eans(pdf_text)),
        "recipient": order.address.name,
        "provider_id": clean(provider.get("id")),
        "provider_name": clean(provider.get("name")),
        "dhl": dhl,
        "checked_at": timestamp(),
    }
    if not live:
        return result

    current_tracking = clean(package.get("last_mile_tracking_number") or package.get("tracking_number"))
    package_status = clean(package.get("package_status"))
    if current_tracking == note.tracking_number:
        result["status"] = "already_synced"
        result["synced_at"] = timestamp()
        return result
    if package_status != "TO_FULFILL":
        raise RuntimeError(
            f"TikTok package {order.package_id} is {package_status or 'unknown'}, not TO_FULFILL, and has no matching tracking."
        )

    client.request(
        "POST",
        f"/fulfillment/202309/packages/{order.package_id}/ship",
        params={"shop_cipher": shop_cipher},
        body={
            "self_shipment": {
                "tracking_number": note.tracking_number,
                "shipping_provider_id": clean(provider.get("id")),
            }
        },
    )
    after = package_detail(client, order.package_id, shop_cipher)
    result["status"] = "synced"
    result["tiktok_package_status"] = clean(after.get("package_status"))
    result["tiktok_tracking_number"] = clean(
        after.get("last_mile_tracking_number") or after.get("tracking_number") or note.tracking_number
    )
    result["synced_at"] = timestamp()
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync Libri direct-shipment tracking numbers to TikTok Shop.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--state", default=str(DEFAULT_OUTPUT_ROOT / "state.json"))
    parser.add_argument("--hours-back", type=int, default=24 * 45)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--live", action="store_true", help="Actually mark matched TikTok packages as shipped.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = Path(args.env)
    output_root = Path(args.output_root)
    state_path = Path(args.state)
    env = load_env_file(env_path)
    provider_name = clean(env.get("TIKTOK_LIBRI_SHIPPING_PROVIDER")) or "DHL Paket"
    state = load_state(state_path)
    opener = login(env_path)
    client = TikTokShopClient(env, env_path)
    shop_cipher = client.ensure_shop_cipher()
    orders = fetch_awaiting_orders(client, max(args.hours_back, 1))
    notes = fetch_delivery_notes(opener)
    pending = [
        note
        for note in notes
        if (state["documents"].get(note.document_number) or {}).get("status") not in {"synced", "already_synced"}
    ]
    if args.limit > 0:
        pending = pending[: args.limit]

    if not pending:
        print("No unsynced Libri direct-shipment delivery notes found.")
        return 0

    errors = 0
    for note in pending:
        try:
            result = process_note(
                note,
                opener,
                client,
                shop_cipher,
                orders,
                output_root,
                provider_name,
                args.live,
            )
            print(
                f"{note.document_number}: {result['status']} | TikTok {result['order_id']} | "
                f"{note.tracking_number} | {result['provider_name']}"
            )
            if args.live:
                state["documents"][note.document_number] = result
                save_state(state_path, state)
        except (RuntimeError, TikTokApiError, OSError, ValueError) as exc:
            errors += 1
            print(f"{note.document_number}: ERROR - {exc}", file=sys.stderr)
            if args.live:
                previous = state["documents"].get(note.document_number) or {}
                state["documents"][note.document_number] = {
                    "status": "error",
                    "document": asdict(note),
                    "error": str(exc),
                    "attempts": int(previous.get("attempts") or 0) + 1,
                    "checked_at": timestamp(),
                }
                save_state(state_path, state)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
