#!/usr/bin/env python3
"""Synchronize KSE monitor configuration and runtime state with Backblaze B2."""

from __future__ import annotations

import json
import os
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = Path(os.environ.get("B2_CONFIG_FILE", str(ROOT / "config.yaml")))
STATE_FILE = Path(os.environ.get("B2_STATE_FILE", str(ROOT / "state" / "last_eod.json")))
CONFIG_KEY = "kse-market-monitor/config.yaml"
STATE_KEY = "kse-market-monitor/last_eod.json"


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


def validate_config(data: bytes) -> None:
    import yaml
    parsed = yaml.safe_load(data)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("stocks"), list) or not parsed["stocks"]:
        raise RuntimeError("config.yaml must contain a non-empty stocks list")
    if any(not isinstance(symbol, str) or not symbol.strip() for symbol in parsed["stocks"]):
        raise RuntimeError("config.yaml stocks must contain symbols only")


def validate_state(data: bytes) -> None:
    parsed = json.loads(data)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("eod_sent", []), list):
        raise RuntimeError("last_eod.json must be an object containing an eod_sent array")


def get_object(s3, key: str) -> bytes:
    return s3.get_object(Bucket=os.environ["B2_BUCKET"], Key=key)["Body"].read()


def download() -> None:
    s3 = b2_client()
    try:
        config_data = get_object(s3, CONFIG_KEY)
    except ClientError as error:
        if missing_object(error):
            raise RuntimeError(f"Required B2 configuration object is missing: {CONFIG_KEY}") from error
        raise
    validate_config(config_data)
    try:
        state_data = get_object(s3, STATE_KEY)
    except ClientError as error:
        if not missing_object(error):
            raise
        state_data = b'{"eod_sent": []}\n'
        print(f"[B2] State object missing; initializing {STATE_KEY}.")
    validate_state(state_data)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_bytes(config_data)
    STATE_FILE.write_bytes(state_data)
    print(f"[B2] Restored {CONFIG_KEY} and {STATE_KEY}.")


def upload() -> None:
    if not CONFIG_FILE.exists():
        raise RuntimeError(f"Cannot upload: configuration file is missing at {CONFIG_FILE}")
    if not STATE_FILE.exists():
        raise RuntimeError(f"Cannot upload: state file is missing at {STATE_FILE}")
    config_data = CONFIG_FILE.read_bytes()
    state_data = STATE_FILE.read_bytes()
    validate_config(config_data)
    validate_state(state_data)
    s3 = b2_client()
    bucket = os.environ["B2_BUCKET"]
    s3.put_object(Bucket=bucket, Key=CONFIG_KEY, Body=config_data, ContentType="text/yaml")
    s3.put_object(Bucket=bucket, Key=STATE_KEY, Body=state_data, ContentType="application/json")
    print(f"[B2] Uploaded {CONFIG_KEY} and {STATE_KEY}.")


command = os.environ.get("B2_COMMAND", "")
try:
    if command == "download":
        download()
    elif command == "upload":
        upload()
    else:
        raise RuntimeError("Set B2_COMMAND to download or upload")
except Exception as error:
    print(f"[B2] KSE sync failed: {error}")
    raise SystemExit(1)
