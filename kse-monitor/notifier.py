import requests


def send_ntfy(server: str, topic: str, title: str, message: str,
              priority: int = 3, tags: list = None) -> bool:
    """Send a notification via ntfy.sh (or self-hosted ntfy server)."""
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
    """Format interval update message. Returns (title, body)."""
    lines = [f"📊 KSE Market Update — {timestamp}", ""]

    # KSE 100
    kse = data["kse100"]
    if "error" in kse:
        lines.append(f"⚠️ KSE 100: Error — {kse['error']}")
    else:
        arrow = "🟢" if kse["change"] >= 0 else "🔴"
        lines.append("📈 KSE 100 Index")
        lines.append(
            f"  {arrow} Price: {kse['price']:,.2f} | "
            f"Change: {kse['change']:+.2f} ({kse['change_pct']:+.2f}%)"
        )
        if kse["volume"]:
            lines.append(f"  📊 Volume: {kse['volume']:,}")
        if kse["high"] and kse["low"]:
            lines.append(f"  ⬆️ High: {kse['high']:,.2f} | ⬇️ Low: {kse['low']:,.2f}")
        lines.append("")

    # Stocks
    if data["stocks"]:
        lines.append("📉 Your Stocks")
        for s in data["stocks"]:
            if "error" in s:
                lines.append(f"  ⚠️ {s['name']} ({s['symbol']}): {s['error']}")
            else:
                arrow = "🟢" if s["change"] >= 0 else "🔴"
                sign = "+" if s["change"] >= 0 else ""
                lines.append(
                    f"  {arrow} {s['name']} ({s['symbol']}): "
                    f"{s['price']:,.2f} | {sign}{s['change']:.2f} ({sign}{s['change_pct']:.2f}%)"
                )
        lines.append("")

    title = f"KSE Market Update — {timestamp}"
    return title, "\n".join(lines)


def format_eod_summary(data: dict, timestamp: str) -> tuple[str, str]:
    """Format end-of-day summary. Returns (title, body)."""
    lines = [f"🏁 End of Day Summary — {timestamp}", ""]

    # KSE 100
    kse = data["kse100"]
    if "error" in kse:
        lines.append(f"⚠️ KSE 100: Error — {kse['error']}")
    else:
        lines.append("📈 KSE 100 Index — Daily Summary")
        lines.append(f"  📊 Close: {kse['price']:,.2f}")
        lines.append(f"  Change: {kse['change']:+.2f} ({kse['change_pct']:+.2f}%)")
        if kse["volume"]:
            lines.append(f"  📊 Volume: {kse['volume']:,}")
        if kse["high"] and kse["low"]:
            lines.append(f"  ⬆️ Day High: {kse['high']:,.2f} | ⬇️ Day Low: {kse['low']:,.2f}")
        lines.append("")

    # Stocks
    if data["stocks"]:
        lines.append("📉 Your Portfolio — Daily Summary")
        lines.append("")
        gainers = [s for s in data["stocks"] if "error" not in s and s["change"] > 0]
        losers = [s for s in data["stocks"] if "error" not in s and s["change"] < 0]

        for s in data["stocks"]:
            if "error" in s:
                lines.append(f"  ⚠️ {s['name']} ({s['symbol']}): {s['error']}")
            else:
                arrow = "🟢" if s["change"] >= 0 else "🔴"
                sign = "+" if s["change"] >= 0 else ""
                lines.append(
                    f"  {arrow} {s['name']} ({s['symbol']}): "
                    f"{s['price']:,.2f} | {sign}{s['change']:.2f} ({sign}{s['change_pct']:.2f}%)"
                )
                if s["high"] and s["low"]:
                    vol_str = f" | 📊 Vol: {s['volume']:,}" if s["volume"] else ""
                    lines.append(
                        f"    ⬆️ High: {s['high']:,.2f} | ⬇️ Low: {s['low']:,.2f}{vol_str}"
                    )

        lines.append("")
        lines.append(
            f"📊 Summary: {len(gainers)} gainers | {len(losers)} losers"
        )

    lines.append("")
    lines.append("🌅 Market closed. See you tomorrow! 📈")

    title = f"KSE Daily Summary — {timestamp}"
    return title, "\n".join(lines)
