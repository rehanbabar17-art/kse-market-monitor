import requests


def send_ntfy(server: str, topic: str, title: str, message: str,
              priority: int = 3, tags: list = None) -> bool:
    """Send a notification via ntfy.sh."""
    url = f"{server}/{topic}"
    headers = {
        "Title": title.encode("ascii", "replace").decode(),
        "Priority": str(priority),
        "Tags": ",".join(tags) if tags else "",
    }
    try:
        resp = requests.post(url, data=message.encode("utf-8"),
                             headers=headers, timeout=30)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"ntfy send failed: {e}")
        return False


def _fmt_price(val) -> str:
    return f"{val:,.2f}" if val is not None else "N/A"


def format_interval_update(data: dict, timestamp: str) -> tuple[str, str]:
    """Interval update. Returns (title, body)."""
    lines = [f"\U0001f4ca KSE Market Update \u2014 {timestamp}", ""]

    kse = data["kse100"]
    if "error" in kse:
        lines.append(f"\u26a0\ufe0f KSE 100: Error \u2014 {kse['error']}")
    else:
        kse_change = kse.get("change") if kse.get("change") is not None else 0
        kse_pct = kse.get("change_pct") if kse.get("change_pct") is not None else 0
        arrow = "\U0001f7e2" if kse_change >= 0 else "\U0001f534"
        lines.append("\U0001f4c8 KSE 100 Index")
        lines.append(
            f"  {arrow} Price: {_fmt_price(kse.get('price'))} | "
            f"Change: {kse_change:+.2f} ({kse_pct:+.2f}%)"
        )
        if kse.get("volume"):
            lines.append(f"  \U0001f4ca Volume: {kse['volume']:,}")
        if kse.get("high") is not None and kse.get("low") is not None:
            lines.append(
                f"  \u2b06\ufe0f High: {kse['high']:,.2f} | "
                f"\u2b07\ufe0f Low: {kse['low']:,.2f}"
            )
        lines.append("")

    if data["stocks"]:
        lines.append("\U0001f4c9 Your Stocks")
        for s in data["stocks"]:
            if "error" in s:
                lines.append(f"  \u26a0\ufe0f {s['name']} ({s['symbol']}): {s['error']}")
            else:
                chg = s.get("change") if s.get("change") is not None else 0
                pct = s.get("change_pct") if s.get("change_pct") is not None else 0
                arrow = "\U0001f7e2" if chg >= 0 else "\U0001f534"
                sign = "+" if chg >= 0 else ""
                lines.append(
                    f"  {arrow} {s['name']} ({s['symbol']}): "
                    f"{_fmt_price(s.get('price'))} | {sign}{chg:.2f} ({sign}{pct:.2f}%)"
                )
                if s.get("high") is not None or s.get("low") is not None:
                    lines.append(
                        f"    \u2b06\ufe0f High: {_fmt_price(s.get('high'))} | "
                        f"\u2b07\ufe0f Low: {_fmt_price(s.get('low'))}"
                    )
        lines.append("")

    title = f"KSE Market Update \u2014 {timestamp}"
    return title, "\n".join(lines)


def format_eod_summary(data: dict, timestamp: str,
                       label: str = "EOD") -> tuple[str, str]:
    """End-of-session summary. Returns (title, body).
    label: 'EOD' for final close, 'Midday' for Friday Jumma break.
    """
    emoji = "\U0001f3c1" if label == "EOD" else "\U0001f55b"
    lines = [f"{emoji} {label} Summary \u2014 {timestamp}", ""]

    kse = data["kse100"]
    if "error" in kse:
        lines.append(f"\u26a0\ufe0f KSE 100: Error \u2014 {kse['error']}")
    else:
        kse_change = kse.get("change") if kse.get("change") is not None else 0
        kse_pct = kse.get("change_pct") if kse.get("change_pct") is not None else 0
        lines.append(f"\U0001f4c8 KSE 100 Index \u2014 {label}")
        lines.append(f"  \U0001f4ca Close: {_fmt_price(kse.get('price'))}")
        lines.append(f"  Change: {kse_change:+.2f} ({kse_pct:+.2f}%)")
        if kse.get("volume"):
            lines.append(f"  \U0001f4ca Volume: {kse['volume']:,}")
        if kse.get("high") is not None and kse.get("low") is not None:
            lines.append(
                f"  \u2b06\ufe0f Day High: {kse['high']:,.2f} | "
                f"\u2b07\ufe0f Day Low: {kse['low']:,.2f}"
            )
        lines.append("")

    if data["stocks"]:
        lines.append(f"\U0001f4c9 Your Portfolio \u2014 {label}")
        lines.append("")
        gainers = [s for s in data["stocks"]
                   if "error" not in s and (s.get("change") or 0) > 0]
        losers = [s for s in data["stocks"]
                  if "error" not in s and (s.get("change") or 0) < 0]

        for s in data["stocks"]:
            if "error" in s:
                lines.append(
                    f"  \u26a0\ufe0f {s['name']} ({s['symbol']}): {s['error']}"
                )
            else:
                chg = s.get("change") if s.get("change") is not None else 0
                pct = s.get("change_pct") if s.get("change_pct") is not None else 0
                arrow = "\U0001f7e2" if chg >= 0 else "\U0001f534"
                sign = "+" if chg >= 0 else ""
                lines.append(
                    f"  {arrow} {s['name']} ({s['symbol']}): "
                    f"{_fmt_price(s.get('price'))} | {sign}{chg:.2f} ({sign}{pct:.2f}%)"
                )
                if s.get("high") is not None or s.get("low") is not None:
                    vol = f" | \U0001f4ca Vol: {s['volume']:,}" if s.get("volume") else ""
                    lines.append(
                        f"    \u2b06\ufe0f High: {_fmt_price(s.get('high'))} | "
                        f"\u2b07\ufe0f Low: {_fmt_price(s.get('low'))}{vol}"
                    )
        lines.append("")
        lines.append(
            f"\U0001f4ca Summary: {len(gainers)} gainers | {len(losers)} losers"
        )

    lines.append("")
    lines.append("\U0001f305 See you next session! \U0001f4c8")

    title = f"KSE {label} Summary \u2014 {timestamp}"
    return title, "\n".join(lines)
