import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta
import plotly.graph_objects as go
from datetime import datetime

ACCOUNT_ALIASES = {
    'revenue': ['revenue', 'total revenue'],
    'cogs': ['cogs', 'cost of goods sold'],
    'opex_prefix': 'opex:'
}

def _to_period(dt_val):
    if isinstance(dt_val, str):
        dt_val = pd.to_datetime(dt_val)
    return pd.Period(dt_val, freq='M').to_timestamp()

def _normalize_accounts(df):
    df = df.copy()
    df['account_norm'] = df['account'].str.lower()
    return df

def _merge_fx(df, fx):
    # Expect fx columns: date, currency, rate_to_usd
    fxc = fx.copy()
    fxc['date'] = pd.to_datetime(fxc['date']).dt.to_period('M').dt.to_timestamp()
    dfc = df.copy()
    dfc['date'] = pd.to_datetime(dfc['date']).dt.to_period('M').dt.to_timestamp()
    merged = pd.merge(dfc, fxc, on=['date','currency'], how='left')
    merged['rate_to_usd'] = merged['rate_to_usd'].fillna(1.0)
    merged['amount_usd'] = merged['amount'] * merged['rate_to_usd']
    return merged

def latest_month_in_actuals(actuals):
    if actuals is None or actuals.empty:
        return None
    d = pd.to_datetime(actuals['date']).dt.to_period('M').max()
    if pd.isna(d):
        return None
    return d.to_timestamp()

def _sum_by_account(df, year, month, account_key):
    dt = pd.Timestamp(year=year, month=month, day=1).to_period('M').to_timestamp()
    mask = df['date'] == dt
    if account_key == 'opex':
        return df[mask & df['account_norm'].str.startswith(ACCOUNT_ALIASES['opex_prefix'])]['amount_usd'].sum()
    if account_key == 'revenue':
        return df[mask & df['account_norm'].isin(ACCOUNT_ALIASES['revenue'])]['amount_usd'].sum()
    if account_key == 'cogs':
        return df[mask & df['account_norm'].isin(ACCOUNT_ALIASES['cogs'])]['amount_usd'].sum()
    return 0.0

def _series_gm(dfa):
    # Return monthly series with revenue, cogs, gm%
    dfa = dfa.copy()
    dfa['ym'] = pd.to_datetime(dfa['date']).dt.to_period('M').dt.to_timestamp()
    rev = dfa[dfa['account_norm'].isin(ACCOUNT_ALIASES['revenue'])].groupby('ym')['amount_usd'].sum()
    cogs = dfa[dfa['account_norm'].isin(ACCOUNT_ALIASES['cogs'])].groupby('ym')['amount_usd'].sum()
    s = pd.DataFrame({'revenue': rev, 'cogs': cogs}).fillna(0.0)
    s['gm'] = s['revenue'] - s['cogs']
    s['gm_pct'] = np.where(s['revenue'] != 0, s['gm'] / s['revenue'] * 100.0, np.nan)
    s = s.dropna(subset=['gm_pct'])
    return s

def _series_opex(dfa):
    dfa = dfa.copy()
    dfa['ym'] = pd.to_datetime(dfa['date']).dt.to_period('M').dt.to_timestamp()
    mask = dfa['account_norm'].str.startswith(ACCOUNT_ALIASES['opex_prefix'])
    s = dfa[mask].groupby(['ym', 'account_norm'])['amount_usd'].sum().reset_index()
    return s

def _series_ebitda(dfa):
    dfa = dfa.copy()
    dfa['ym'] = pd.to_datetime(dfa['date']).dt.to_period('M').dt.to_timestamp()
    rev = dfa[dfa['account_norm'].isin(ACCOUNT_ALIASES['revenue'])].groupby('ym')['amount_usd'].sum()
    cogs = dfa[dfa['account_norm'].isin(ACCOUNT_ALIASES['cogs'])].groupby('ym')['amount_usd'].sum()
    opex = dfa[dfa['account_norm'].str.startswith(ACCOUNT_ALIASES['opex_prefix'])].groupby('ym')['amount_usd'].sum()
    s = pd.DataFrame({'revenue': rev, 'cogs': cogs, 'opex': opex}).fillna(0.0)
    s['ebitda'] = s['revenue'] - s['cogs'] - s['opex']
    return s

def revenue_vs_budget_usd(dfs, year, month):
    actuals = _normalize_accounts(_merge_fx(dfs['actuals'], dfs['fx']))
    budget = _normalize_accounts(_merge_fx(dfs['budget'], dfs['fx']))
    a = _sum_by_account(actuals, year, month, 'revenue')
    b = _sum_by_account(budget, year, month, 'revenue')
    variance = a - b
    variance_pct = (variance / b * 100.0) if b != 0 else np.nan

    # Small single-bar chart actual vs budget
    fig = go.Figure()
    fig.add_bar(x=['Actual', 'Budget'], y=[a, b])
    fig.update_layout(title=f"Revenue (USD) — {year}-{month:02d}", yaxis_title='USD')
    return { 'actual_usd': float(a), 'budget_usd': float(b), 'variance_usd': float(variance), 'variance_pct': float(variance_pct if not np.isnan(variance_pct) else 0.0), 'chart': fig }

def gross_margin_trend_pct(dfs, last_n=3):
    actuals = _normalize_accounts(_merge_fx(dfs['actuals'], dfs['fx']))
    s = _series_gm(actuals).tail(last_n)
    fig = go.Figure()
    fig.add_scatter(x=s.index, y=s['gm_pct'], mode='lines+markers', name='GM %')
    fig.update_layout(title=f'Gross Margin % — last {last_n} months', yaxis_title='Percent')
    series = [{'period': d.strftime('%Y-%m'), 'gm_pct': float(v)} for d, v in zip(s.index, s['gm_pct'])]
    return {'chart': fig, 'series': series}

def opex_breakdown_usd(dfs, year, month):
    actuals = _normalize_accounts(_merge_fx(dfs['actuals'], dfs['fx']))
    s = _series_opex(actuals)
    dt = pd.Timestamp(year=year, month=month, day=1).to_period('M').to_timestamp()
    m = s[s['ym'] == dt]
    fig = go.Figure()
    if not m.empty:
        fig.add_pie(labels=m['account_norm'].str.replace('opex:', '', regex=False).str.upper(),
                    values=m['amount_usd'])
    fig.update_layout(title=f'Opex Breakdown (USD) — {year}-{month:02d}')
    return {'chart': fig}

def cash_runway_months(dfs):
    # Cash (latest), avg monthly net burn = -EBITDA average of last 3 months if EBITDA<0, else 0 (infinite runway)
    actuals = _normalize_accounts(_merge_fx(dfs['actuals'], dfs['fx']))
    e = _series_ebitda(actuals).tail(3)
    if e.empty:
        return None
    avg_burn = -e['ebitda'].mean()  # burn is negative EBITDA
    cash = dfs['cash'].copy()
    cash['date'] = pd.to_datetime(cash['date']).dt.to_period('M').dt.to_timestamp()
    cash = _merge_fx(cash.rename(columns={'cash': 'amount', 'currency': 'currency'}), dfs['fx'])
    latest_cash = cash.sort_values('date').groupby('currency', as_index=False).tail(1)  # already usd after merge
    total_cash = cash.groupby('date')['amount_usd'].sum().sort_index().tail(1)
    cash_usd = float(total_cash.iloc[0]) if not total_cash.empty else 0.0

    if avg_burn <= 0.0:
        months = float('inf')
    else:
        months = cash_usd / avg_burn

    # Chart: trailing EBITDA and cash
    fig = go.Figure()
    fig.add_bar(x=e.index, y=e['ebitda'], name='EBITDA (USD)')
    # Overlay latest cash as a line (flat)
    if not cash.empty:
        fig.add_scatter(x=total_cash.index, y=total_cash.values, name='Cash (USD)', mode='markers+lines')
    fig.update_layout(title='EBITDA (last 3 months) & Latest Cash', yaxis_title='USD')
    return {'months': months, 'cash_usd': cash_usd, 'avg_burn_usd': float(avg_burn), 'chart': fig}
