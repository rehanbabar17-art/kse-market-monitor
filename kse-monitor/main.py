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
import hashlib
import json
import os
import sys

import yaml
import pytz

from fetcher import fetch_all, fetch_psx_status
from notifier import send_ntfy, format_interval_update, format_eod_summary


DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_INDEX = {k: i for i, k in enumerate(DAY_KEYS)}
MARKET_TIMEZONE = "Asia/Karachi"
TRADING_WINDOWS = {
    "mon": [[9, 17]],
    "tue": [[9, 17]],
    "wed": [[9, 17]],
    "thu": [[9, 17]],
    "fri": [[9, 13], [14, 17]],
}


def load_config(path: str = None) -> dict:
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "config.yaml")
    with open(path) as f:
        raw = f.read()
    for k, v in os.environ.items():
        raw = raw.replace(f"${{{k}}}", v)
    loaded = yaml.safe_load(raw) or {}
    symbols = loaded.get("stocks", [])
    if not symbols or not isinstance(symbols, list):
        raise ValueError("B2 configuration must contain a non-empty stocks list")
    normalized = []
    for item in symbols:
        symbol = item if isinstance(item, str) else item.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("Every configured stock must be a symbol string")
        normalized.append(symbol.strip().upper())
    return {"stocks": normalized}


# ── state helpers ──────────────────────────────────────────────────
def _state_path() -> str:
    return os.environ.get(
        "KSE_STATE_FILE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "last_eod.json"),
    )


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


def _sent_on(state: dict) -> set:
    return set(state.get("eod_sent", []))


def _mark_sent(state: dict, composite_key: str):
    sents = state.get("eod_sent", [])
    if composite_key not in sents:
        sents.append(composite_key)
    state["eod_sent"] = sents


def _interval_signature(data: dict, date_str: str) -> str:
    """Create a timestamp-free fingerprint of the interval alert contents.

    The date is included so an unchanged closing snapshot on a new trading day
    still produces that day's first update. Fields shown in interval messages
    are included; notification timestamps are intentionally excluded.
    """
    kse = data.get("kse100", {})
    kse_snapshot = {
        key: kse.get(key)
        for key in ("price", "change", "change_pct", "volume", "high", "low", "error")
        if key in kse
    }
    stocks_snapshot = []
    for stock in data.get("stocks", []):
        stocks_snapshot.append({
            key: stock.get(key)
            for key in (
                "symbol", "name", "price", "change", "change_pct", "error"
            )
            if key in stock
        })
    payload = {"date": date_str, "kse100": kse_snapshot, "stocks": stocks_snapshot}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _interval_was_sent(state: dict, date_str: str, signature: str) -> bool:
    """Return whether this exact interval snapshot was already delivered today."""
    previous = state.get("last_interval", {})
    return (
        isinstance(previous, dict)
        and previous.get("date") == date_str
        and previous.get("signature") == signature
    )


def _mark_interval_sent(state: dict, date_str: str, signature: str):
    state["last_interval"] = {"date": date_str, "signature": signature}


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
    schedule = config.get("trading_windows", TRADING_WINDOWS)
    for w_open, w_close in _windows_for_day({"trading_windows": schedule}, weekday_index):
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
    tz = pytz.timezone(MARKET_TIMEZONE)
    now = datetime.datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")
    weekday = now.weekday()

    # Weekend → skip
    if weekday >= 5:
        raise StopIteration("weekend")

    windows = _windows_for_day({"trading_windows": TRADING_WINDOWS}, weekday)
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
def _is_market_hours(config: dict) -> bool:
    tz = pytz.timezone(MARKET_TIMEZONE)
    now = datetime.datetime.now(tz)
    win = _current_window(config, now.hour, now.weekday())
    return win is not None


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

    tz = pytz.timezone(MARKET_TIMEZONE)
    now = datetime.datetime.now(tz)
    timestamp = now.strftime("%d %b %Y, %I:%M %p %Z")

    if args.mode == "summary":
        title, body = format_eod_summary(data, timestamp, label=summary_label)
    else:
        date_str = now.strftime("%Y-%m-%d")
        interval_signature = _interval_signature(data, date_str)
        state = _load_state()
        if (
            args.mode == "interval"
            and not args.force
            and _interval_was_sent(state, date_str, interval_signature)
        ):
            print("Skipping interval alert — market snapshot unchanged.")
            sys.exit(0)
        title, body = format_interval_update(data, timestamp)

    server = "https://ntfy.sh"
    topic = os.environ.get("NTFY_TOPIC", "")

    if not topic or "${" in topic:
        print("ERROR: NTFY_TOPIC not configured. Add the GitHub secret.")
        sys.exit(1)

    priority = 4 if args.mode == "summary" else 3
    ok = send_ntfy(server, topic, title, body, priority=priority,
                   tags=["chart_with_upwards_trend"])
    if not ok:
        print("Failed to send notification.")
        sys.exit(1)

    if args.mode == "interval":
        _mark_interval_sent(state, date_str, interval_signature)
        _save_state(state)

    label = f"{summary_label} Summary" if args.mode == "summary" else "Update"
    print(f"{label} sent to ntfy://{topic}")


if __name__ == "__main__":
    main()
