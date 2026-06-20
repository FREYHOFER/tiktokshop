#!/usr/bin/env python3
"""Read-only TikTok Shop mission endpoint test.

This script calls one explicitly configured TikTok Shop API path and writes a
sanitized JSON result. It does not change TikTok data and does not create
Google Tasks yet.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://open-api.tiktokglobalshop.com"
DEFAULT_VERSION = "202309"
DEFAULT_OUTPUT = Path("outputs") / "mission_endpoint_test" / "result.json"
SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|password|credential|phone|email|address|recipient|buyer|customer)",
    re.IGNORECASE,
)


class TikTokMissionError(RuntimeError):
    pass


def clean(value: object) -> str:
    return str(value or "").replace("\ufeff", "").strip()


def bool_env(value: str, default: bool = False) -> bool:
    if not clean(value):
        return default
    return clean(value).casefold() in {"1", "true", "yes", "y", "on"}


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(env: dict[str, str], key: str, default: str = "") -> str:
    return clean(os.environ.get(key) or env.get(key) or default)


def compact_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def truncate(value: object, limit: int = 1000) -> str:
    text = clean(value)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def redact(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "<max_depth>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            result[key_text] = "<redacted>" if SENSITIVE_KEY_RE.search(key_text) else redact(item, depth + 1)
        return result
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value[:10]]
    if isinstance(value, str):
        return truncate(value)
    return value


def parse_json_object(text: str, field_name: str) -> dict[str, Any]:
    if not clean(text):
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TikTokMissionError(f"{field_name} must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise TikTokMissionError(f"{field_name} must be a JSON object.")
    return parsed


def try_json(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else {"value": parsed}


class TikTokShopClient:
    def __init__(self, env: dict[str, str]):
        self.app_key = env_value(env, "TIKTOK_APP_KEY")
        self.app_secret = env_value(env, "TIKTOK_APP_SECRET")
        self.access_token = env_value(env, "TIKTOK_ACCESS_TOKEN")
        self.shop_cipher = env_value(env, "TIKTOK_SHOP_CIPHER")
        self.base_url = env_value(env, "TIKTOK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.version = env_value(env, "TIKTOK_API_VERSION", DEFAULT_VERSION)
        self.include_version = bool_env(env_value(env, "TIKTOK_INCLUDE_VERSION", "true"), True)
        self.access_token_in_query = bool_env(env_value(env, "TIKTOK_ACCESS_TOKEN_IN_QUERY", "false"), False)
        self.sign_include_body = bool_env(env_value(env, "TIKTOK_SIGN_INCLUDE_BODY", "true"), True)
        missing = [
            key
            for key, value in [
                ("TIKTOK_APP_KEY", self.app_key),
                ("TIKTOK_APP_SECRET", self.app_secret),
                ("TIKTOK_ACCESS_TOKEN", self.access_token),
                ("TIKTOK_SHOP_CIPHER", self.shop_cipher),
            ]
            if not value
        ]
        if missing:
            raise TikTokMissionError("Missing TikTok secret(s): " + ", ".join(missing))

    def sign(self, path: str, params: dict[str, str], body_text: str = "") -> str:
        sign_params = {
            key: str(value)
            for key, value in params.items()
            if key not in {"sign", "access_token"} and value is not None and value != ""
        }
        sign_input = path + "".join(f"{key}{sign_params[key]}" for key in sorted(sign_params))
        if self.sign_include_body and body_text:
            sign_input += body_text
        wrapped = self.app_secret + sign_input + self.app_secret
        return hmac.new(self.app_secret.encode("utf-8"), wrapped.encode("utf-8"), hashlib.sha256).hexdigest()

    def request(self, method: str, path: str, params: dict[str, Any], body: dict[str, Any] | None) -> dict[str, Any]:
        if not path.startswith("/"):
            path = "/" + path

        query: dict[str, str] = {
            "app_key": self.app_key,
            "timestamp": str(int(time.time())),
            "shop_cipher": self.shop_cipher,
        }
        if self.include_version:
            query["version"] = self.version
        for key, value in params.items():
            if value not in (None, ""):
                query[key] = str(value)
        if self.access_token_in_query:
            query["access_token"] = self.access_token

        body_text = compact_json(body) if body is not None else ""
        query["sign"] = self.sign(path, query, body_text)
        url = self.base_url + path + "?" + urllib.parse.urlencode(query)
        data = body_text.encode("utf-8") if body is not None else None

        request = urllib.request.Request(
            url,
            data=data,
            method=method.upper(),
            headers={
                "Content-Type": "application/json",
                "x-tts-access-token": self.access_token,
                "User-Agent": "TikTokShop-MissionEndpointTest/1.0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode("utf-8", errors="replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            status = exc.code
        except urllib.error.URLError as exc:
            return {
                "http_status": 0,
                "error": f"Connection failed: {truncate(exc)}",
            }

        payload = try_json(text)
        result: dict[str, Any] = {
            "http_status": status,
            "raw_text_sample": truncate(text),
        }
        if payload is not None:
            result["api_code"] = clean(payload.get("code"))
            result["api_message"] = truncate(payload.get("message") or payload.get("msg") or "")
            result["sanitized_payload"] = redact(payload)
            result.pop("raw_text_sample", None)
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call one read-only TikTok Shop API path and save sanitized output.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--method", default="")
    parser.add_argument("--path", default="")
    parser.add_argument("--params-json", default="")
    parser.add_argument("--body-json", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = load_env_file(Path(args.env))

    method = (args.method or env_value(env, "TIKTOK_MISSION_METHOD", "GET")).upper()
    path = args.path or env_value(env, "TIKTOK_MISSION_API_PATH")
    if method not in {"GET", "POST"}:
        raise TikTokMissionError("--method must be GET or POST.")
    if not path:
        raise TikTokMissionError(
            "No mission API path configured. Set workflow input 'path' or repository secret/variable TIKTOK_MISSION_API_PATH."
        )

    params = parse_json_object(args.params_json or env_value(env, "TIKTOK_MISSION_PARAMS_JSON"), "params-json")
    body_source = args.body_json or env_value(env, "TIKTOK_MISSION_BODY_JSON")
    body = parse_json_object(body_source, "body-json") if body_source else None
    if method == "POST" and body is None:
        body = {}

    client = TikTokShopClient(env)
    api_result = client.request(method, path, params=params, body=body)

    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "method": method,
        "path": path,
        "params_keys": sorted(params.keys()),
        "has_body": body is not None,
        "result": api_result,
        "next_step": "If this response contains mission/task data, map it into Google Tasks in the next workflow.",
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Wrote sanitized result to {output.resolve()}")
    print(f"HTTP status: {api_result.get('http_status')}")
    if "api_code" in api_result:
        print(f"API code: {api_result.get('api_code')}")
        print(f"API message: {api_result.get('api_message')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
