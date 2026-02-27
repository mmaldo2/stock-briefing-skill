#!/usr/bin/env python3
"""
daily_stock_checkin.py

Generate a daily watchlist check-in report with guardrails for manual review.

Usage:
  python daily_stock_checkin.py
  python daily_stock_checkin.py --config stock_checkin_config.yaml
  python daily_stock_checkin.py --date 2026-02-26
  python daily_stock_checkin.py --stdout-only
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
import yfinance as yf


DAY_NAME_TO_WEEKDAY = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass
class WatchlistItem:
    ticker: str
    company: str
    earnings_date: date | None


@dataclass
class Snapshot:
    ticker: str
    company: str
    price: float | None
    price_change_pct: float | None
    market_cap: int | None
    pe_trailing: float | None
    pe_forward: float | None
    ev_ebitda: float | None
    ps_ratio: float | None
    last_trade_date: date | None
    error: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate daily stock check-in report")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("stock_checkin_config.yaml")),
        help="Path to stock_checkin_config.yaml",
    )
    parser.add_argument(
        "--date",
        help="Run date in YYYY-MM-DD (defaults to local today)",
    )
    parser.add_argument(
        "--stdout-only",
        action="store_true",
        help="Print report to stdout instead of writing a file",
    )
    return parser.parse_args()


def load_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_iso_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def summarize_error_message(value: Any) -> str:
    text = str(value).replace("\n", " ").strip()
    if not text:
        return "Unknown fetch error"
    text_lower = text.lower()
    if "failed to perform" in text_lower and "curl" in text_lower:
        return "Network fetch failed"
    if len(text) > 140:
        return text[:137] + "..."
    return text


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN check
        return None
    return result


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN check
        return None
    return int(result)


def compute_price_change_pct(current: float | None, previous_close: float | None) -> float | None:
    if current is None or previous_close is None or previous_close == 0:
        return None
    if current == previous_close:
        return None
    if previous_close < current * 0.01 or previous_close > current * 100:
        return None
    return round(((current - previous_close) / previous_close) * 100, 2)


def extract_last_trade_date(info: dict[str, Any]) -> date | None:
    raw = info.get("regularMarketTime")
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).date()
        return datetime.fromisoformat(str(raw)).date()
    except (TypeError, ValueError, OSError):
        return None


def format_money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:,.2f}"


def format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def format_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


def format_market_cap(value: int | None) -> str:
    if value is None:
        return "-"
    abs_value = abs(value)
    if abs_value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if abs_value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    return f"${value:,}"


def resolve_watchlist(config: dict[str, Any]) -> list[WatchlistItem]:
    items = []
    for raw in config.get("watchlist", []):
        ticker = str(raw.get("ticker", "")).strip().upper()
        company = str(raw.get("company", ticker)).strip()
        if not ticker:
            continue
        items.append(
            WatchlistItem(
                ticker=ticker,
                company=company,
                earnings_date=parse_iso_date(raw.get("earnings_date")),
            )
        )
    return items


def fetch_snapshot(item: WatchlistItem) -> Snapshot:
    try:
        info = yf.Ticker(item.ticker).info
    except Exception as exc:  # pragma: no cover - network/data source boundary
        return Snapshot(
            ticker=item.ticker,
            company=item.company,
            price=None,
            price_change_pct=None,
            market_cap=None,
            pe_trailing=None,
            pe_forward=None,
            ev_ebitda=None,
            ps_ratio=None,
            last_trade_date=None,
            error=summarize_error_message(exc),
        )

    if not info:
        return Snapshot(
            ticker=item.ticker,
            company=item.company,
            price=None,
            price_change_pct=None,
            market_cap=None,
            pe_trailing=None,
            pe_forward=None,
            ev_ebitda=None,
            ps_ratio=None,
            last_trade_date=None,
            error="No data returned from yfinance",
        )

    price = safe_float(info.get("currentPrice"))
    if price is None:
        price = safe_float(info.get("regularMarketPrice"))
    previous_close = safe_float(info.get("previousClose"))

    return Snapshot(
        ticker=item.ticker,
        company=item.company,
        price=price if price is not None else previous_close,
        price_change_pct=compute_price_change_pct(price, previous_close),
        market_cap=safe_int(info.get("marketCap")),
        pe_trailing=safe_float(info.get("trailingPE")),
        pe_forward=safe_float(info.get("forwardPE")),
        ev_ebitda=safe_float(info.get("enterpriseToEbitda")),
        ps_ratio=safe_float(info.get("priceToSalesTrailing12Months")),
        last_trade_date=extract_last_trade_date(info),
        error=None,
    )


def nth_business_day_of_month(target_date: date) -> int:
    count = 0
    cursor = target_date.replace(day=1)
    while cursor <= target_date:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def build_due_tasks(run_date: date, cadence_cfg: dict[str, Any], earnings_due: list[str]) -> dict[str, list[str]]:
    daily = [
        "Review red flags checklist for all six names.",
        "Scan 8-K filings and material company announcements.",
        "Check sell-side estimate revisions and target changes.",
        "Check hyperscaler AI capex commentary deltas (MSFT, GOOG, META, AMZN).",
    ]

    weekly = []
    weekly_day = str(cadence_cfg.get("weekly_review_day", "Friday")).strip().lower()
    if run_date.weekday() == DAY_NAME_TO_WEEKDAY.get(weekly_day, 4):
        weekly = [
            "Review Form 4 insider buy/sell activity.",
            "Review sector flow and relative performance signals (SMH, GRID/ICLN).",
            "Review valuation drift versus your baseline thesis assumptions.",
        ]

    bi_monthly = []
    bi_monthly_days = cadence_cfg.get("bi_monthly_days", [1, 15])
    if run_date.day in bi_monthly_days:
        bi_monthly = [
            "Check short-interest updates and changes in crowding risk.",
            "Review options implied volatility into the next earnings windows.",
        ]

    monthly = []
    monthly_business_day = int(cadence_cfg.get("monthly_review_business_day", 1))
    if nth_business_day_of_month(run_date) == monthly_business_day:
        monthly = [
            "Review macro layer: fed path, 10Y yield, and cost-of-capital pressure.",
            "Review policy/regulation changes: export controls, tariff updates, DOE/NRC updates.",
        ]

    earnings_window = []
    if earnings_due:
        earnings_window = [
            "Run earnings workflow: pre-read release, call notes, guidance delta, and post-call thesis check."
        ]

    return {
        "daily": daily,
        "weekly": weekly,
        "bi_monthly": bi_monthly,
        "monthly": monthly,
        "earnings_window": earnings_window,
    }


def evaluate_guardrails(
    snapshots: list[Snapshot],
    watchlist: list[WatchlistItem],
    guardrails: dict[str, Any],
    run_date: date,
) -> tuple[str, list[str], list[str]]:
    triggered: list[str] = []
    earnings_due: list[str] = []

    max_missing_tickers = int(guardrails.get("max_missing_tickers", 0))
    stale_data_max_days = int(guardrails.get("stale_data_max_days", 1))
    price_move_threshold = float(guardrails.get("price_move_pct_threshold", 7.0))
    earnings_window_days = int(guardrails.get("earnings_window_days", 1))

    missing = [s.ticker for s in snapshots if s.error or s.price is None]
    if len(missing) > max_missing_tickers:
        triggered.append(
            f"Missing critical data for {len(missing)} ticker(s): {', '.join(sorted(missing))}"
        )

    stale = []
    for snap in snapshots:
        if snap.last_trade_date is None or snap.price is None:
            continue
        age_days = (run_date - snap.last_trade_date).days
        if age_days > stale_data_max_days:
            stale.append(f"{snap.ticker} ({snap.last_trade_date.isoformat()})")
    if stale:
        triggered.append(
            "Stale market timestamps beyond allowed window: " + ", ".join(stale)
        )

    large_moves = []
    for snap in snapshots:
        change = snap.price_change_pct
        if change is None:
            continue
        if abs(change) >= price_move_threshold:
            large_moves.append(f"{snap.ticker} ({change:+.2f}%)")
    if large_moves:
        triggered.append(
            f"Large daily move >= {price_move_threshold:.1f}%: " + ", ".join(large_moves)
        )

    for item in watchlist:
        if item.earnings_date is None:
            continue
        delta = (item.earnings_date - run_date).days
        if abs(delta) <= earnings_window_days:
            relation = "today"
            if delta < 0:
                relation = f"{abs(delta)} day(s) ago"
            elif delta > 0:
                relation = f"in {delta} day(s)"
            earnings_due.append(
                f"{item.ticker} ({item.company}) earnings {item.earnings_date.isoformat()} [{relation}]"
            )
    if earnings_due:
        triggered.append("Earnings window active: " + "; ".join(earnings_due))

    status = "AUTO CLEAR"
    if triggered:
        status = "MANUAL REVIEW REQUIRED"

    return status, triggered, earnings_due


def render_report(
    run_date: date,
    generated_at: datetime,
    status: str,
    guardrails_triggered: list[str],
    snapshots: list[Snapshot],
    due_tasks: dict[str, list[str]],
) -> str:
    lines: list[str] = []
    lines.append(f"# Daily Stock Check-In - {run_date.isoformat()}")
    lines.append("")
    lines.append(f"Status: **{status}**")
    lines.append(f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append("")

    lines.append("## Guardrail Triggers")
    if guardrails_triggered:
        for trigger in guardrails_triggered:
            lines.append(f"- {trigger}")
    else:
        lines.append("- No guardrails triggered.")
    lines.append("")

    lines.append("## Market Snapshot")
    lines.append("| Ticker | Company | Price | 1D % | Market Cap | P/E TTM | P/E Fwd | EV/EBITDA | P/S | Last Trade | Data Status |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for snap in snapshots:
        data_status = "ok" if not snap.error else f"error: {snap.error}"
        lines.append(
            "| "
            + " | ".join(
                [
                    snap.ticker,
                    snap.company,
                    format_money(snap.price),
                    format_pct(snap.price_change_pct),
                    format_market_cap(snap.market_cap),
                    format_ratio(snap.pe_trailing),
                    format_ratio(snap.pe_forward),
                    format_ratio(snap.ev_ebitda),
                    format_ratio(snap.ps_ratio),
                    snap.last_trade_date.isoformat() if snap.last_trade_date else "-",
                    data_status,
                ]
            )
            + " |"
        )
    lines.append("")

    lines.append("## Checklist Tasks Due Today")
    lines.append("### Daily")
    for task in due_tasks["daily"]:
        lines.append(f"- [ ] {task}")
    lines.append("")

    if due_tasks["weekly"]:
        lines.append("### Weekly")
        for task in due_tasks["weekly"]:
            lines.append(f"- [ ] {task}")
        lines.append("")

    if due_tasks["bi_monthly"]:
        lines.append("### Bi-Monthly")
        for task in due_tasks["bi_monthly"]:
            lines.append(f"- [ ] {task}")
        lines.append("")

    if due_tasks["monthly"]:
        lines.append("### Monthly")
        for task in due_tasks["monthly"]:
            lines.append(f"- [ ] {task}")
        lines.append("")

    if due_tasks["earnings_window"]:
        lines.append("### Earnings Window")
        for task in due_tasks["earnings_window"]:
            lines.append(f"- [ ] {task}")
        lines.append("")

    lines.append("## Next Action")
    if status == "MANUAL REVIEW REQUIRED":
        lines.append("- Run an assistant-led qualitative review before making position changes.")
    else:
        lines.append("- Proceed with normal cadence and schedule the next daily check-in.")
    lines.append("")

    return "\n".join(lines)


def write_report(content: str, output_dir: str, filename_format: str, run_date: date) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    filename = run_date.strftime(filename_format)
    report_path = directory / filename
    report_path.write_text(content, encoding="utf-8")
    return report_path


def main() -> int:
    args = parse_args()
    config = load_yaml(args.config)

    run_date = datetime.now().date()
    if args.date:
        parsed = parse_iso_date(args.date)
        if parsed is None:
            raise SystemExit("--date must be in YYYY-MM-DD format")
        run_date = parsed

    watchlist = resolve_watchlist(config)
    snapshots = [fetch_snapshot(item) for item in watchlist]

    status, guardrails_triggered, earnings_due = evaluate_guardrails(
        snapshots=snapshots,
        watchlist=watchlist,
        guardrails=config.get("guardrails", {}),
        run_date=run_date,
    )

    due_tasks = build_due_tasks(
        run_date=run_date,
        cadence_cfg=config.get("cadence", {}),
        earnings_due=earnings_due,
    )

    generated_at = datetime.now().astimezone()
    report_text = render_report(
        run_date=run_date,
        generated_at=generated_at,
        status=status,
        guardrails_triggered=guardrails_triggered,
        snapshots=snapshots,
        due_tasks=due_tasks,
    )

    if args.stdout_only:
        print(report_text)
        return 0

    output_cfg = config.get("output", {})
    report_path = write_report(
        content=report_text,
        output_dir=output_cfg.get(
            "report_dir", str(Path(__file__).parent / "output")
        ),
        filename_format=output_cfg.get("filename_format", "%Y-%m-%d.md"),
        run_date=run_date,
    )

    print(f"Wrote daily check-in: {report_path}")
    print(f"Status: {status}")
    if guardrails_triggered:
        print("Guardrails:")
        for item in guardrails_triggered:
            print(f" - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
