#!/usr/bin/env python3
"""
KSE Monitor — HTTP Server for cron-job.org

Exposes HTTP endpoints that cron-job.org can call:
  GET /interval   -> sends half-hourly market update
  GET /summary    -> sends end-of-day summary
  GET /           -> health check

Required env vars:
  PORT              (default 8080)
  MONITOR_TOKEN     (optional; if set, requests need ?token=... or X-Monitor-Token header)
"""

import datetime
import os
import sys

from flask import Flask, request, jsonify
import pytz

from fetcher import fetch_all
from notifier import send_ntfy, format_interval_update, format_eod_summary
from main import load_config, is_market_hours


app = Flask(__name__)
CONFIG = load_config()
TOKEN = os.environ.get("MONITOR_TOKEN", "")


def _auth_ok() -> bool:
    if not TOKEN:
        return True
    supplied = request.headers.get("X-Monitor-Token", "") or request.args.get("token", "")
    return supplied == TOKEN


def _send(mode: str):
    if not _auth_ok():
        return jsonify({"status": "unauthorized"}), 401

    config = CONFIG
    print("Fetching market data...")
    data = fetch_all(stocks=config["stocks"])

    tz = pytz.timezone(config["market"]["timezone"])
    now = datetime.datetime.now(tz)
    timestamp = now.strftime("%d %b %Y, %I:%M %p %Z")

    if mode == "summary":
        title, body = format_eod_summary(data, timestamp)
    else:
        title, body = format_interval_update(data, timestamp)

    server = config["ntfy"]["server"]
    topic = config["ntfy"]["topic"]

    if not topic:
        return jsonify({"status": "error", "message": "ntfy topic not set"}), 500

    priority = 4 if mode == "summary" else 3
    ok = send_ntfy(server, topic, title, body, priority=priority,
                   tags=["chart_with_upwards_trend"])
    if ok:
        return jsonify({"status": "ok", "mode": mode})
    return jsonify({"status": "error", "message": "ntfy send failed"}), 500


@app.route("/")
def health():
    return jsonify({"status": "alive", "service": "kse-monitor"})


@app.route("/interval")
def interval():
    return _send("interval")


@app.route("/summary")
def summary():
    return _send("summary")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"Starting KSE Monitor server on port {port}")
    print(f"  POST/GET /interval  -> half-hourly update")
    print(f"  POST/GET /summary   -> end-of-day summary")
    app.run(host="0.0.0.0", port=port)
