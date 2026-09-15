import re
import json
import time

import requests


def _retry(fn, attempts: int = 3, backoff: float = 120, *args, **kwargs):
    """Call fn(*args, **kwargs), retrying with exponential backoff."""
    last_err = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.HTTPError) as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(backoff * (2 ** i))
    raise last_err


def _parse_market_watch() -> dict:
    """Scrape PSX DPS market-watch page for all listed stocks."""
    resp = _retry(requests.get,
                 "https://dps.psx.com.pk/market-watch",
                 timeout=30,
                 headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    html = resp.text
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    stocks = {}
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        c = [re.sub(r"<[^>]+>", "", x).strip() for x in cells]
        if len(c) < 11:
            continue
        sym, _sec, listed, ldcp, opn, hi, lo, cur, chg, pct, vol = c[:11]
        if not sym or not cur:
            continue
        stocks[sym] = {
            "symbol": sym, "listed_in": listed,
            "ldcp": _num(ldcp), "open": _num(opn), "high": _num(hi),
            "low": _num(lo), "price": _num(cur), "change": _num(chg),
            "change_pct": _num(pct.replace("%", "")),
            "volume": _num(vol, as_int=True),
        }
    return stocks


def _parse_futures(month: str) -> dict:
    """Scrape PSX futures for a given month."""
    sess = requests.Session()
    sess.get("https://www.psx.com.pk/", timeout=10,
             headers={"User-Agent": "Mozilla/5.0"})
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.psx.com.pk/psx/market-summary/future-contracts",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.psx.com.pk",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    r = _retry(sess.post,
               "https://www.psx.com.pk/psx/market-summary/future-contract-ajax",
               data={"month": month, "limit": 0}, timeout=15, headers=headers)
    r.raise_for_status()
    if "No Data found" in r.text:
        return {}
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.DOTALL)
    futures = {}
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        c = [re.sub(r"<[^>]+>", "", x).strip() for x in cells]
        if len(c) < 7:
            continue
        sym, opn, hi, lo, cur, chg, vol = c[:7]
        if not sym or not cur:
            continue
        p, ch = _num(cur), _num(chg)
        ldcp = (p - ch) if p and ch else None
        pct = round(ch / ldcp * 100, 2) if ldcp else 0
        futures[sym] = {
            "symbol": sym, "listed_in": f"FUTURES-{month}", "ldcp": ldcp,
            "open": _num(opn), "high": _num(hi), "low": _num(lo),
            "price": p, "change": ch, "change_pct": pct,
            "volume": _num(vol, as_int=True),
        }
    return futures


def _num(val: str, as_int: bool = False):
    if not val:
        return None
    cleaned = val.replace(",", "").replace("%", "").strip()
    try:
        return int(float(cleaned)) if as_int else float(cleaned)
    except (ValueError, OverflowError):
        return None


def fetch_psx_status() -> str:
    """Scrape current market status from psx.com.pk ('Open'/'Closed')."""
    try:
        r = _retry(requests.get, "https://www.psx.com.pk/", timeout=15,
                   headers={"User-Agent": "Mozilla/5.0"})
        m = re.search(r"Market Status.*?<td[^>]*>\s*([^<]+)", r.text,
                       re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else "Unknown"
    except Exception:
        return "Unknown"


def fetch_kse100(all_stocks: dict = None) -> dict:
    """Fetch KSE 100 index from PSX main page."""
    try:
        r = _retry(requests.get, "https://www.psx.com.pk/", timeout=20,
                   headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        html = r.text

        def ex(fid):
            m = re.search(rf'id="{fid}"[^>]*>([^<]+)<', html)
            return m.group(1).strip() if m else None

        p = _num(ex("curIndex"))
        ch = _num(ex("cahnge"))
        cp = _num(ex("percentchange"))
        hi = _num(ex("high"))
        lo = _num(ex("low"))
        vol = _num(ex("volume"), as_int=True)

        if p is not None:
            return {
                "symbol": "KSE100", "name": "KSE 100 Index",
                "price": round(p, 2), "change": round(ch, 2),
                "change_pct": round(cp, 2), "volume": vol,
                "high": round(hi, 2) if hi else None,
                "low": round(lo, 2) if lo else None,
            }
    except Exception:
        pass

    if all_stocks is None:
        all_stocks = _parse_market_watch()
    kse = [s for s in all_stocks.values()
           if "KSE100" in (s.get("listed_in") or "")]
    if not kse:
        return {"symbol": "KSE100", "name": "KSE 100 Index",
                "error": "Could not fetch KSE 100 data"}
    t_ldcp = sum(s["ldcp"] or 0 for s in kse)
    t_cur = sum(s["price"] or 0 for s in kse)
    t_hi = sum(s["high"] or 0 for s in kse)
    t_lo = sum(s["low"] or 0 for s in kse)
    t_vol = sum(s["volume"] or 0 for s in kse)
    ch = t_cur - t_ldcp
    cp = (ch / t_ldcp * 100) if t_ldcp else 0
    return {
        "symbol": "KSE100", "name": "KSE 100 Index",
        "price": round(t_cur, 2), "change": round(ch, 2),
        "change_pct": round(cp, 2), "volume": t_vol,
        "high": round(t_hi, 2), "low": round(t_lo, 2),
    }


def _fetch_investify_fallback(symbol: str) -> dict | None:
    """Fallback: fetch from investify.pk/company/SYMBOL/quote."""
    url = f"https://www.investify.pk/company/{symbol}/quote"
    try:
        resp = _retry(requests.get, url, timeout=15,
                      headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None
        push_blocks = re.findall(
            r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', resp.text, re.DOTALL)
        for block in push_blocks:
            unescaped = block.replace('\\"', '"')
            m = re.search(
                r'"stock":\{[^}]*"sym":"' + re.escape(symbol) + r'"[^}]*\}',
                unescaped)
            if not m:
                continue
            j = m.group(0).replace('"stock":', "", 1)
            j = re.sub(r',\s*"[a-z]+":\s*[a-z](?=[,}])', "", j)
            j = re.sub(r',\}', "}", j)
            try:
                data = json.loads(j)
            except json.JSONDecodeError:
                continue
            price = data.get("c")
            change = data.get("ch")
            ldcp = data.get("ldcp")
            if price is None:
                continue
            return {
                "symbol": symbol, "listed_in": "INVESTIFY_FALLBACK",
                "ldcp": ldcp, "open": data.get("o"),
                "high": data.get("h"), "low": data.get("l"),
                "price": round(price, 2),
                "change": round(change, 2) if change is not None else 0,
                "change_pct": round(change / ldcp * 100, 2)
                              if ldcp and change is not None else 0,
                "volume": data.get("v"),
            }
    except Exception:
        pass
    return None


def _is_futures(sym: str) -> bool:
    return bool(re.match(r"^[A-Z]+-[A-Z]{3}$", sym.upper()))


def fetch_all(stocks: list) -> dict:
    """Fetch KSE 100 + user stocks with multi-source fallback."""
    futures_needed = {}
    for s in stocks:
        sym = s["symbol"].upper()
        if _is_futures(sym):
            futures_needed.setdefault(sym.rsplit("-", 1)[1], []).append(sym)

    psx_all = _parse_market_watch()
    all_futures = {}
    for m in futures_needed:
        all_futures.update(_parse_futures(m))

    stock_data = []
    for s in stocks:
        sym = s["symbol"].upper()
        if sym in all_futures:
            stock_data.append(_mk(s, all_futures[sym]))
        elif sym in psx_all:
            stock_data.append(_mk(s, psx_all[sym]))
        else:
            fb = _fetch_investify_fallback(sym)
            if fb:
                stock_data.append(_mk(s, fb))
            else:
                stock_data.append({
                    "symbol": sym, "name": s["name"],
                    "error": f"Not found on PSX or Investify (tried: {sym})",
                })

    kse = fetch_kse100(all_stocks=psx_all)
    return {"kse100": kse, "stocks": stock_data}


def _mk(cfg: dict, data: dict) -> dict:
    return {
        "symbol": cfg["symbol"], "name": cfg["name"],
        "price": data["price"], "change": data["change"],
        "change_pct": data["change_pct"], "volume": data["volume"],
        "high": data["high"], "low": data["low"],
    }
