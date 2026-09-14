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


def format_interval_update(data: dict, timestamp: str) -> tuple[str, str]:
    """Interval update. Returns (title, body)."""
    lines = [f"\U0001f4ca KSE Market Update \u2014 {timestamp}", ""]

    kse = data["kse100"]
    if "error" in kse:
        lines.append(f"\u26a0\ufe0f KSE 100: Error \u2014 {kse['error']}")
    else:
        arrow = "\U0001f7e2" if kse["change"] >= 0 else "\U0001f534"
        lines.append("\U0001f4c8 KSE 100 Index")
        lines.append(
            f"  {arrow} Price: {kse['price']:,.2f} | "
            f"Change: {kse['change']:+.2f} ({kse['change_pct']:+.2f}%)"
        )
        if kse["volume"]:
            lines.append(f"  \U0001f4ca Volume: {kse['volume']:,}")
        if kse["high"] and kse["low"]:
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
                arrow = "\U0001f7e2" if s["change"] >= 0 else "\U0001f534"
                sign = "+" if s["change"] >= 0 else ""
                lines.append(
                    f"  {arrow} {s['name']} ({s['symbol']}): "
                    f"{s['price']:,.2f} | {sign}{s['change']:.2f} ({sign}{s['change_pct']:.2f}%)"
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
        lines.append(f"\U0001f4c8 KSE 100 Index \u2014 {label}")
        lines.append(f"  \U0001f4ca Close: {kse['price']:,.2f}")
        lines.append(f"  Change: {kse['change']:+.2f} ({kse['change_pct']:+.2f}%)")
        if kse["volume"]:
            lines.append(f"  \U0001f4ca Volume: {kse['volume']:,}")
        if kse["high"] and kse["low"]:
            lines.append(
                f"  \u2b06\ufe0f Day High: {kse['high']:,.2f} | "
                f"\u2b07\ufe0f Day Low: {kse['low']:,.2f}"
            )
        lines.append("")

    if data["stocks"]:
        lines.append(f"\U0001f4c9 Your Portfolio \u2014 {label}")
        lines.append("")
        gainers = [s for s in data["stocks"]
                   if "error" not in s and s["change"] > 0]
        losers = [s for s in data["stocks"]
                  if "error" not in s and s["change"] < 0]

        for s in data["stocks"]:
            if "error" in s:
                lines.append(
                    f"  \u26a0\ufe0f {s['name']} ({s['symbol']}): {s['error']}"
                )
            else:
                arrow = "\U0001f7e2" if s["change"] >= 0 else "\U0001f534"
                sign = "+" if s["change"] >= 0 else ""
                lines.append(
                    f"  {arrow} {s['name']} ({s['symbol']}): "
                    f"{s['price']:,.2f} | {sign}{s['change']:.2f} ({sign}{s['change_pct']:.2f}%)"
                )
                if s["high"] and s["low"]:
                    vol = f" | \U0001f4ca Vol: {s['volume']:,}" if s["volume"] else ""
                    lines.append(
                        f"    \u2b06\ufe0f High: {s['high']:,.2f} | "
                        f"\u2b07\ufe0f Low: {s['low']:,.2f}{vol}"
                    )
        lines.append("")
        lines.append(
            f"\U0001f4ca Summary: {len(gainers)} gainers | {len(losers)} losers"
        )

    lines.append("")
    lines.append("\U0001f305 See you next session! \U0001f4c8")

    title = f"KSE {label} Summary \u2014 {timestamp}"
    return title, "\n".join(lines)
