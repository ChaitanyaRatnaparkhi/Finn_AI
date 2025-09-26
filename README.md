
# FP&A Mini CFO Copilot

A small end-to-end Streamlit app that answers CFO-style questions directly from monthly CSVs and returns concise, board-ready answers with charts.

## Features
- Natural-language **question → intent classification → metric functions → text + chart**.
- Required metrics: Revenue vs Budget (USD), Gross Margin %, Opex totals (USD), EBITDA (proxy), Cash Runway.
- Charts with Plotly (works in Streamlit).
- Minimal tests with `pytest`.
- Drop-in CSVs via `fixtures/` (works offline).

## Data
Place these CSVs in **`fixtures/`** (file names must match):
- `actuals.csv` — monthly actuals by entity/account
- `budget.csv` — monthly budget by entity/account
- `fx.csv` — currency exchange rates
- `cash.csv` — monthly cash balances

> **Tip:** Export each sheet from the shared Google Sheet as CSV and save into `fixtures/` with the exact names above.

### Expected Columns
**actuals.csv** and **budget.csv**
```
date, entity, account, amount, currency
2025-05-01, US, Revenue, 120000, USD
2025-05-01, US, COGS, 60000, USD
2025-05-01, US, Opex:Sales, 15000, USD
...
```
- `date` should be the **first day of the month** (`YYYY-MM-01`).
- `account` values should include `Revenue`, `COGS`, and `Opex:*` categories (e.g., `Opex:G&A`, `Opex:R&D`, `Opex:Sales`).

**fx.csv**
```
date, currency, rate_to_usd
2025-05-01, USD, 1.0
2025-05-01, EUR, 1.1
...
```
> `rate_to_usd` = USD per 1 unit of `currency` on that date.

**cash.csv**
```
date, entity, cash, currency
2025-05-01, Consolidated, 1500000, USD
...
```

## Run
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
streamlit run app.py


python -m streamlit run app.py --server.port 8502  # IF YOU GET A ERROR TRY RUNNING ON THIS PORT

```

## Example Questions
- *What was June 2025 revenue vs budget in USD?*
- *Show Gross Margin % trend for the last 3 months.*
- *Break down Opex by category for June 2025.*
- *What is our cash runway right now?*

## Tests
```bash
pytest -q
```

## Notes
- The app uses a **simple rules-based intent classifier**; you can extend it with LLMs later.
- If your CSVs use different account names, update `agent/tools.py -> ACCOUNT_ALIASES`.
