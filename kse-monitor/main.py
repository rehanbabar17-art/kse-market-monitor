#!/usr/bin/env python3
"""
KSE Monitor — Main Entry Point

Fetches KSE 100 + listed PSX stocks. Sends updates via ntfy.

Modes:
    interval  — market update
    summary   — end-of-session summary
    auto      — decides automatically per trading window:
                interval while a window is active, summary once
                per window close, nothing otherwise
"""

import argparse
import datetime
import json
import os
import sys

import yaml
import pytz

from fetcher import fetch_all, fetch_psx_status
from notifier import send_ntfy, format_interval_update, format_eod_summary


DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_INDEX = {k: i for i, k in enumerate(DAY_KEYS)}


def load_config(path: str = None) -> dict:
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "config.yaml")
    with open(path) as f:
        raw = f.read()
    for k, v in os.environ.items():
        raw = raw.replace(f"${{{k}}}", v)
    return yaml.safe_load(raw)


# ── state helpers ──────────────────────────────────────────────────
def _state_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "state", "last_eod.json")


def _load_state() -> dict:
    try:
        with open(_state_path()) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict):
    os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
    with open(_state_path(), "w") as f:
        json.dump(state, f)


def _last_check_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "state", "last_check.json")


def _load_last_check() -> dict:
    try:
        with open(_last_check_path()) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_last_check(data: dict):
    os.makedirs(os.path.dirname(_last_check_path()), exist_ok=True)
    with open(_last_check_path(), "w") as f:
        json.dump(data, f, indent=2)


def has_errors(data: dict) -> bool:
    if not data or not isinstance(data, dict):
        return True
    kse = data.get("kse100")
    if not kse or "error" in kse:
        return True
    stocks = data.get("stocks")
    if stocks is None:
        return True
    for s in stocks:
        if "error" in s:
            return True
    return False


def extract_comparable_state(data: dict) -> dict | None:
    if not data or has_errors(data):
        return None
    kse = data.get("kse100", {})
    kse_state = {
        "price": kse.get("price"),
        "change": kse.get("change"),
        "change_pct": kse.get("change_pct"),
        "volume": kse.get("volume"),
        "high": kse.get("high"),
        "low": kse.get("low"),
    }
    stocks_state = []
    for s in sorted(data.get("stocks", []), key=lambda x: x.get("symbol", "")):
        stocks_state.append({
            "symbol": s.get("symbol"),
            "price": s.get("price"),
            "change": s.get("change"),
            "change_pct": s.get("change_pct"),
            "volume": s.get("volume"),
            "high": s.get("high"),
            "low": s.get("low"),
        })
    return {
        "kse100": kse_state,
        "stocks": stocks_state,
    }


def is_duplicate_data(current_data: dict, last_data: dict) -> bool:
    c_state = extract_comparable_state(current_data)
    l_state = extract_comparable_state(last_data)
    if c_state is None or l_state is None:
        return False
    return c_state == l_state


def _sent_on(state: dict) -> set:
    return set(state.get("eod_sent", []))


def _mark_sent(state: dict, composite_key: str):
    sents = state.get("eod_sent", [])
    if composite_key not in sents:
        sents.append(composite_key)
    state["eod_sent"] = sents


def _purge_old(state: dict, today: str):
    """Remove entries older than today so the file doesn't grow forever."""
    state["eod_sent"] = [
        e for e in state.get("eod_sent", []) if e.startswith(today)
    ]


# ── trading-window logic ──────────────────────────────────────────
def _windows_for_day(config: dict, weekday_index: int) -> list[tuple[int, int]]:
    """Return list of (open_hour, close_hour) for the given weekday."""
    key = DAY_KEYS[weekday_index]
    windows = config.get("trading_windows", {}).get(key, [])
    return [tuple(w) for w in windows]


def _current_window(config: dict, hour: int, weekday_index: int) -> tuple[int, int] | None:
    """Return the active trading window containing `hour`, or None."""
    for w_open, w_close in _windows_for_day(config, weekday_index):
        if w_open <= hour < w_close:
            return (w_open, w_close)
    return None


def _window_id(date_str: str, window: tuple[int, int]) -> str:
    return f"{date_str}_w{window[0]}-{window[1]}"


# ── auto decision ──────────────────────────────────────────────────
def _decide_auto(config: dict) -> tuple[str, bool, str]:
    """
    Returns (mode, persist_eod, window_id)
    Raises StopIteration to signal "skip, nothing to do".
    """
    tz = pytz.timezone(config["market"]["timezone"])
    now = datetime.datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")
    weekday = now.weekday()

    # Weekend → skip
    if weekday >= 5:
        raise StopIteration("weekend")

    windows = _windows_for_day(config, weekday)
    if not windows:
        raise StopIteration(f"no trading windows defined for {DAY_KEYS[weekday]}")

    win = _current_window(config, now.hour, weekday)
    wid = _window_id(date_str, win) if win else None
    state = _load_state()
    _purge_old(state, date_str)

    # ── inside an active trading window → interval update ─────────
    if win:
        _save_state(state)
        return "interval", False, wid or ""

    # ── outside all windows today — check if any window just closed ──
    # Find the most recently closed window (latest close_hour <= now.hour)
    closed_wins = [w for w in windows if now.hour >= w[1]]
    if closed_wins:
        last_closed = closed_wins[-1]
        cw_id = _window_id(date_str, last_closed)
        sent = _sent_on(state)
        if cw_id not in sent:
            _mark_sent(state, cw_id)
            _save_state(state)
            return "summary", False, cw_id
        raise StopIteration("summary already sent for this window")

    raise StopIteration("before market hours")


# ── market hours (non-auto) ───────────────────────────────────────
def is_market_hours(config: dict) -> bool:
    tz = pytz.timezone(config["market"]["timezone"])
    now = datetime.datetime.now(tz)
    win = _current_window(config, now.hour, now.weekday())
    return win is not None


_is_market_hours = is_market_hours


# ── main ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="KSE Monitor")
    parser.add_argument("--mode", choices=["interval", "summary", "auto"],
                        default="interval")
    parser.add_argument("--config", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    persist_eod = False
    summary_label = "EOD"

    if args.mode == "auto":
        try:
            args.mode, persist_eod, win_id = _decide_auto(config)
            if "_w9-13" in win_id:
                summary_label = "Midday"
        except StopIteration as e:
            print(f"Auto: skipping — {e}")
            sys.exit(0)
    elif not args.force and not _is_market_hours(config):
        print("Outside market hours. Use --force to send anyway.")
        sys.exit(0)

    print(f"Fetching market data (mode={args.mode})...")
    data = fetch_all(stocks=config["stocks"])

    if args.mode == "interval" and not args.force:
        if has_errors(data):
            print("Skipping update — fetch data contains errors")
            sys.exit(0)
        last_data = _load_last_check()
        if is_duplicate_data(data, last_data):
            print("Skipping update — duplicate market data (no price changes)")
            sys.exit(0)

    tz = pytz.timezone(config["market"]["timezone"])
    now = datetime.datetime.now(tz)
    timestamp = now.strftime("%d %b %Y, %I:%M %p %Z")

    if args.mode == "summary":
        title, body = format_eod_summary(data, timestamp, label=summary_label)
    else:
        title, body = format_interval_update(data, timestamp)

    server = config["ntfy"]["server"]
    topic = config["ntfy"]["topic"]

    if not topic or "${" in topic:
        print("ERROR: NTFY_TOPIC not configured. Add the GitHub secret.")
        sys.exit(1)

    priority = 4 if args.mode == "summary" else 3
    ok = send_ntfy(server, topic, title, body, priority=priority,
                   tags=["chart_with_upwards_trend"])
    if not ok:
        print("Failed to send notification.")
        sys.exit(1)

    if not has_errors(data):
        _save_last_check(data)

    label = f"{summary_label} Summary" if args.mode == "summary" else "Update"
    print(f"{label} sent to ntfy://{topic}")


if __name__ == "__main__":
    main()
