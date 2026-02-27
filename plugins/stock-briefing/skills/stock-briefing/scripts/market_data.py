#!/usr/bin/env python3
"""
market_data.py — Unified yfinance data collection for the stock briefing skill.

Merges ecosystem signals, short interest, and earnings refresh into a single
script with one yfinance .info call per unique ticker. Returns all data in a
combined JSON envelope.

Usage:
    python market_data.py --tickers NVDA,MRVL,OKLO,CRWV,MOD,LUMN
    python market_data.py --tickers NVDA,MRVL,OKLO,CRWV,MOD,LUMN --config path/to/config.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

try:
    import yfinance as yf
except ImportError:
    yf = None

# --- Configuration ---

HYPERSCALERS = ["MSFT", "GOOG", "META", "AMZN"]
PEERS = {
    "NVDA": ["AVGO", "AMD", "INTC"],
    "MRVL": ["AVGO", "ANET"],
    "OKLO": ["SMR", "NNE"],
    "CRWV": [],
    "MOD": ["VRT", "ETN"],
    "LUMN": ["EQIX"],
}
SUPPLY_CHAIN = ["TSM"]

TOTAL_TIMEOUT = 90
REQUEST_DELAY = 0.3


# --- Data fetching ---

def fetch_all_info(
    tickers: list[str], deadline: float, errors: list[str],
) -> dict[str, dict]:
    """Fetch yfinance .info for all tickers, one call each, with deadline."""
    cache: dict[str, dict] = {}
    for i, ticker in enumerate(sorted(tickers)):
        if time.monotonic() > deadline:
            errors.append(f"{ticker}: global deadline exceeded, skipping remaining")
            break
        if i > 0:
            time.sleep(REQUEST_DELAY)
        try:
            info = yf.Ticker(ticker).info
            cache[ticker] = info if info else {}
        except (ValueError, KeyError, AttributeError, ConnectionError, OSError) as e:
            errors.append(f"{ticker}: yfinance error — {e}")
            cache[ticker] = {}
    return cache


# --- Short interest extraction ---

def extract_short_interest(ticker: str, info: dict) -> dict:
    """Extract short interest fields from a cached .info response."""
    shares_short = info.get("sharesShort")
    shares_short_prior = info.get("sharesShortPriorMonth")
    short_ratio = info.get("shortRatio")
    short_pct_float = info.get("shortPercentOfFloat")
    date_short_interest = info.get("dateShortInterest")

    report_date = None
    if date_short_interest:
        try:
            report_date = datetime.fromtimestamp(
                int(date_short_interest), tz=timezone.utc
            ).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            pass

    change_pct = None
    if shares_short and shares_short_prior and shares_short_prior > 0:
        change_pct = round(
            ((shares_short - shares_short_prior) / shares_short_prior) * 100, 2
        )

    return {
        "shares_short": shares_short,
        "shares_short_prior_month": shares_short_prior,
        "short_ratio": round(short_ratio, 2) if short_ratio else None,
        "short_pct_of_float": (
            round(short_pct_float * 100, 2) if short_pct_float else None
        ),
        "change_pct": change_pct,
        "report_date": report_date,
        "source": "yfinance",
        "available": shares_short is not None,
    }


# --- Ecosystem signals extraction ---

def extract_ecosystem_entry(ticker: str, info: dict) -> dict:
    """Extract ecosystem signal fields from a cached .info response."""
    earnings_ts = info.get("earningsTimestampStart")
    earnings_date = None
    if earnings_ts:
        try:
            earnings_date = datetime.fromtimestamp(
                int(earnings_ts), tz=timezone.utc
            ).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            pass

    revenue_growth = info.get("revenueGrowth")
    earnings_growth = info.get("earningsGrowth")

    return {
        "ticker": ticker,
        "name": info.get("shortName", ticker),
        "next_earnings": earnings_date,
        "revenue_growth_yoy": (
            round(revenue_growth * 100, 1) if revenue_growth else None
        ),
        "earnings_growth_yoy": (
            round(earnings_growth * 100, 1) if earnings_growth else None
        ),
    }


def build_ecosystem_signals(
    watchlist: list[str], info_cache: dict[str, dict], today: date,
) -> dict:
    """Build the ecosystem signals section from cached data."""
    ecosystem_tickers: set[str] = set()
    ecosystem_tickers.update(HYPERSCALERS)
    ecosystem_tickers.update(SUPPLY_CHAIN)
    for ticker in watchlist:
        ecosystem_tickers.update(PEERS.get(ticker, []))

    ecosystem_data: list[dict] = []
    for ticker in sorted(ecosystem_tickers):
        info = info_cache.get(ticker)
        if info is None:
            continue
        if not info:
            continue
        ecosystem_data.append(extract_ecosystem_entry(ticker, info))

    # Separate into upcoming (next 30 days) and recent (past 14 days)
    upcoming: list[dict] = []
    recent_results: list[dict] = []

    for item in ecosystem_data:
        if item.get("next_earnings"):
            try:
                ed = datetime.strptime(item["next_earnings"], "%Y-%m-%d").date()
                days_until = (ed - today).days
                item["days_until_earnings"] = days_until
                if 0 <= days_until <= 30:
                    upcoming.append(item)
                elif -14 <= days_until < 0:
                    recent_results.append(item)
            except ValueError:
                pass

    upcoming.sort(key=lambda x: x.get("days_until_earnings", 999))
    recent_results.sort(
        key=lambda x: x.get("days_until_earnings", -999), reverse=True,
    )

    # Build signals
    signals: list[str] = []
    for item in ecosystem_data:
        if item["ticker"] in HYPERSCALERS:
            rg = item.get("revenue_growth_yoy")
            if rg is not None and rg > 15:
                signals.append(
                    f"{item['ticker']} revenue growing {rg}% YoY — positive AI capex signal"
                )
        if item["ticker"] == "TSM":
            rg = item.get("revenue_growth_yoy")
            if rg is not None:
                direction = (
                    "expanding" if rg > 10
                    else "moderating" if rg > 0
                    else "contracting"
                )
                signals.append(
                    f"TSMC revenue {direction} ({rg}% YoY) — semiconductor demand proxy"
                )

    return {
        "upcoming_earnings": upcoming,
        "recent_results": recent_results,
        "signals": signals,
        "hyperscalers_tracked": HYPERSCALERS,
        "peers_tracked": PEERS,
        "supply_chain_tracked": SUPPLY_CHAIN,
    }


# --- Earnings refresh ---

def get_next_earnings_date(ticker: str, info: dict) -> date | None:
    """Extract next earnings date from cached .info, with yfinance fallbacks."""
    # Strategy 1: info fields (already cached — free)
    for field in ("earningsTimestampStart", "earningsTimestampEnd"):
        ts = info.get(field)
        if ts:
            try:
                d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
                if d >= date.today():
                    return d
            except (TypeError, ValueError, OSError):
                pass

    if yf is None:
        return None

    tk = yf.Ticker(ticker)

    # Strategy 2: calendar property (separate HTTP call)
    try:
        cal = tk.calendar
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed and len(ed) > 0:
                d = ed[0]
                if hasattr(d, "date"):
                    d = d.date()
                if isinstance(d, date) and d >= date.today():
                    return d
    except (ValueError, KeyError, AttributeError, ConnectionError, OSError, ImportError):
        pass

    # Strategy 3: earnings_dates index (separate HTTP call)
    try:
        eds = tk.earnings_dates
        if eds is not None and len(eds) > 0:
            today_d = date.today()
            for idx in eds.index:
                d = idx.date() if hasattr(idx, "date") else idx
                if isinstance(d, date) and d >= today_d:
                    return d
    except (ValueError, KeyError, AttributeError, ConnectionError, OSError, ImportError):
        pass

    return None


def refresh_earnings(
    watchlist_tickers: list[str],
    info_cache: dict[str, dict],
    config_path: Path | None,
    errors: list[str],
) -> dict:
    """Check and update stale earnings dates in config."""
    if config_path is None:
        return {"updated": [], "unchanged": list(watchlist_tickers)}

    today = date.today()

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        errors.append(f"Failed to load config: {e}")
        return {"updated": [], "unchanged": []}

    watchlist = config.get("watchlist", [])
    changed = False
    updated: list[dict] = []
    unchanged: list[str] = []

    for item in watchlist:
        ticker = item.get("ticker", "")
        current_date_str = item.get("earnings_date")

        needs_update = False
        if current_date_str is None:
            needs_update = True
        else:
            try:
                current_date = (
                    current_date_str
                    if isinstance(current_date_str, date)
                    else datetime.strptime(str(current_date_str), "%Y-%m-%d").date()
                )
                if current_date < today:
                    needs_update = True
            except (ValueError, TypeError):
                needs_update = True

        if not needs_update:
            unchanged.append(ticker)
            continue

        info = info_cache.get(ticker, {})
        try:
            new_date = get_next_earnings_date(ticker, info)
            if new_date:
                old_val = str(current_date_str) if current_date_str else "null"
                new_val = new_date.isoformat()
                item["earnings_date"] = new_val
                updated.append({
                    "ticker": ticker,
                    "old_date": old_val,
                    "new_date": new_val,
                })
                changed = True
            else:
                errors.append(f"{ticker}: Could not determine next earnings date")
                unchanged.append(ticker)
        except (ValueError, KeyError, AttributeError, ConnectionError, OSError) as e:
            errors.append(f"{ticker}: {e}")
            unchanged.append(ticker)

    if changed:
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        except OSError as e:
            errors.append(f"Failed to write config: {e}")

    return {"updated": updated, "unchanged": unchanged}


# --- Main ---

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified yfinance data collection for stock briefing skill",
    )
    parser.add_argument("--tickers", required=True, help="Comma-separated watchlist tickers")
    parser.add_argument("--config", default=None, help="Path to stock_checkin_config.yaml for earnings refresh")
    args = parser.parse_args()

    if yf is None:
        output = {
            "source": "market_data",
            "date": date.today().isoformat(),
            "data": {},
            "errors": ["yfinance not installed"],
        }
        json.dump(output, sys.stdout, indent=2)
        print()
        return 0

    watchlist = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    config_path = Path(args.config) if args.config else None
    today = date.today()
    deadline = time.monotonic() + TOTAL_TIMEOUT
    errors: list[str] = []

    # Collect ALL unique tickers to fetch in one pass
    all_tickers: set[str] = set(watchlist)
    all_tickers.update(HYPERSCALERS)
    all_tickers.update(SUPPLY_CHAIN)
    for ticker in watchlist:
        all_tickers.update(PEERS.get(ticker, []))

    # Single fetch pass — one .info call per unique ticker
    info_cache = fetch_all_info(sorted(all_tickers), deadline, errors)

    # Extract all data from the cache
    short_interest = {
        ticker: extract_short_interest(ticker, info_cache.get(ticker, {}))
        for ticker in watchlist
    }

    ecosystem = build_ecosystem_signals(watchlist, info_cache, today)

    earnings = refresh_earnings(watchlist, info_cache, config_path, errors)

    output = {
        "source": "market_data",
        "date": today.isoformat(),
        "data": {
            "short_interest": short_interest,
            "ecosystem_signals": ecosystem,
            "earnings_refresh": earnings,
        },
        "errors": errors,
    }

    json.dump(output, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
