import re
import json
import requests


def _parse_market_watch() -> dict:
    """
    Scrape the PSX DPS market-watch page for all listed stocks.
    Returns a dict keyed by symbol.
    """
    resp = requests.get(
        "https://dps.psx.com.pk/market-watch",
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    html = resp.text

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    stocks = {}
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        cleaned = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if len(cleaned) < 11:
            continue
        symbol, _sector, listed_in, ldcp, _open, high, low, current, change, change_pct, volume = cleaned[:11]
        if not symbol or not current:
            continue
        stocks[symbol] = {
            "symbol": symbol,
            "listed_in": listed_in,
            "ldcp": _parse_num(ldcp),
            "open": _parse_num(_open),
            "high": _parse_num(high),
            "low": _parse_num(low),
            "price": _parse_num(current),
            "change": _parse_num(change),
            "change_pct": _parse_num(change_pct.replace("%", "")),
            "volume": _parse_num(volume, as_int=True),
        }
    return stocks


def _parse_futures(month: str) -> dict:
    """
    Scrape PSX futures for a given month from the PSX website.
    Returns a dict keyed by futures symbol (e.g. 'MLCF-SEP').
    """
    session = requests.Session()
    session.get("https://www.psx.com.pk/", timeout=10,
                headers={"User-Agent": "Mozilla/5.0"})

    url = "https://www.psx.com.pk/psx/market-summary/future-contract-ajax"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.psx.com.pk/psx/market-summary/future-contracts",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.psx.com.pk",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    r = session.post(url, data={"month": month, "limit": 0},
                     timeout=15, headers=headers)
    r.raise_for_status()

    if "No Data found" in r.text:
        return {}

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.DOTALL)
    futures = {}
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        cleaned = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if len(cleaned) < 7:
            continue
        symbol, _open, high, low, current, change, volume = cleaned[:7]
        if not symbol or not current:
            continue
        price_val = _parse_num(current)
        change_val = _parse_num(change)
        ldcp_val = (price_val - change_val) if price_val and change_val else None
        pct = round((change_val / ldcp_val * 100), 2) if ldcp_val else 0
        futures[symbol] = {
            "symbol": symbol,
            "listed_in": f"FUTURES-{month}",
            "ldcp": ldcp_val,
            "open": _parse_num(_open),
            "high": _parse_num(high),
            "low": _parse_num(low),
            "price": price_val,
            "change": change_val,
            "change_pct": pct,
            "volume": _parse_num(volume, as_int=True),
        }
    return futures


def _parse_num(val: str, as_int: bool = False):
    if not val:
        return None
    cleaned = val.replace(",", "").replace("%", "").strip()
    try:
        return int(float(cleaned)) if as_int else float(cleaned)
    except (ValueError, OverflowError):
        return None


def _fetch_investify_fallback(symbol: str) -> dict | None:
    """
    Fallback: fetch a single stock from investify.pk/company/SYMBOL/quote.
    Extracts data from the embedded Next.js RSC payload.
    Returns stock dict or None if not available.
    """
    url = f"https://www.investify.pk/company/{symbol}/quote"
    try:
        resp = requests.get(url, timeout=15,
                            headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None
        text = resp.text

        # The stock data lives in a __next_f.push block as escaped JSON
        # Pattern: "stock":{"sym":"SYMBOL","c":price,"ch":change,...}
        push_blocks = re.findall(
            r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', text, re.DOTALL
        )

        for block in push_blocks:
            unescaped = block.replace('\\"', '"')
            # Extract the stock object
            m = re.search(r'"stock":\{[^}]*"sym":"' + re.escape(symbol) + r'"[^}]*\}', unescaped)
            if not m:
                continue

            json_str = m.group(0).replace('"stock":', "", 1)
            # Clean up any JS references (like ,f:f)
            json_str = re.sub(r',\s*"[a-z]+":\s*[a-z](?=[,}])', "", json_str)
            json_str = re.sub(r',\}', "}", json_str)

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            price = data.get("c")
            change = data.get("ch")
            ldcp = data.get("ldcp")
            if price is None:
                continue

            change_pct = round((change / ldcp * 100), 2) if ldcp and change is not None else 0

            return {
                "symbol": symbol,
                "listed_in": "INVESTIFY_FALLBACK",
                "ldcp": ldcp,
                "open": data.get("o"),
                "high": data.get("h"),
                "low": data.get("l"),
                "price": round(price, 2),
                "change": round(change, 2) if change is not None else 0,
                "change_pct": change_pct,
                "volume": data.get("v"),
            }

    except Exception:
        pass
    return None


def fetch_kse100(all_stocks: dict = None) -> dict:
    """Fetch KSE 100 index from PSX website."""
    try:
        resp = requests.get(
            "https://www.psx.com.pk/",
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        html = resp.text

        def extract(field_id: str):
            m = re.search(rf'id="{field_id}"[^>]*>([^<]+)<', html)
            return m.group(1).strip() if m else None

        price = _parse_num(extract("curIndex"))
        change = _parse_num(extract("cahnge"))
        change_pct = _parse_num(extract("percentchange"))
        high = _parse_num(extract("high"))
        low = _parse_num(extract("low"))
        volume = _parse_num(extract("volume"), as_int=True)

        if price is not None:
            return {
                "symbol": "KSE100", "name": "KSE 100 Index",
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume": volume,
                "high": round(high, 2) if high else None,
                "low": round(low, 2) if low else None,
            }
    except Exception:
        pass

    if all_stocks is None:
        all_stocks = _parse_market_watch()

    kse_stocks = [s for s in all_stocks.values()
                  if "KSE100" in (s.get("listed_in") or "")]
    if not kse_stocks:
        return {"symbol": "KSE100", "name": "KSE 100 Index",
                "error": "Could not fetch KSE 100 data"}

    total_ldcp = sum(s["ldcp"] or 0 for s in kse_stocks)
    total_current = sum(s["price"] or 0 for s in kse_stocks)
    total_high = sum(s["high"] or 0 for s in kse_stocks)
    total_low = sum(s["low"] or 0 for s in kse_stocks)
    total_vol = sum(s["volume"] or 0 for s in kse_stocks)
    change = total_current - total_ldcp
    change_pct = (change / total_ldcp * 100) if total_ldcp else 0

    return {
        "symbol": "KSE100", "name": "KSE 100 Index",
        "price": round(total_current, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "volume": total_vol,
        "high": round(total_high, 2),
        "low": round(total_low, 2),
    }


def _is_futures_symbol(symbol: str) -> bool:
    """Check if a symbol looks like a futures contract (e.g. MLCF-SEP)."""
    return bool(re.match(r"^[A-Z]+-[A-Z]{3}$", symbol.upper()))


def fetch_all(stocks: list) -> dict:
    """
    Fetch KSE 100 + user stocks.
    Strategy per stock:
      1. If futures symbol (X-MON) -> PSX futures API
      2. Else -> PSX DPS market-watch
      3. Fallback -> investify.pk
    """
    futures_needed = {}
    for s in stocks:
        sym = s["symbol"].upper()
        if _is_futures_symbol(sym):
            month = sym.rsplit("-", 1)[1]
            futures_needed.setdefault(month, []).append(sym)

    psx_all = _parse_market_watch()

    all_futures = {}
    for month in futures_needed:
        all_futures.update(_parse_futures(month))

    stock_data = []
    for s in stocks:
        sym = s["symbol"].upper()

        if sym in all_futures:
            d = all_futures[sym]
            stock_data.append(_make_stock_entry(s, d))
            continue

        if sym in psx_all:
            d = psx_all[sym]
            stock_data.append(_make_stock_entry(s, d))
            continue

        fallback = _fetch_investify_fallback(sym)
        if fallback:
            stock_data.append(_make_stock_entry(s, fallback))
        else:
            stock_data.append({
                "symbol": sym, "name": s["name"],
                "error": f"Not found on PSX or Investify (tried: {sym})",
            })

    kse = fetch_kse100(all_stocks=psx_all)
    return {"kse100": kse, "stocks": stock_data}


def _make_stock_entry(config: dict, data: dict) -> dict:
    """Build a stock dict from config entry and scraped data."""
    return {
        "symbol": config["symbol"],
        "name": config["name"],
        "price": data["price"],
        "change": data["change"],
        "change_pct": data["change_pct"],
        "volume": data["volume"],
        "high": data["high"],
        "low": data["low"],
    }
