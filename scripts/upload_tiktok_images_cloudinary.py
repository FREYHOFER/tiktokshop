#!/usr/bin/env python3
"""Upload prepared TikTok listing images to Cloudinary and merge HTTPS URLs.

Required .env keys:
  CLOUDINARY_CLOUD_NAME=...
  CLOUDINARY_API_KEY=...
  CLOUDINARY_API_SECRET=...

Optional:
  CLOUDINARY_FOLDER=tiktokshop/books
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def cloudinary_signature(params: dict[str, str], api_secret: str) -> str:
    signable = {
        key: value
        for key, value in params.items()
        if value and key not in {"file", "cloud_name", "resource_type", "api_key", "signature"}
    }
    payload = "&".join(f"{key}={signable[key]}" for key in sorted(signable))
    return hashlib.sha1(f"{payload}{api_secret}".encode("utf-8")).hexdigest()


def multipart_body(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----codex-cloudinary-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_image(row: dict[str, str], folder: str, cloud_name: str, api_key: str, api_secret: str) -> dict[str, str]:
    local_path = Path(row["local_image_path"])
    if not local_path.exists():
        raise FileNotFoundError(local_path)
    ean = row.get("ean", "").strip()
    public_id = row.get("public_id", "").strip() or (f"LIBRI-{ean}-main-cover" if ean else local_path.stem)
    timestamp = str(int(time.time()))
    fields = {
        "api_key": api_key,
        "timestamp": timestamp,
        "folder": folder,
        "public_id": public_id,
        "overwrite": "true",
        "unique_filename": "false",
    }
    fields["signature"] = cloudinary_signature(fields, api_secret)
    body, content_type = multipart_body(fields, "file", local_path)
    request = urllib.request.Request(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "secure_url": payload.get("secure_url", ""),
        "public_id": payload.get("public_id", public_id),
        "bytes": str(payload.get("bytes", "")),
        "width": str(payload.get("width", "")),
        "height": str(payload.get("height", "")),
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def merge_hosted_urls(plan_path: Path, hosted_by_key: dict[str, str], output_path: Path) -> None:
    plan_rows = read_csv(plan_path)
    fieldnames = list(plan_rows[0].keys()) if plan_rows else []
    if "hosted_main_image_url" not in fieldnames:
        fieldnames.append("hosted_main_image_url")
    for row in plan_rows:
        hosted_url = hosted_by_key.get(row.get("ean", "")) or hosted_by_key.get(row.get("seller_sku", ""))
        if hosted_url:
            row["hosted_main_image_url"] = hosted_url
    write_csv(output_path, plan_rows, fieldnames)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload generated TikTok main images to Cloudinary.")
    parser.add_argument("--queue", required=True, help="main_image_upload_queue.csv from the mediafix output.")
    parser.add_argument("--plan", help="listing_quality_update_plan.csv to copy and enrich with hosted URLs.")
    parser.add_argument("--output-plan", help="Output plan CSV with hosted_main_image_url filled.")
    parser.add_argument("--log", help="Upload log CSV. Defaults next to queue.")
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()

    load_env(Path(args.env))
    cloud_name = require_env("CLOUDINARY_CLOUD_NAME")
    api_key = require_env("CLOUDINARY_API_KEY")
    api_secret = require_env("CLOUDINARY_API_SECRET")
    folder = os.environ.get("CLOUDINARY_FOLDER", "tiktokshop/books").strip() or "tiktokshop/books"

    queue_path = Path(args.queue)
    rows = read_csv(queue_path)
    log_rows = []
    hosted_by_key: dict[str, str] = {}
    for row in rows:
        result = {
            "seller_sku": row.get("seller_sku", ""),
            "ean": row.get("ean", ""),
            "local_image_path": row.get("local_image_path", ""),
            "hosted_main_image_url": "",
            "public_id": "",
            "status": "error",
            "error": "",
        }
        try:
            uploaded = upload_image(row, folder, cloud_name, api_key, api_secret)
            result["hosted_main_image_url"] = uploaded["secure_url"]
            result["public_id"] = uploaded["public_id"]
            result["status"] = "uploaded"
            if row.get("ean"):
                hosted_by_key[row["ean"]] = uploaded["secure_url"]
            if row.get("seller_sku"):
                hosted_by_key[row["seller_sku"]] = uploaded["secure_url"]
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        log_rows.append(result)

    log_path = Path(args.log) if args.log else queue_path.with_name("cloudinary_upload_log.csv")
    write_csv(log_path, log_rows, ["seller_sku", "ean", "local_image_path", "hosted_main_image_url", "public_id", "status", "error"])

    if args.plan:
        output_plan = Path(args.output_plan) if args.output_plan else Path(args.plan).with_name("listing_quality_update_plan_hosted.csv")
        merge_hosted_urls(Path(args.plan), hosted_by_key, output_plan)
        print(f"Hosted plan: {output_plan.resolve()}")
    print(f"Uploaded: {sum(row['status'] == 'uploaded' for row in log_rows)}")
    print(f"Log: {log_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
