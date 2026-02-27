---
name: stock-briefing
description: >
  Generate a daily pre-market portfolio briefing for AI infrastructure stocks
  (NVDA, MRVL, OKLO, CRWV, MOD, LUMN). Use when the user asks for a stock
  briefing, portfolio check-in, market update, or when invoked by a Cowork
  recurring task. Triggers on "stock briefing", "portfolio briefing",
  "market check-in", "stock check-in", "run stock-briefing", or daily
  scheduled execution.
version: 1.0.0
---

# Stock Briefing Skill

Generate a cadence-aware daily pre-market briefing for the AI infrastructure
portfolio. Layers qualitative intelligence on top of quantitative data from
existing scripts.

## Configuration

- **Watchlist**: NVDA, MRVL, OKLO, CRWV, MOD, LUMN
- **Config file**: `C:\Users\Marcus Maldonado\vault-tools\stock_checkin_config.yaml`
- **Vault path**: `C:\Users\Marcus Maldonado\OneDrive\Documents\Data Center Research`
- **Output folder**: `Investments/Daily Briefings/` (in the vault)
- **Scripts dir**: `C:\Users\Marcus Maldonado\.claude\marcus-local\plugins\stock-briefing\skills\stock-briefing\scripts`
- **Existing scripts**: `C:\Users\Marcus Maldonado\vault-tools`
- **Python**: `C:/Python314/python.exe`
- **Reference checklist**: See `references/stock_monitoring_checklist.md`

## Execution Steps

Follow these steps in order. Each data source is independent — if one fails,
log the error and continue with the others. Never let a single failure block
the entire briefing.

### Step 1: Determine Today's Date and Cadence Layers

```
today = current date (YYYY-MM-DD)
day_of_week = Monday/Tuesday/.../Sunday
day_of_month = 1-31
```

**Check if today is a US market trading day:**
Run: `C:/Python314/python.exe -c "from exchange_calendars import get_calendar; import datetime; cal = get_calendar('XNYS'); d = datetime.date.today(); print('OPEN' if cal.is_session(d.isoformat()) else 'CLOSED')"`

If the `exchange_calendars` library is not installed, use WebSearch to check
"Is the US stock market open today {today}?" as a fallback.

- If CLOSED: Write a minimal note "Markets Closed — {today}" to the vault and
  skip all remaining steps. Do NOT send email for market-closed days.
- If OPEN: Continue.

**Determine active cadence layers:**

```
layers = ["daily"]  # always active

if day_of_week == Monday:
    layers.append("weekly")  # comprehensive Monday report

if day_of_month in [1, 15]:
    layers.append("bi_monthly")

# Check if today is the 1st business day of the month
# (1st weekday that is also a market day)
if day_of_month <= 3 and it's the first trading day of the month:
    layers.append("monthly")
```

**Check earnings proximity:**
Read `C:\Users\Marcus Maldonado\vault-tools\stock_checkin_config.yaml` and
check each ticker's `earnings_date`. If any ticker's earnings date is within
+/- 1 calendar day of today, add "earnings" to layers and note which tickers.

### Step 2: Collect Quantitative Data (Existing Scripts)

Run the existing daily check-in script to get price snapshots, guardrails,
and cadence-aware task lists:

```bash
C:/Python314/python.exe "C:/Users/Marcus Maldonado/vault-tools/daily_stock_checkin.py" --config "C:/Users/Marcus Maldonado/vault-tools/stock_checkin_config.yaml" --stdout-only --date {today}
```

Capture the full stdout output. This gives you:
- Market snapshot table (prices, changes, valuations)
- Guardrail triggers (large moves, stale data, missing tickers, earnings window)
- Status: AUTO CLEAR or MANUAL REVIEW REQUIRED
- Checklist tasks due today

**Parse the status** from the output to determine briefing depth:
- `AUTO CLEAR` + not Monday = **concise** depth
- `MANUAL REVIEW REQUIRED` or earnings layer active = **detailed** depth
- Monday (any status) = **comprehensive** depth
- If `daily_stock_checkin.py` fails entirely, default to **detailed** depth

### Step 3: Collect Qualitative Data (New Sources)

Run these data collection steps. Each is independent — failures do not block others.

**Parallel execution:** Steps 3b, 3c, and 3d are independent Python scripts.
Launch all applicable scripts simultaneously using parallel Bash tool calls.
Steps 3a, 3e use tool calls (WebSearch, MCP) and can also run in parallel
where possible. Do NOT wait for one script to finish before starting the next.

#### 3a: News Headlines (WebSearch — every day)

For each ticker in the watchlist, use the WebSearch tool:
- Query: `"{TICKER} stock news today {today}"`
- Extract: top 3 headlines with source name and date
- For concise depth: limit to 2 headlines per ticker
- For comprehensive depth: up to 5 headlines per ticker

Also search for ecosystem-wide news:
- `"AI data center infrastructure news {today}"`
- `"semiconductor industry news {today}"`

#### 3b: SEC Filings (script — every day)

Run: `C:/Python314/python.exe "{scripts_dir}/sec_filings.py" --tickers NVDA,MRVL,OKLO,CRWV,MOD,LUMN`

If the script is not yet available or fails, use WebSearch as fallback:
- Query: `site:sec.gov "{TICKER}" 8-K OR "Form 4" {this week}`

Report any new 8-K, Form 4, 13D/G filings found.

#### 3c: Insider Activity (script — weekly on Monday + when triggered by red flags)

Only run if "weekly" is in cadence layers OR a red flag is detected:

Run: `C:/Python314/python.exe "{scripts_dir}/insider_activity.py" --tickers NVDA,MRVL,OKLO,CRWV,MOD,LUMN`

If the script is not yet available or fails, use WebSearch:
- Query: `"insider trading" "{TICKER}" site:openinsider.com`

Flag cluster selling (multiple executives selling simultaneously) as a RED FLAG.

#### 3d: Market Data — Short Interest, Ecosystem Signals, Earnings Refresh (script)

Run if "bi_monthly" OR "weekly" is in cadence layers:

Run: `C:/Python314/python.exe "{scripts_dir}/market_data.py" --tickers NVDA,MRVL,OKLO,CRWV,MOD,LUMN --config "{config_file}"`

Where `{config_file}` = `C:\Users\Marcus Maldonado\vault-tools\stock_checkin_config.yaml`

This single script fetches yfinance `.info` once per unique ticker and returns:
- **Short interest** for all watchlist tickers (use on bi_monthly days)
- **Ecosystem signals** — hyperscaler, peer, and supply chain earnings/growth (use on weekly days)
- **Earnings refresh** — updates stale earnings dates in config (use on weekly days)

From the JSON output:
- `data.short_interest` — per-ticker short interest, change %, and report date
- `data.ecosystem_signals.upcoming_earnings` — earnings in next 30 days
- `data.ecosystem_signals.signals` — AI capex and TSMC demand signals
- `data.earnings_refresh.updated` — tickers whose earnings dates were refreshed

If the script fails, use WebSearch as fallback:
- `"{TICKER}" short interest latest`
- `"hyperscaler AI capex earnings" {current_month}`

#### 3e: Prediction Markets (MCP — every day)

Use the Prediction Markets MCP tools to check for relevant markets:

1. `search_all_markets("NVIDIA earnings")` — only during NVDA earnings window
2. `search_all_markets("AI semiconductor")` — weekly
3. `search_all_markets("fed rate cut")` — always (macro signal)
4. `search_all_markets("US recession")` — always (macro signal)

For each relevant market found (>$10K volume):
- Note: market name, yes price (= implied probability), 24h price change

If no relevant markets found or MCP tools unavailable, skip this section.

#### 3f: Playwright Scraping — Finviz (comprehensive days only)

Only run if depth is "comprehensive" (Monday or earnings window):

Use the Playwright MCP tools:
1. `browser_navigate` to `https://finviz.com/quote.ashx?t={TICKER}`
2. `browser_snapshot` to capture the page
3. Extract: analyst consensus rating, price target (mean/high/low), recent
   analyst actions (upgrades/downgrades)

Repeat for each ticker. If Playwright is unavailable or Finviz blocks,
use WebSearch as fallback: `"{TICKER}" analyst rating price target finviz`

#### 3g: Obsidian Vault Cross-Reference (comprehensive days only)

Only run if depth is "comprehensive":

Read each company's vault note from `{vault_path}/Companies/{company_name}.md`:
- Check the `## Financial Data` section for last-known values
- Compare current price vs. last recorded price
- Flag significant changes (>5% move since last vault update)

#### 3h: Monthly Macro Layer (1st business day only)

Only run if "monthly" is in cadence layers:

Use WebSearch to gather macro signals:
- `"federal funds rate" latest decision {current_month}`
- `"10 year treasury yield" today`
- `"hyperscaler AI capex" {current_quarter}` (MSFT, GOOG, META, AMZN)
- `"semiconductor export controls" {current_month}` (NVDA, MRVL exposure)
- `"nuclear energy policy NRC" {current_month}` (OKLO)
- `"data center power demand" {current_month}` (OKLO, CRWV)

Summarize each macro factor's current state and direction.

### Step 4: Synthesize the Briefing

Assemble the briefing document. Apply the depth rules:

**Concise** (normal weekday, no triggers):
Only include: Status & Alerts, Market Snapshot, top headlines (3 per ticker max),
Checklist Tasks Due, Action Items. Target: 1-2 pages.

**Detailed** (guardrail triggered or earnings window):
Include all sections applicable to today's cadence layers. Expand the section
for any ticker that triggered a guardrail. Target: 3-5 pages.

**Comprehensive** (Monday or user request):
Include ALL sections. Full analysis. Target: 5-8 pages.

**Action Items section (always include):**
Synthesize across all data sources. Produce 3-7 bullet points:
- What to watch today/this week
- What requires immediate attention (red flags)
- What to research further
- Position management considerations

### Step 5: Write to Obsidian Vault

Write the briefing to:
`{vault_path}/Investments/Daily Briefings/{today}.md`

Where `vault_path` = `C:\Users\Marcus Maldonado\OneDrive\Documents\Data Center Research`

**Create the directory** if `Investments/Daily Briefings/` doesn't exist:
```bash
mkdir -p "C:/Users/Marcus Maldonado/OneDrive/Documents/Data Center Research/Investments/Daily Briefings"
```

**If a file already exists for today**, overwrite it (latest data wins).

**Frontmatter format:**
```yaml
---
date: {today}
type: stock-briefing
tickers: [NVDA, MRVL, OKLO, CRWV, MOD, LUMN]
status: {AUTO_CLEAR or MANUAL_REVIEW}
cadence: [{active layers as list}]
depth: {concise or detailed or comprehensive}
---
```

### Step 6: Send Email via Gmail

**Only if Gmail is available in Cowork:**

1. Generate an HTML version of the briefing:
   - Run: `C:/Python314/python.exe "{scripts_dir}/email_renderer.py" "{vault_path}/Investments/Daily Briefings/{today}.md"`
   - If the script is not available, just use the markdown text as-is

2. Compose and send an email:
   - To: the authenticated Gmail user (primary address)
   - Subject: `Portfolio Briefing — {today} [{status}]`
   - Body: HTML rendered briefing (or markdown fallback)

3. If Gmail is not configured or sending fails:
   - Log: "Gmail delivery skipped — not configured or send failed"
   - The vault note is still the primary output

### Step 7: Report Completion

After all steps complete, summarize:

```
Stock Briefing Complete — {today}

Status: {AUTO_CLEAR / MANUAL_REVIEW}
Depth: {concise / detailed / comprehensive}
Cadence: {active layers}
Vault: {vault_path}/Investments/Daily Briefings/{today}.md
Email: {sent / skipped}

Data sources: {list which succeeded and which failed}

Key highlights:
- {top 2-3 findings from Action Items}
```

## Red Flags (Always Scan)

Regardless of cadence or depth, ALWAYS check for these red flags and
prominently surface them in the Status & Alerts section if detected:

- CFO or CEO departure (from news)
- Auditor change (from 8-K filings)
- Guidance cut or withdrawal (from news/earnings)
- Key customer loss or contract cancellation
- Regulatory setback (NRC denial for OKLO, export controls for NVDA/MRVL)
- Debt covenant violations or credit rating downgrades (LUMN, CRWV)
- Secondary offering at poor terms (OKLO, CRWV)
- Insider selling clusters (multiple executives selling simultaneously)
- Short seller report published
- Daily price move > 7% (from guardrail triggers)

If ANY red flag is detected, force the briefing depth to "detailed" regardless
of other cadence rules.

## Error Handling

- Each data source (Steps 3a-3h) is independently wrapped — one failure does
  not block others
- If a script is missing or fails, note "Data unavailable: {source}" in the
  relevant section and continue
- If the existing daily_stock_checkin.py fails completely, still attempt other
  data sources and produce a partial briefing with a prominent warning
- If the vault write fails, print the briefing to stdout as a fallback
- Never produce an empty briefing — at minimum, output the date, status, and
  an explanation of what failed
