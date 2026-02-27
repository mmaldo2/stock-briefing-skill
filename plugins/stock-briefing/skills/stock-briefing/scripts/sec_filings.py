#!/usr/bin/env python3
"""
sec_filings.py — Query SEC EDGAR full-text search for recent filings.

Usage:
    python sec_filings.py --tickers NVDA,MRVL,OKLO,CRWV,MOD,LUMN
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from urllib.parse import quote

import requests

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
FORM_TYPES = "8-K,10-Q,10-K,4,SC 13D,SC 13G"
# SEC EDGAR requires a real contact email — update this before use
USER_AGENT = "StockBriefingSkill marcusmaldonado15@gmail.com"
REQUEST_DELAY = 0.15
TOTAL_TIMEOUT = 60
PER_REQUEST_TIMEOUT = 15


def fetch_filings(
    ticker: str,
    start_date: str,
    end_date: str,
    session: requests.Session,
    deadline: float,
) -> tuple[list[dict], str | None]:
    if time.monotonic() > deadline:
        return [], f"{ticker}: total timeout exceeded"

    url = (
        f"{EDGAR_SEARCH_URL}?q=%22{quote(ticker)}%22"
        f"&forms={quote(FORM_TYPES)}"
        f"&dateRange=custom&startdt={start_date}&enddt={end_date}"
    )

    remaining = max(1.0, deadline - time.monotonic())
    try:
        resp = session.get(url, timeout=min(PER_REQUEST_TIMEOUT, remaining))
        resp.raise_for_status()
    except requests.RequestException as e:
        return [], f"{ticker}: {e}"

    try:
        data = resp.json()
    except (ValueError, json.JSONDecodeError):
        return [], f"{ticker}: invalid JSON response"

    hits_wrapper = data.get("hits", data)
    hits = (
        hits_wrapper.get("hits", [])
        if isinstance(hits_wrapper, dict)
        else hits_wrapper if isinstance(hits_wrapper, list) else []
    )

    filings = []
    seen_adsh: set[str] = set()  # Deduplicate by accession number
    for hit in hits:
        src = hit.get("_source", hit)
        adsh = src.get("adsh", "")
        if adsh in seen_adsh:
            continue
        seen_adsh.add(adsh)

        # EDGAR returns: form, file_type, root_forms (list), file_date, display_names, adsh
        ft = src.get("form", src.get("file_type", ""))
        if not ft:
            root = src.get("root_forms", [])
            ft = root[0] if root else ""
        fd = src.get("file_date", src.get("date_filed", ""))
        title = src.get("display_names", src.get("entity_name", ""))
        if isinstance(title, list):
            title = "; ".join(title)

        # Build URL from accession number and CIK
        ciks = src.get("ciks", [])
        cik = ciks[0] if ciks else ""
        if adsh and cik:
            url_out = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/"
        else:
            url_out = ""

        # Extract 8-K item numbers for context
        items = src.get("items", [])

        filings.append({
            "filing_type": str(ft).strip(),
            "filed_date": str(fd).strip(),
            "title": str(title).strip(),
            "url": url_out,
            "items": items,
        })

    return filings, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=True)
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    today = date.today()
    start = (today - timedelta(days=7)).isoformat()
    end = today.isoformat()
    deadline = time.monotonic() + TOTAL_TIMEOUT

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    results: dict[str, list] = {}
    errors: list[str] = []

    for i, ticker in enumerate(tickers):
        if i > 0:
            time.sleep(REQUEST_DELAY)
        filings, err = fetch_filings(ticker, start, end, session, deadline)
        results[ticker] = filings
        if err:
            errors.append(err)

    output = {
        "source": "sec_filings",
        "date": today.isoformat(),
        "data": results,
        "errors": errors,
    }
    json.dump(output, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
