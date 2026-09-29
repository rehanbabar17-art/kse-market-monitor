import re
import json
import time

import requests


def _retry(fn, *args, attempts: int = 3, backoff: float = 10, **kwargs):
    """Call fn(*args, **kwargs), retrying with exponential backoff."""
    last_err = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.HTTPError,
        ) as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(backoff * (2 ** i))
    raise last_err


def _num(val: str, as_int: bool = False):
    if not val:
        return None

    cleaned = str(val).replace(",", "").replace("%", "").strip()

    try:
        return int(float(cleaned)) if as_int else float(cleaned)
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_market_rows(html: str) -> dict:
    """
    Parse the current PSX Data Portal market-watch table.

    PSX identifies columns using data-name and numeric values using
    data-order/data-value. We therefore parse by column name instead of
    assuming a fixed column position.
    """
    rows = re.findall(
        r"<tr[^>]*>(.*?)</tr>",
        html,
        re.DOTALL | re.IGNORECASE,
    )

    headers = None
    stocks = {}

    def cell_value(attrs: str, body: str) -> str:
        match = re.search(
            r'data-(?:order|value)="([^"]*)"',
            attrs,
            re.IGNORECASE,
        )

        if match:
            return match.group(1).strip()

        return re.sub(r"<[^>]+>", "", body).strip()

    for row in rows:
        cells = re.findall(
            r"<t([dh])([^>]*)>(.*?)</t\1>",
            row,
            re.DOTALL | re.IGNORECASE,
        )

        if not cells:
            continue

        # Header row.
        if cells[0][0].lower() == "h":
            names = []

            for _tag, attrs, _body in cells:
                match = re.search(
                    r'data-name="([^"]+)"',
                    attrs,
                    re.IGNORECASE,
                )

                names.append(match.group(1) if match else "")

            if any(names):
                headers = names

            continue

        if not headers:
            continue

        row_data = {}

        for i, (_tag, attrs, body) in enumerate(cells):
            if i >= len(headers):
                continue

            name = headers[i]

            if not name:
                continue

            row_data[name] = cell_value(attrs, body)

        symbol = row_data.get("symbol", "").upper()
        current = row_data.get("close", "")

        if not symbol or not current:
            continue

        stocks[symbol] = {
            "symbol": symbol,
            "listed_in": row_data.get("listed", ""),
            "ldcp": _num(row_data.get("ldcp")),
            "open": _num(row_data.get("open")),
            "high": _num(row_data.get("high")),
            "low": _num(row_data.get("low")),
            "price": _num(current),
            "change": _num(row_data.get("change")),
            "change_pct": _num(
                row_data.get("percentChange")
            ),
            "volume": _num(
                row_data.get("volume"),
                as_int=True,
            ),
        }

    return stocks


def _parse_market_watch() -> dict:
    """Fetch the current PSX market-wide quote snapshot."""
    try:
        response = _retry(
            requests.get,
            "https://dps.psx.com.pk/market-watch",
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "text/html,application/xhtml+xml",
            },
        )

        response.raise_for_status()

        stocks = _parse_market_rows(response.text)

        if not stocks:
            raise requests.RequestException(
                "PSX market-watch returned no parseable rows"
            )

        print(
            f"PSX market-watch returned {len(stocks)} symbols"
        )

        return stocks

    except requests.RequestException as exc:
        print(
            f"PSX market-watch unavailable ({exc}); "
            "using symbol fallbacks"
        )
        return {}


def _parse_psx_market_summary_rows(html: str) -> dict:
    """Parse regular-equity rows from PSX's official market-summary include."""
    stocks = {}
    rows = re.finditer(
        r'<tr\b[^>]*>(?:(?!<tr\b).)*?data-srip="([^"]+)"'
        r'(?:(?!</tr>).)*?</tr>',
        html,
        re.DOTALL | re.IGNORECASE,
    )

    for match in rows:
        symbol = match.group(1)
        row = match.group(0)
        cells = re.findall(
            r'<td[^>]*>(.*?)</td>',
            row,
            re.DOTALL | re.IGNORECASE,
        )
        values = [re.sub(r'<[^>]+>', '', cell).strip() for cell in cells]
        if len(values) < 9:
            continue

        # A blank cell precedes SCRIP: blank, SCRIP, LDCP, OPEN, HIGH,
        # LOW, CURRENT, CHANGE, VOLUME.
        ldcp, opn, high, low, current, change, volume = values[2:9]
        price = _num(current)
        if price is None:
            continue

        change_value = _num(change)
        ldcp_value = _num(ldcp)

        stocks[symbol.upper()] = {
            "symbol": symbol.upper(),
            "listed_in": "PSX_MARKET_SUMMARY",
            "ldcp": ldcp_value,
            "open": _num(opn),
            "high": _num(high),
            "low": _num(low),
            "price": price,
            "change": change_value,
            "change_pct": (
                round(change_value / ldcp_value * 100, 2)
                if change_value is not None and ldcp_value
                else 0
            ),
            "volume": _num(volume, as_int=True),
        }

    return stocks


def _parse_psx_market_summary() -> dict:
    """Fetch regular-equity quotes from the official PSX market summary."""
    urls = [
        "https://www.psx.com.pk/psx/include71650/new-PSX-market-summary.php",
        "https://www.psx.com.pk/psx/market-summary",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://www.psx.com.pk/psx/market-summary",
        "X-Requested-With": "XMLHttpRequest",
    }

    for url in urls:
        try:
            response = _retry(requests.get, url, timeout=30, headers=headers)
            response.raise_for_status()
            stocks = _parse_psx_market_summary_rows(response.text)
            if stocks:
                print(f"PSX market summary returned {len(stocks)} symbols from {url}")
                return stocks
        except requests.RequestException as exc:
            print(f"PSX market summary unavailable ({url}: {exc})")

    return {}


def _parse_futures(month: str) -> dict:
    """Scrape PSX futures for a given month."""
    session = requests.Session()

    session.get(
        "https://www.psx.com.pk/",
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": (
            "https://www.psx.com.pk/"
            "psx/market-summary/future-contracts"
        ),
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.psx.com.pk",
        "Content-Type": (
            "application/x-www-form-urlencoded; charset=UTF-8"
        ),
    }

    response = _retry(
        session.post,
        "https://www.psx.com.pk/"
        "psx/market-summary/future-contract-ajax",
        data={
            "month": month,
            "limit": 0,
        },
        timeout=15,
        headers=headers,
    )

    response.raise_for_status()

    if "No Data found" in response.text:
        return {}

    rows = re.findall(
        r"<tr[^>]*>(.*?)</tr>",
        response.text,
        re.DOTALL,
    )

    futures = {}

    for row in rows:
        cells = re.findall(
            r"<td[^>]*>(.*?)</td>",
            row,
            re.DOTALL,
        )

        values = [
            re.sub(r"<[^>]+>", "", x).strip()
            for x in cells
        ]

        if len(values) < 7:
            continue

        symbol, opn, hi, lo, cur, chg, vol = values[:7]

        if not symbol or not cur:
            continue

        price = _num(cur)
        change = _num(chg)

        if price is None:
            continue

        ldcp = (
            price - change
            if change is not None
            else None
        )

        pct = (
            round(change / ldcp * 100, 2)
            if ldcp
            and change is not None
            else 0
        )

        futures[symbol.upper()] = {
            "symbol": symbol.upper(),
            "listed_in": f"FUTURES-{month}",
            "ldcp": ldcp,
            "open": _num(opn),
            "high": _num(hi),
            "low": _num(lo),
            "price": price,
            "change": change or 0,
            "change_pct": pct,
            "volume": _num(vol, as_int=True),
        }

    return futures


def fetch_psx_status() -> str:
    """Fetch current market status from PSX."""
    try:
        response = _retry(
            requests.get,
            "https://www.psx.com.pk/",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )

        match = re.search(
            r"Market Status.*?<td[^>]*>\s*([^<]+)",
            response.text,
            re.DOTALL | re.IGNORECASE,
        )

        return (
            match.group(1).strip()
            if match
            else "Unknown"
        )

    except Exception:
        return "Unknown"


def _parse_kse100_html(html: str) -> dict | None:
    """Parse KSE-100 from current DPS table or homepage markup."""
    row = re.search(
        r'<tr[^>]*>.*?data-code="KSE100".*?</tr>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if row:
        orders = re.findall(
            r'<td[^>]*data-order="([^"]+)"',
            row.group(0),
            re.IGNORECASE,
        )
        if len(orders) >= 5:
            price = _num(orders[2])
            change = _num(orders[3])
            change_pct = _num(orders[4])
            if price is not None:
                return {
                    "symbol": "KSE100",
                    "name": "KSE 100 Index",
                    "price": round(price, 2),
                    "change": round(change, 2) if change is not None else 0,
                    "change_pct": round(change_pct, 2) if change_pct is not None else 0,
                    "volume": None,
                    "high": _num(orders[0]),
                    "low": _num(orders[1]),
                }

    current = re.search(
        r'topIndices__item__name">KSE100</div>.*?'
        r'topIndices__item__val">([^<]+).*?'
        r'topIndices__item__change">.*?</i>\s*([^<]+).*?'
        r'topIndices__item__changep">\(([^)]+)%\)',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if current:
        price = _num(current.group(1))
        change = _num(current.group(2))
        change_pct = _num(current.group(3))
        if price is not None:
            return {
                "symbol": "KSE100",
                "name": "KSE 100 Index",
                "price": round(price, 2),
                "change": round(change, 2) if change is not None else 0,
                "change_pct": round(change_pct, 2) if change_pct is not None else 0,
                "volume": None,
                "high": None,
                "low": None,
            }

    return None


def fetch_kse100(all_stocks: dict = None) -> dict:
    """Fetch KSE-100 from the PSX Data Portal."""

    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
    }

    # DPS may intermittently close one route to automated runners. Try both
    # the dedicated indices page and the portal homepage before leaving DPS.
    for url in (
        "https://dps.psx.com.pk/indices",
        "https://dps.psx.com.pk/",
    ):
        try:
            response = _retry(requests.get, url, timeout=20, headers=headers)
            response.raise_for_status()
            parsed = _parse_kse100_html(response.text)
            if parsed:
                return parsed
        except requests.RequestException as exc:
            print(f"DPS KSE100 source unavailable ({url}: {exc})")

    # Current PSX Data Portal indices page.
    try:
        response = _retry(
            requests.get,
            "https://dps.psx.com.pk/indices",
            timeout=20,
            headers=headers,
        )

        response.raise_for_status()

        # Current indices table: high, low, current, change, percent change.
        row = re.search(
            r'<tr[^>]*>.*?data-code="KSE100".*?</tr>',
            response.text,
            re.DOTALL | re.IGNORECASE,
        )
        if row:
            orders = re.findall(
                r'<td[^>]*data-order="([^"]+)"',
                row.group(0),
                re.IGNORECASE,
            )
            if len(orders) >= 5:
                price = _num(orders[2])
                change = _num(orders[3])
                change_pct = _num(orders[4])
                if price is not None:
                    return {
                        "symbol": "KSE100",
                        "name": "KSE 100 Index",
                        "price": round(price, 2),
                        "change": round(change, 2) if change is not None else 0,
                        "change_pct": round(change_pct, 2) if change_pct is not None else 0,
                        "volume": None,
                        "high": _num(orders[0]),
                        "low": _num(orders[1]),
                    }

        text = re.sub(
            r"<[^>]+>",
            " | ",
            response.text,
        )

        text = re.sub(r"\s+", " ", text)

        match = re.search(
            r"KSE100\s*\|\s*"
            r"([\d,]+(?:\.\d+)?)\s*\|\s*"
            r"([+-]?[\d,]+(?:\.\d+)?)\s*\|\s*"
            r"\(?\s*([+-]?[\d.]+)\s*%?\s*\)?",
            text,
            re.IGNORECASE,
        )

        if match:
            price = _num(match.group(1))
            change = _num(match.group(2))
            change_pct = _num(match.group(3))

            if price is not None:
                return {
                    "symbol": "KSE100",
                    "name": "KSE 100 Index",
                    "price": round(price, 2),
                    "change": (
                        round(change, 2)
                        if change is not None
                        else 0
                    ),
                    "change_pct": (
                        round(change_pct, 2)
                        if change_pct is not None
                        else 0
                    ),
                    "volume": None,
                    "high": None,
                    "low": None,
                }

    except requests.RequestException as exc:
        print(
            f"PSX indices unavailable ({exc}); "
            "trying homepage"
        )

    # Homepage fallback.
    try:
        response = _retry(
            requests.get,
            "https://www.psx.com.pk/",
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )

        response.raise_for_status()

        html = response.text

        match = re.search(
            r'topIndices__item__name">KSE100</div>.*?'
            r'topIndices__item__val">([^<]+).*?'
            r'topIndices__item__change">.*?</i>\s*'
            r'([^<]+).*?'
            r'topIndices__item__changep">\(([^)]+)%\)',
            html,
            re.DOTALL,
        )

        if match:
            price = _num(match.group(1))
            change = _num(match.group(2))
            change_pct = _num(match.group(3))

            if price is not None:
                return {
                    "symbol": "KSE100",
                    "name": "KSE 100 Index",
                    "price": round(price, 2),
                    "change": (
                        round(change, 2)
                        if change is not None
                        else 0
                    ),
                    "change_pct": (
                        round(change_pct, 2)
                        if change_pct is not None
                        else 0
                    ),
                    "volume": None,
                    "high": None,
                    "low": None,
                }

    except requests.RequestException:
        pass

    return {
        "symbol": "KSE100",
        "name": "KSE 100 Index",
        "error": "Could not fetch KSE 100 data",
    }


def _fetch_investify_fallback(symbol: str) -> dict | None:
    """Fallback for a symbol if PSX futures or equity data is unavailable."""
    url = f"https://www.investify.pk/company/{symbol}/quote"

    try:
        response = _retry(
            requests.get,
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )

        if response.status_code != 200:
            return None

        # Current Investify pages expose the quote in the page metadata and
        # FAQ text; older pages also embedded a nested `stock` JSON object.
        quote_match = re.search(
            r"available PSX quote of PKR\s*([\d,]+(?:\.\d+)?)"
            r".*?,\s*(up|down)\s+PKR\s*([\d,]+(?:\.\d+)?)"
            r"\s*\(([+-]?[\d.]+)%\)",
            response.text,
            re.IGNORECASE | re.DOTALL,
        )

        if quote_match:
            price = _num(quote_match.group(1))
            direction = quote_match.group(2).lower()
            abs_change = _num(quote_match.group(3)) or 0
            change = -abs_change if direction == "down" else abs_change
            change_pct = _num(quote_match.group(4)) or 0

            range_match = re.search(
                r"displayed session['’]s range is PKR\s*"
                r"([\d,]+(?:\.\d+)?)\s+to\s+PKR\s*"
                r"([\d,]+(?:\.\d+)?)",
                response.text,
                re.IGNORECASE,
            )
            volume_match = re.search(
                r"reports\s+([\d,]+)\s+shares traded",
                response.text,
                re.IGNORECASE,
            )

            if price is not None:
                return {
                    "symbol": symbol,
                    "listed_in": "INVESTIFY_FALLBACK",
                    "ldcp": round(price - change, 2),
                    "open": None,
                    "high": (
                        _num(range_match.group(2))
                        if range_match else None
                    ),
                    "low": (
                        _num(range_match.group(1))
                        if range_match else None
                    ),
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": (
                        _num(volume_match.group(1), as_int=True)
                        if volume_match else None
                    ),
                }

        push_blocks = re.findall(
            r'self\.__next_f\.push\(\[1,"(.*?)"\]\)',
            response.text,
            re.DOTALL,
        )

        for block in push_blocks:
            unescaped = block.replace('\"', '"')
            idx = unescaped.find('"stock":{')
            if idx == -1:
                continue

            start = idx + len('"stock":')
            brace_count = 0
            end = -1
            for i in range(start, len(unescaped)):
                if unescaped[i] == '{':
                    brace_count += 1
                elif unescaped[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break

            if end == -1:
                continue

            try:
                data = json.loads(unescaped[start:end])
            except json.JSONDecodeError:
                continue

            if data.get("sym", "").upper() != symbol.upper():
                continue

            price = data.get("c")
            change = data.get("ch")
            ldcp = data.get("ldcp")

            if price is None:
                continue

            return {
                "symbol": symbol,
                "listed_in": "INVESTIFY_FALLBACK",
                "ldcp": ldcp,
                "open": data.get("o"),
                "high": data.get("h"),
                "low": data.get("l"),
                "price": round(price, 2),
                "change": (
                    round(change, 2)
                    if change is not None
                    else 0
                ),
                "change_pct": (
                    round(change / ldcp * 100, 2)
                    if ldcp and change is not None
                    else 0
                ),
                "volume": data.get("v"),
            }

    except Exception:
        pass

    return None


def _is_futures(symbol: str) -> bool:
    return bool(
        re.match(
            r"^[A-Z]+-[A-Z]{3}$",
            symbol.upper(),
        )
    )


def fetch_all(stocks: list) -> dict:
    """Fetch KSE-100 + configured stocks."""

    futures_needed = {}

    for stock in stocks:
        symbol = stock.upper() if isinstance(stock, str) else stock["symbol"].upper()

        if _is_futures(symbol):
            month = symbol.rsplit("-", 1)[1]
            futures_needed.setdefault(
                month,
                [],
            ).append(symbol)

    # Try both official sources. DPS is preferred when available; PSX's
    # market-summary include fills gaps when DPS changes route or blocks bots.
    psx_all = _parse_market_watch()
    official_psx = _parse_psx_market_summary()
    for symbol, quote in official_psx.items():
        psx_all.setdefault(symbol, quote)

    all_futures = {}

    for month in futures_needed:
        try:
            all_futures.update(
                _parse_futures(month)
            )
        except requests.RequestException as exc:
            print(
                f"PSX futures for {month} unavailable: "
                f"{exc}"
            )

    stock_data = []

    for stock in stocks:
        symbol = stock.upper() if isinstance(stock, str) else stock["symbol"].upper()

        # Futures.
        if symbol in all_futures:
            stock_data.append(
                _mk(
                    stock,
                    all_futures[symbol],
                )
            )
            continue

        # Normal PSX equity.
        if symbol in psx_all:
            stock_data.append(
                _mk(
                    stock,
                    psx_all[symbol],
                )
            )
            continue

        # Use Investify fallback for equities or futures.
        fallback = _fetch_investify_fallback(symbol)

        if fallback:
            stock_data.append(
                _mk(
                    stock,
                    fallback,
                )
            )
        else:
            stock_data.append(
                {
                    "symbol": symbol,
                    "name": symbol,
                    "error": (
                        "Symbol not found in DPS market-watch, PSX "
                        f"market summary, or Investify: {symbol}"
                    ),
                }
            )

    kse = fetch_kse100(
        all_stocks=psx_all
    )

    return {
        "kse100": kse,
        "stocks": stock_data,
    }


def _mk(cfg: dict | str, data: dict) -> dict:
    symbol = cfg if isinstance(cfg, str) else cfg["symbol"]
    return {
        "symbol": symbol,
        "name": data.get("name") or data.get("company") or symbol,
        "price": data["price"],
        # PSX reports blank change values for symbols with no trade/change.
        # Normalize them before notifier.py compares the value numerically.
        "change": data.get("change") if data.get("change") is not None else 0,
        "change_pct": data.get("change_pct") if data.get("change_pct") is not None else 0,
        "volume": data["volume"],
        "high": data["high"],
        "low": data["low"],
    }
