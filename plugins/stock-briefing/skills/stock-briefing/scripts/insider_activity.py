#!/usr/bin/env python3
"""
insider_activity.py — Fetch insider trading activity from OpenInsider.

Usage:
    python insider_activity.py --tickers NVDA,MRVL,OKLO,CRWV,MOD,LUMN
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

OPENINSIDER_URL = "https://www.openinsider.com/screener?s={ticker}&o=&pl=&ph=&st=0&lt=0&lk=&ld=&td=7&tdr=&fdlyl=&fdlyh=&dtefrom=&dteto=&xp=1&vtefrom=&vteto=&hession=true"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REQUEST_DELAY = 1.5
PER_REQUEST_TIMEOUT = 15


def parse_money(text: str) -> float | None:
    """Parse dollar amounts like '$1,234,567' or '-$500'."""
    cleaned = re.sub(r"[,$]", "", text.strip())
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int_shares(text: str) -> int | None:
    """Parse share counts like '+1,234' or '-500'."""
    cleaned = re.sub(r"[,+]", "", text.strip())
    if not cleaned or cleaned == "-":
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def fetch_insider_data(ticker: str, session: requests.Session) -> tuple[list[dict], str | None]:
    url = OPENINSIDER_URL.format(ticker=ticker)
    try:
        resp = session.get(url, timeout=PER_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        return [], str(e)

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", class_="tinytable")
    if not table:
        return [], None  # No transactions found (not an error)

    rows = table.find_all("tr")[1:]  # Skip header
    transactions = []

    for row in rows[:20]:  # Limit to 20 most recent
        cells = row.find_all("td")
        if len(cells) < 13:
            continue

        try:
            filing_date = cells[1].get_text(strip=True)
            trade_date = cells[2].get_text(strip=True)
            insider_name = cells[4].get_text(strip=True)
            title = cells[5].get_text(strip=True)
            trade_type = cells[6].get_text(strip=True)
            price = parse_money(cells[8].get_text(strip=True))
            shares = parse_int_shares(cells[9].get_text(strip=True))
            value = parse_money(cells[12].get_text(strip=True))

            # Get filing URL if available
            link = cells[1].find("a")
            filing_url = (
                f"https://www.sec.gov{link['href']}"
                if link and link.get("href", "").startswith("/")
                else ""
            )

            transactions.append({
                "filing_date": filing_date,
                "trade_date": trade_date,
                "insider_name": insider_name,
                "title": title,
                "trade_type": trade_type,
                "price": price,
                "shares": shares,
                "value": value,
                "filing_url": filing_url,
            })
        except (IndexError, AttributeError):
            continue

    return transactions, None


def detect_cluster_selling(transactions: list[dict]) -> bool:
    """Detect if 3+ unique insiders sold within a 7-day window."""
    sells = []
    for t in transactions:
        if "Sale" in t.get("trade_type", "") or "S -" in t.get("trade_type", ""):
            try:
                d = datetime.strptime(t["trade_date"], "%Y-%m-%d").date()
                sells.append((d, t["insider_name"]))
            except (ValueError, KeyError):
                continue

    if len(sells) < 3:
        return False

    sells.sort(key=lambda x: x[0])
    # Sliding window: check if 3+ unique sellers within any 7-day window
    for i in range(len(sells)):
        window_end = sells[i][0] + timedelta(days=7)
        unique_sellers = set()
        for j in range(i, len(sells)):
            if sells[j][0] <= window_end:
                unique_sellers.add(sells[j][1])
            else:
                break
        if len(unique_sellers) >= 3:
            return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=True)
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    today = date.today().isoformat()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    data: dict[str, dict] = {}
    errors: list[str] = []

    for i, ticker in enumerate(tickers):
        if i > 0:
            time.sleep(REQUEST_DELAY)

        transactions, err = fetch_insider_data(ticker, session)
        cluster_alert = detect_cluster_selling(transactions) if transactions else False

        data[ticker] = {
            "transactions": transactions,
            "transaction_count": len(transactions),
            "cluster_alert": cluster_alert,
        }
        if err:
            errors.append(f"{ticker}: {err}")

    output = {
        "source": "insider_activity",
        "date": today,
        "data": data,
        "errors": errors,
    }
    json.dump(output, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
