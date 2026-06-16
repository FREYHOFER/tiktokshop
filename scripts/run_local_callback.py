#!/usr/bin/env python3
"""Run a tiny local HTTP server to capture the TikTok OAuth code and exchange it for a token.

Usage:
  python scripts/run_local_callback.py --env .env --host 127.0.0.1 --port 8765

When the browser is redirected to /tiktok/callback?code=..., the server will
call the exchange routine and write `TIKTOK_ACCESS_TOKEN` into the env file.
"""
from __future__ import annotations

import argparse
import http.server
import importlib.util
import json
import socket
import threading
import urllib.parse
from pathlib import Path


def load_module_from_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    loader.exec_module(module)
    return module


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/tiktok/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [""])[0]
        app_key = qs.get("app_key", [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if not code:
            self.wfile.write(b"<html><body><h1>No code received</h1></body></html>")
            return

        # Exchange the code using the helper module loaded by path
        scripts_dir = Path(__file__).resolve().parent
        exch = load_module_from_path(scripts_dir / "exchange_tiktok_code.py", "exchange_tiktok_code")
        env_path = Path(self.server.env_path)
        env = exch.load_env(env_path)
        app_key_val = env.get("TIKTOK_APP_KEY", "")
        app_secret_val = env.get("TIKTOK_APP_SECRET", "")
        try:
            result = exch.exchange_code(app_key_val, app_secret_val, code, redirect_uri=f"http://{self.server.server_address[0]}:{self.server.server_address[1]}/tiktok/callback")
        except SystemExit as exc:
            self.wfile.write(f"<html><body><h1>Error exchanging code</h1><pre>{exc}</pre></body></html>".encode())
            # don't shut down server on exchange error; let user retry
            return
        token = None
        if isinstance(result, dict):
            data = result.get("data") if isinstance(result.get("data"), dict) else result
            token = data.get("access_token") or data.get("accessToken") or result.get("access_token")
        if not token:
            self.wfile.write(b"<html><body><h1>Token not found in response</h1><pre>")
            self.wfile.write(json.dumps(result, ensure_ascii=False, indent=2).encode())
            self.wfile.write(b"</pre></body></html>")
            return

        # write token to env
        env["TIKTOK_ACCESS_TOKEN"] = token.strip().strip('"')
        backup = env_path.with_suffix(env_path.suffix + ".bak")
        if env_path.exists():
            env_path.rename(backup)
        exch.write_env(env_path, env)

        self.wfile.write(b"<html><body><h1>Success</h1><p>Access token saved to .env</p></body></html>")
        # shutdown server cleanly in a new thread
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def run_server(env_path: Path, host: str, port: int):
    server = http.server.ThreadingHTTPServer((host, port), CallbackHandler)
    # attach env path to server so handler can access it
    server.env_path = str(env_path)
    print(f"Listening for callback on http://{host}:{port}/tiktok/callback")
    print("Open the TikTok authorization link in your browser now.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Interrupted, shutting down.")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local callback to capture TikTok OAuth code and exchange for token")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    env_path = Path(args.env)
    run_server(env_path, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
