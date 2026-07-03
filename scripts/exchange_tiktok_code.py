#!/usr/bin/env python3
"""Exchange a TikTok OAuth authorization code for tokens and save them to .env.

Usage:
  python scripts/exchange_tiktok_code.py --code <code> --env .env

The script attempts a GET to the TikTok Shop token endpoint and writes
`TIKTOK_ACCESS_TOKEN=<token>` and, when returned by TikTok,
`TIKTOK_REFRESH_TOKEN=<token>` into the provided env file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


SENSITIVE_KEY_PARTS = ("token", "secret", "password", "auth_code")


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def write_env(path: Path, env: dict[str, str]) -> None:
    # Preserve unknown lines by reading original and replacing/adding keys
    lines = []
    existing = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip().startswith("#") or "=" not in raw:
                lines.append(raw)
                continue
            k, v = raw.split("=", 1)
            existing[k.strip()] = True
            if k.strip() in env:
                lines.append(f"{k.strip()}={env[k.strip()]}")
            else:
                lines.append(raw)
    # append any missing
    for k, v in env.items():
        if k not in existing:
            lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask_sensitive(value):
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if any(part in str(key).casefold() for part in SENSITIVE_KEY_PARTS):
                masked[key] = "***"
            else:
                masked[key] = mask_sensitive(item)
        return masked
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def exchange_code(app_key: str, app_secret: str, code: str, redirect_uri: str | None = None) -> dict:
    # Correct TikTok Shop API OAuth token endpoint (GET method).
    url = "https://auth.tiktok-shops.com/api/v2/token/get"
    params = {
        "app_key": app_key,
        "app_secret": app_secret,
        "auth_code": code,
        "grant_type": "authorized_code",
    }
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} from token endpoint: {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Network error exchanging code: {exc}")
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        raise SystemExit(f"Non-JSON response from token endpoint: {payload[:1000]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exchange TikTok OAuth code for access/refresh tokens and write to .env")
    parser.add_argument("--code", required=True)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--redirect-uri", default="http://127.0.0.1:8765/tiktok/callback")
    parser.add_argument("--app-key", default="")
    parser.add_argument("--app-secret", default="")
    args = parser.parse_args(argv)

    env_path = Path(args.env)
    env = load_env(env_path)
    app_key = args.app_key or env.get("TIKTOK_APP_KEY", "")
    app_secret = args.app_secret or env.get("TIKTOK_APP_SECRET", "")
    if not app_key or not app_secret:
        print("Missing app key/secret. Set TIKTOK_APP_KEY and TIKTOK_APP_SECRET in .env or pass --app-key/--app-secret.")
        return 2

    print("Exchanging code for TikTok tokens...")
    result = exchange_code(app_key, app_secret, args.code, redirect_uri=args.redirect_uri)
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    if not isinstance(data, dict):
        data = {}

    token = data.get("access_token") or data.get("accessToken") or result.get("access_token")
    refresh_token = data.get("refresh_token") or data.get("refreshToken") or result.get("refresh_token")
    expires_in = data.get("access_token_expire_in") or data.get("accessTokenExpireIn") or data.get("expires_in")

    if not token:
        print("Access token not found in response:")
        print(json.dumps(mask_sensitive(result), ensure_ascii=False, indent=2))
        return 3

    print("Received access token. Writing to", env_path)
    env["TIKTOK_ACCESS_TOKEN"] = str(token).strip().strip('"')
    if refresh_token:
        env["TIKTOK_REFRESH_TOKEN"] = str(refresh_token).strip().strip('"')
    if expires_in:
        env["TIKTOK_ACCESS_TOKEN_EXPIRES_IN"] = str(expires_in).strip().strip('"')
        try:
            env["TIKTOK_ACCESS_TOKEN_EXPIRES_AT"] = str(int(time.time()) + int(float(str(expires_in))))
        except ValueError:
            pass

    backup = env_path.with_suffix(env_path.suffix + ".bak")
    if env_path.exists():
        env_path.rename(backup)
    write_env(env_path, env)
    print("Wrote TikTok token values to", env_path)
    print("Backup of original .env saved to", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
