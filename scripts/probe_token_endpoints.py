#!/usr/bin/env python3
"""Probe multiple TikTok token endpoints to find the correct one."""
from __future__ import annotations

import urllib.request
import urllib.error
import urllib.parse
import json

app_key = "6kb1epvf2cl16"
app_secret = "4196346e2b9c5f7cbf7ffb5a15c82bb3a2c3744c"
code = "GCP_BF3ERwAAAABqyZ4b_jRHvFFLoumyfqnxpqBDz8AzpdhB_sMhalDn_5f-Kdw2xr5M0Gk36c-d5pa-icra0kjyN_2pc2sxQpMhsqkwzDEozwueVeB0z1aKUQpHRYkef4579ztZ_JrVphMwvhpPf-5byEHS9JeMR4H17PVkIiU1UiTKRUjKlKsaIA"

endpoints = [
    ("POST", "https://open-api.tiktokglobalshop.com/oauth/access_token"),
    ("POST", "https://open-api.tiktokglobalshop.com/oauth/token"),
    ("POST", "https://open-api.tiktokglobalshop.com/oauth/2.0/token"),
    ("POST", "https://open-api.tiktokglobalshop.com/oauth/202309/access_token"),
    ("POST", "https://auth.tiktokglobalshop.com/oauth/access_token"),
    ("POST", "https://auth.tiktokglobalshop.com/oauth/token"),
    ("POST", "https://api.tiktokshop.com/oauth/access_token"),
    ("POST", "https://api.tiktokshop.com/oauth/token"),
    ("GET", "https://open-api.tiktokglobalshop.com/oauth/access_token"),
    ("GET", "https://open-api.tiktokglobalshop.com/oauth/token"),
]

data = {
    "app_key": app_key,
    "app_secret": app_secret,
    "code": code,
}

for method, url in endpoints:
    try:
        if method == "POST":
            body = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        else:
            url_with_params = url + "?" + urllib.parse.urlencode(data)
            req = urllib.request.Request(url_with_params, method="GET")

        with urllib.request.urlopen(req, timeout=10) as resp:
            result = resp.read().decode("utf-8", errors="replace")
            print(f"✓ {method} {url}")
            print(f"  Status: {resp.status}")
            print(f"  Response: {result[:200]}")
            print()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:100]
        print(f"✗ {method} {url}")
        print(f"  HTTP {exc.code}: {detail}")
        print()
    except urllib.error.URLError as exc:
        print(f"✗ {method} {url}")
        print(f"  Network: {exc}")
        print()
    except Exception as exc:
        print(f"✗ {method} {url}")
        print(f"  Error: {exc}")
        print()
