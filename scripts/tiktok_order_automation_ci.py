#!/usr/bin/env python3
"""Run TikTok order automation safely from GitHub Actions.

Scheduled workflow runs should not fail only because the external TikTok API
or its shop authorization is temporarily unavailable. The underlying automation
script is still used unchanged for local/manual runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tiktok_order_automation import TikTokApiError, main  # noqa: E402


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TikTokApiError as exc:
        print(f"::notice::TikTok order automation skipped because the TikTok API returned an error: {exc}")
        raise SystemExit(0)
