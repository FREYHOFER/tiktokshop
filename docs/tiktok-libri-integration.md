# TikTok Shop + Libri integration

This document tracks what is wired into the daily shop workflow and which configuration values are still needed.

## Daily workflow

Workflow: `.github/workflows/tiktok-order-automation.yml`

Schedule: daily at `07:30 UTC`.

Steps:
1. Refresh TikTok access token.
2. Run the read-only TikTok/Libri integration audit.
3. Fetch pending TikTok orders and prepare Libri order packages.
4. Submit only clean prepared orders to Libri.
5. Check Libri delivery-note pages and, when a tracking number is found, send tracking back to TikTok Shop.
6. Upload audit artifacts and persist local state in `.automation/order_state.json` and `.automation/libri_order_state.json`.

## Duplicate protection

` .automation/libri_order_state.json ` is the local source of truth for Libri submissions. Before a Libri order is submitted, `scripts/libri_customer_submit.py` checks whether the TikTok order ID is already recorded as `submitted`. If yes, it skips the order.

Only clean packages with `automation_status=prepared` are auto-submitted. Packages with warnings stay manual-review only.

## Required secrets

Required for base order flow:

- `LIBRI_CUSTOMER_NUMBER`
- `LIBRI_USERNAME`
- `LIBRI_PASSWORD`
- `TIKTOK_APP_KEY`
- `TIKTOK_APP_SECRET`
- `TIKTOK_ACCESS_TOKEN` or `TIKTOK_REFRESH_TOKEN`

Recommended for stable operation:

- `TIKTOK_SHOP_CIPHER`
- `TIKTOK_WAREHOUSE_ID`
- `TIKTOK_SHIPPING_PROVIDER_NAME` — default in workflow: `DHL`
- `TIKTOK_SHIPPING_PROVIDER_ID` — optional, but more reliable if TikTok requires the carrier ID
- `TIKTOK_SHIP_PACKAGE_PATH_TEMPLATE` — default in workflow: `/fulfillment/{version}/packages/{package_id}/ship`
- `LIBRI_DELIVERY_NOTE_URLS` — exact comma- or newline-separated Mein.Libri URLs where German Lieferscheine/Belege appear after login
- `TIKTOK_AFFILIATE_AUDIT_PATHS` — optional comma- or newline-separated affiliate/sample probe endpoints if the app has Affiliate API scopes

## What is still not fully automatic

Affiliate/sample checks depend on TikTok Affiliate API access and scopes. The daily audit probes likely endpoints, but it cannot approve samples or read the Affiliate Center unless the app is allowed to access those APIs.

Libri Lieferschein detection depends on finding the correct Mein.Libri document page. If the default guessed pages do not work, set `LIBRI_DELIVERY_NOTE_URLS` to the exact pages from the browser after login.

TikTok tracking handback uses the official package ship endpoint by default. If the account requires a different endpoint or payload, set `TIKTOK_SHIP_PACKAGE_PATH_TEMPLATE` and `TIKTOK_SHIPPING_PROVIDER_ID`.

## Scripts

- `scripts/tiktok_order_automation.py`: reads TikTok orders and prepares Libri packages.
- `scripts/libri_customer_submit.py`: submits a prepared package to Libri with duplicate-state protection.
- `scripts/submit_clean_prepared_libri_orders.py`: submits only clean packages.
- `scripts/libri_lieferschein_sync.py`: checks Libri documents, extracts tracking, and updates TikTok fulfillment.
- `scripts/tiktok_shop_integration_audit.py`: read-only audit for orders, products/listings, affiliate/sample readiness, Libri login, and Lieferschein pages.
