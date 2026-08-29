#!/usr/bin/env python3
"""Exchange or refresh TikTok OAuth tokens and save them to .env.

Usage:
  python scripts/exchange_tiktok_code.py --code <code> --env .env
  python scripts/exchange_tiktok_code.py --refresh --env .env

The script uses TikTok Shop's GET token endpoint and writes returned token
values into the provided env file without printing token contents.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
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


def request_token(params: dict[str, str], endpoint: str = "get") -> dict:
    # TikTok Shop OAuth token endpoints use GET requests.
    url = f"https://auth.tiktok-shops.com/api/v2/token/{endpoint}"
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


def exchange_code(app_key: str, app_secret: str, code: str, redirect_uri: str | None = None) -> dict:
    params = {
        "app_key": app_key,
        "app_secret": app_secret,
        "auth_code": code,
        "grant_type": "authorized_code",
    }
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    return request_token(params)


def extract_auth_code(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme and parsed.netloc:
        query = urllib.parse.parse_qs(parsed.query)
        for key in ("code", "auth_code", "authCode"):
            if query.get(key):
                return query[key][0].strip()
    return text


def refresh_token(app_key: str, app_secret: str, token: str) -> dict:
    return request_token(
        {
            "app_key": app_key,
            "app_secret": app_secret,
            "refresh_token": token,
            "grant_type": "refresh_token",
        },
        endpoint="refresh",
    )


def token_payload(result: dict) -> dict:
    if not isinstance(result, dict):
        return {}
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    return data if isinstance(data, dict) else {}


def update_env_with_tokens(env: dict[str, str], result: dict) -> dict[str, str]:
    data = token_payload(result)
    access_token = data.get("access_token") or data.get("accessToken")
    refresh = data.get("refresh_token") or data.get("refreshToken")
    if not access_token:
        print("Access token not found in response:")
        print(json.dumps(mask_sensitive(result), ensure_ascii=False, indent=2))
        raise SystemExit(3)

    env["TIKTOK_ACCESS_TOKEN"] = str(access_token).strip().strip('"')
    if refresh:
        env["TIKTOK_REFRESH_TOKEN"] = str(refresh).strip().strip('"')

    for source_key, env_key in [
        ("access_token_expire_in", "TIKTOK_ACCESS_TOKEN_EXPIRES_IN"),
        ("accessTokenExpireIn", "TIKTOK_ACCESS_TOKEN_EXPIRES_IN"),
        ("refresh_token_expire_in", "TIKTOK_REFRESH_TOKEN_EXPIRES_IN"),
        ("refreshTokenExpireIn", "TIKTOK_REFRESH_TOKEN_EXPIRES_IN"),
        ("open_id", "TIKTOK_OPEN_ID"),
        ("seller_name", "TIKTOK_SELLER_NAME"),
    ]:
        if source_key in data and data[source_key] not in (None, ""):
            env[env_key] = str(data[source_key]).strip()
    expires_in = data.get("access_token_expire_in") or data.get("accessTokenExpireIn") or data.get("expires_in")
    if expires_in:
        env["TIKTOK_ACCESS_TOKEN_EXPIRES_IN"] = str(expires_in).strip().strip('"')
        try:
            env["TIKTOK_ACCESS_TOKEN_EXPIRES_AT"] = str(int(time.time()) + int(float(str(expires_in))))
        except ValueError:
            pass
    return env


def backup_env_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    shutil.copy2(path, backup)
    return backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exchange or refresh TikTok OAuth tokens and write them to .env")
    parser.add_argument("--code", default="")
    parser.add_argument("--code-stdin", action="store_true", help="Read the authorization code from stdin.")
    parser.add_argument("--refresh", action="store_true", help="Refresh using TIKTOK_REFRESH_TOKEN from env.")
    parser.add_argument("--refresh-token", default="", help="Override TIKTOK_REFRESH_TOKEN for this run.")
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

    code = args.code
    if args.code_stdin:
        code = sys.stdin.readline().strip()
    code = extract_auth_code(code)

    if args.refresh:
        refresh = args.refresh_token or env.get("TIKTOK_REFRESH_TOKEN", "")
        if not refresh:
            print("Missing refresh token. Re-authorize with --code once, then future refreshes can use --refresh.")
            return 2
        print("Refreshing TikTok access token...")
        result = refresh_token(app_key, app_secret, refresh)
    elif code:
        print("Exchanging authorization code for TikTok tokens...")
        result = exchange_code(app_key, app_secret, code, redirect_uri=args.redirect_uri)
    else:
        print("Pass either --code <authorization-code> or --refresh.")
        return 2

    update_env_with_tokens(env, result)
    backup = backup_env_file(env_path)
    write_env(env_path, env)
    print("Wrote TikTok token values to", env_path)
    if backup:
        print("Backup of original .env saved to", backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
