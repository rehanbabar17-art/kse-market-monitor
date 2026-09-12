#!/usr/bin/env python3
"""
KSE Monitor — Main Entry Point

Fetches KSE 100 index (from PSX website) and your listed PSX stocks.
Sends updates via ntfy.

Modes:
    interval  — half-hourly market update
    summary   — end-of-day summary
    auto      — decides automatically: interval during market hours,
                EOD summary once at close (state persisted via last_eod.txt)
"""

import argparse
import datetime
import os
import sys

import yaml
import pytz

from fetcher import fetch_all
from notifier import send_ntfy, format_interval_update, format_eod_summary


def load_config(path: str = None) -> dict:
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    with open(path, "r") as f:
        raw = f.read()
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)
    return yaml.safe_load(raw)


def _state_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "last_eod.txt")


def _read_last_eod() -> str:
    try:
        with open(_state_path()) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _write_last_eod(date_str: str):
    os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
    with open(_state_path(), "w") as f:
        f.write(date_str)


def _decide_auto(config: dict) -> tuple[str, bool]:
    """
    Decide what to do based on market hours.
    Returns (mode, persist_eod) or raises StopIteration to signal skip.
    """
    tz = pytz.timezone(config["market"]["timezone"])
    now = datetime.datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    weekday_ok = not (config["market"]["weekdays_only"] and now.weekday() >= 5)

    if not weekday_ok:
        raise StopIteration("weekend")

    open_h = config["market"]["open_hour"]
    close_h = config["market"]["close_hour"]

    if open_h <= now.hour < close_h:
        return "interval", False

    if now.hour >= close_h:
        if _read_last_eod() != today:
            return "summary", True
        raise StopIteration("EOD already sent today")

    raise StopIteration("before market hours")


def main():
    parser = argparse.ArgumentParser(description="KSE Monitor")
    parser.add_argument("--mode", choices=["interval", "summary", "auto"],
                        default="interval")
    parser.add_argument("--config", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    persist_eod = False

    if args.mode == "auto":
        try:
            args.mode, persist_eod = _decide_auto(config)
        except StopIteration as e:
            print(f"Auto: skipping — {e}")
            sys.exit(0)
    elif not args.force and not _is_market_hours(config):
        print("Outside market hours. Use --force to send anyway.")
        sys.exit(0)

    print(f"Fetching market data (mode={args.mode})...")
    data = fetch_all(stocks=config["stocks"])

    tz = pytz.timezone(config["market"]["timezone"])
    now = datetime.datetime.now(tz)
    timestamp = now.strftime("%d %b %Y, %I:%M %p %Z")

    if args.mode == "summary":
        title, body = format_eod_summary(data, timestamp)
    else:
        title, body = format_interval_update(data, timestamp)

    server = config["ntfy"]["server"]
    topic = config["ntfy"]["topic"]

    if not topic or "${" in topic:
        print("ERROR: ntfy topic not set. Configure the NTFY_TOPIC secret / env var.")
        sys.exit(1)

    priority = 4 if args.mode == "summary" else 3
    ok = send_ntfy(server, topic, title, body, priority=priority,
                   tags=["chart_with_upwards_trend"])

    if not ok:
        print("Failed to send notification.")
        sys.exit(1)

    label = "Summary" if args.mode == "summary" else "Update"
    print(f"{label} sent to ntfy://{topic}")

    if persist_eod:
        _write_last_eod(now.strftime("%Y-%m-%d"))
        print(f"EOD state saved for {now.strftime('%Y-%m-%d')}")


def _is_market_hours(config: dict) -> bool:
    tz = pytz.timezone(config["market"]["timezone"])
    now = datetime.datetime.now(tz)
    if config["market"]["weekdays_only"] and now.weekday() >= 5:
        return False
    if now.hour < config["market"]["open_hour"] or now.hour >= config["market"]["close_hour"]:
        return False
    return True


if __name__ == "__main__":
    main()
