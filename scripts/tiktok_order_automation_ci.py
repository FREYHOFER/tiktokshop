#!/usr/bin/env python3
"""Run TikTok order automation from GitHub Actions with actionable errors."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tiktok_order_automation import TikTokApiError, main  # noqa: E402


def advice_for_error(message: str) -> str:
    lower = message.casefold()

    if "missing tiktok api values" in lower:
        return (
            "Add or update these GitHub environment secrets in the shop environment: "
            "TIKTOK_APP_KEY, TIKTOK_APP_SECRET and TIKTOK_ACCESS_TOKEN."
        )
    if "no authorized tiktok shops" in lower:
        return (
            "Create a new TikTok Shop access token for the correct app and shop, then update "
            "the GitHub environment secret TIKTOK_ACCESS_TOKEN."
        )
    if "multiple authorized tiktok shops" in lower:
        return (
            "Set the GitHub environment secret TIKTOK_SHOP_CIPHER to the shop_cipher of the "
            "shop this automation should use."
        )
    if "access_token" in lower or "unauthorized" in lower or "401" in lower:
        return (
            "Refresh the TikTok Shop access token and update the GitHub environment secret "
            "TIKTOK_ACCESS_TOKEN. Also confirm the token belongs to the same app key."
        )
    if "sign" in lower or "signature" in lower:
        return (
            "Check TIKTOK_APP_KEY and TIKTOK_APP_SECRET. If they are correct, the TikTok "
            "signature settings in the workflow may need adjustment."
        )
    if "shop_cipher" in lower:
        return "Check or set the GitHub environment secret TIKTOK_SHOP_CIPHER."

    return (
        "Open the failed Prepare new orders step and check the TikTok API error above. "
        "Most likely fix: refresh TIKTOK_ACCESS_TOKEN and verify TIKTOK_SHOP_CIPHER."
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TikTokApiError as exc:
        message = str(exc)
        advice = advice_for_error(message)
        print(f"::error title=TikTok API setup problem::{message} Next action: {advice}")
        print("TikTok API setup problem:")
        print(message)
        print("Next action:")
        print(advice)
        raise SystemExit(1)
