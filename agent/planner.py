import re
from dateutil.parser import parse
from .tools import (
    revenue_vs_budget_usd,
    gross_margin_trend_pct,
    opex_breakdown_usd,
    cash_runway_months,
    latest_month_in_actuals,
)

MONTH_ALIASES = {
    'jan': 1, 'january': 1,
    'feb': 2, 'february': 2,
    'mar': 3, 'march': 3,
    'apr': 4, 'april': 4,
    'may': 5,
    'jun': 6, 'june': 6,
    'jul': 7, 'july': 7,
    'aug': 8, 'august': 8,
    'sep': 9, 'sept': 9, 'september': 9,
    'oct': 10, 'october': 10,
    'nov': 11, 'november': 11,
    'dec': 12, 'december': 12,
}

def _parse_month_year(text, fallback=None):
    text = text.lower()
    # Try explicit "June 2025" style
    m = re.search(r"""(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|
                    jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|
                    dec(?:ember)?)\s+(20\d{2})""", text, re.X)
    if m:
        month = MONTH_ALIASES[m.group(1)[:3]]
        year = int(m.group(2))
        return year, month
    # Try "for 2025-06" or "2025/06"
    m2 = re.search(r"(20\d{2})[-/](\d{1,2})", text)
    if m2:
        return int(m2.group(1)), int(m2.group(2))
    # Try single month name with fallback year
    for k, v in MONTH_ALIASES.items():
        if re.search(rf"\b{k}\b", text):
            year = fallback if fallback else None
            return (year, v) if year else (None, v)
    return fallback, None

def _parse_window(text, default_last_n=3):
    m = re.search(r"last\s+(\d{1,2})\s+months?", text, re.I)
    if m: return int(m.group(1))
    return default_last_n

def plan_and_execute(q: str, dfs: dict):
    ql = q.lower()

    # Determine default year from latest actuals if needed
    latest_ym = latest_month_in_actuals(dfs['actuals'])
    default_year = latest_ym.year if latest_ym is not None else None

    # INTENT: revenue vs budget
    if re.search(r"revenue.*budget|vs\s*budget|budget.*revenue", ql):
        year, month = _parse_month_year(ql, fallback=default_year)
        if month is None or year is None:
            return {"text": "Please include a month and year (e.g., 'June 2025').", "chart": None}
        res = revenue_vs_budget_usd(dfs, year, month)
        return {
            "text": (f"Revenue vs Budget for {year}-{month:02d}: Actual ${res['actual_usd']:,.0f} | " 
                      f"Budget ${res['budget_usd']:,.0f} | Variance ${res['variance_usd']:,.0f} ({res['variance_pct']:.1f}%)."),
            "chart": res['chart']
        }

    # INTENT: gross margin trend
    if re.search(r"gross\s*margin", ql) and re.search(r"trend|last\s+\d+\s+months|last\s+months", ql):
        n = _parse_window(ql, 3)
        res = gross_margin_trend_pct(dfs, last_n=n)
        return {
            "text": f"Gross Margin % for last {n} months: " + ", ".join([f"{x['period']}: {x['gm_pct']:.1f}%" for x in res['series']]),
            "chart": res['chart']
        }

    # INTENT: opex breakdown
    if re.search(r"opex|operating\s+expenses", ql) and re.search(r"break\s*down|breakdown" , ql):
        year, month = _parse_month_year(ql, fallback=default_year)
        if month is None or year is None:
            return {"text": "Please include a month and year for the Opex breakdown.", "chart": None}
        res = opex_breakdown_usd(dfs, year, month)
        return {"text": f"Opex breakdown for {year}-{month:02d} (USD).", "chart": res['chart']}

    # INTENT: cash runway
    if re.search(r"cash\s*runway|runway", ql):
        res = cash_runway_months(dfs)
        if res is None:
            return {"text": "Not enough data to compute runway.", "chart": None}
        months = res['months']
        return {"text": f"Cash runway: {months:.1f} months (Cash ${res['cash_usd']:,.0f} / Avg monthly burn ${res['avg_burn_usd']:,.0f}).", "chart": res['chart']}

    return {"text": "Sorry, I couldn't classify that question. Try: 'What was June 2025 revenue vs budget?'", "chart": None}