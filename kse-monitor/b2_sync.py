#!/usr/bin/env python3
"""Restore and persist KSE monitor state in a private Backblaze B2 prefix."""

from __future__ import annotations

import json
import os
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "last_eod.json"
B2_KEY = "kse-market-monitor/last_eod.json"


def b2_client():
    required = ["B2_KEY_ID", "B2_APPLICATION_KEY", "B2_BUCKET"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing B2 configuration: {', '.join(missing)}")
    endpoint = os.environ.get("B2_ENDPOINT", "https://s3.us-east-005.backblazeb2.com").rstrip("/")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-005",
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APPLICATION_KEY"],
        config=Config(signature_version="s3v4"),
    )


def missing_object(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


def validate_state(data: bytes) -> None:
    parsed = json.loads(data)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("eod_sent", []), list):
        raise RuntimeError("last_eod.json must be an object containing an eod_sent array")


def download() -> None:
    s3 = b2_client()
    bucket = os.environ["B2_BUCKET"]
    try:
        data = s3.get_object(Bucket=bucket, Key=B2_KEY)["Body"].read()
    except ClientError as error:
        if missing_object(error):
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            if STATE_FILE.exists():
                validate_state(STATE_FILE.read_bytes())
                print("[B2] No KSE state exists yet; retaining the repository state for one-time bootstrap.")
            else:
                STATE_FILE.write_text('{"eod_sent": []}\n', encoding="utf-8")
                print("[B2] No KSE state exists; created an empty state for bootstrap.")
            return
        raise
    validate_state(data)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_bytes(data)
    print(f"[B2] Restored KSE state from {B2_KEY}.")


def upload() -> None:
    if not STATE_FILE.exists():
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text('{"eod_sent": []}\n', encoding="utf-8")
    data = STATE_FILE.read_bytes()
    validate_state(data)
    s3 = b2_client()
    s3.put_object(
        Bucket=os.environ["B2_BUCKET"],
        Key=B2_KEY,
        Body=data,
        ContentType="application/json",
    )
    print(f"[B2] Uploaded KSE state to {B2_KEY}.")


command = os.environ.get("B2_COMMAND", "")
try:
    if command == "download":
        download()
    elif command == "upload":
        upload()
    else:
        raise RuntimeError("Set B2_COMMAND to download or upload")
except Exception as error:
    print(f"[B2] KSE state sync failed: {error}")
    raise SystemExit(1)
