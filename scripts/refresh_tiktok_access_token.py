#!/usr/bin/env python3
"""Refresh a TikTok Shop Open API access token and write it back to .env.

The GitHub Actions jobs create a temporary .env from repository/environment
secrets. This script can refresh an expired TIKTOK_ACCESS_TOKEN from
TIKTOK_REFRESH_TOKEN before the automation calls the TikTok Shop Open API.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

TOKEN_REFRESH_URL = "https://auth.tiktok-shops.com/api/v2/token/refresh"

SENSITIVE_KEY_PARTS = ("token", "secret", "password", "auth_code")


def clean(value: object) -> str:
    return str(value or "").replace("\ufeff", "").strip().strip('"').strip("'")


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = clean(value)
    return env


def write_env(path: Path, updates: dict[str, str]) -> None:
    lines: list[str] = []
    seen: set[str] = set()
    if path.exists():
        for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if raw.strip().startswith("#") or "=" not in raw:
                lines.append(raw)
                continue
            key, _value = raw.split("=", 1)
            key = key.strip()
            if key in updates:
                lines.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                lines.append(raw)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            if any(part in str(key).casefold() for part in SENSITIVE_KEY_PARTS):
                masked[key] = "***"
            else:
                masked[key] = mask_sensitive(item)
        return masked
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def refresh_access_token(app_key: str, app_secret: str, refresh_token: str) -> dict[str, Any]:
    params = {
        "app_key": app_key,
        "app_secret": app_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    url = TOKEN_REFRESH_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TikTok token refresh HTTP {exc.code}: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"TikTok token refresh connection failed: {exc}") from exc

    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"TikTok token refresh returned non-JSON: {payload[:1000]}") from exc

    code = clean(result.get("code"))
    message = clean(result.get("message") or result.get("msg"))
    if code and code not in {"0", "OK", "SUCCESS"}:
        raise RuntimeError(f"TikTok token refresh error {code}: {message or json.dumps(mask_sensitive(result), ensure_ascii=False)}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh TikTok Shop access token in .env")
    parser.add_argument("--env", default=".env")
    args = parser.parse_args(argv)

    env_path = Path(args.env)
    env = load_env(env_path)
    app_key = clean(env.get("TIKTOK_APP_KEY"))
    app_secret = clean(env.get("TIKTOK_APP_SECRET"))
    refresh_token = clean(env.get("TIKTOK_REFRESH_TOKEN"))

    if not refresh_token:
        print("No TIKTOK_REFRESH_TOKEN set; keeping existing TIKTOK_ACCESS_TOKEN.")
        return 0
    missing = [key for key, value in [("TIKTOK_APP_KEY", app_key), ("TIKTOK_APP_SECRET", app_secret)] if not value]
    if missing:
        raise SystemExit("Missing required TikTok values for token refresh: " + ", ".join(missing))

    result = refresh_access_token(app_key, app_secret, refresh_token)
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    access_token = clean(data.get("access_token") or data.get("accessToken"))
    new_refresh_token = clean(data.get("refresh_token") or data.get("refreshToken"))
    expires_in = clean(data.get("access_token_expire_in") or data.get("accessTokenExpireIn") or data.get("expires_in"))

    if not access_token:
        safe_result = json.dumps(mask_sensitive(result), ensure_ascii=False, indent=2)
        raise SystemExit("TikTok token refresh response did not contain an access token:\n" + safe_result)

    updates = {"TIKTOK_ACCESS_TOKEN": access_token}
    if new_refresh_token:
        updates["TIKTOK_REFRESH_TOKEN"] = new_refresh_token
    if expires_in:
        updates["TIKTOK_ACCESS_TOKEN_EXPIRES_IN"] = expires_in
        try:
            updates["TIKTOK_ACCESS_TOKEN_EXPIRES_AT"] = str(int(time.time()) + int(float(expires_in)))
        except ValueError:
            pass

    write_env(env_path, updates)
    print("Refreshed TikTok access token in", env_path)
    if new_refresh_token and new_refresh_token != refresh_token:
        print("TikTok returned a new refresh token. The temporary .env was updated for this run; update the GitHub secret TIKTOK_REFRESH_TOKEN if future runs start failing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
