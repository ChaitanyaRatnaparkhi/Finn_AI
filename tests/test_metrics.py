import pandas as pd
from agent.tools import revenue_vs_budget_usd, gross_margin_trend_pct, cash_runway_months

def _dfs(tmp_path=None):
    import pandas as pd
    a = pd.read_csv('fixtures/actuals.csv')
    b = pd.read_csv('fixtures/budget.csv')
    f = pd.read_csv('fixtures/fx.csv')
    c = pd.read_csv('fixtures/cash.csv')
    return {'actuals': a, 'budget': b, 'fx': f, 'cash': c}

def test_revenue_vs_budget():
    dfs = _dfs()
    res = revenue_vs_budget_usd(dfs, 2025, 6)
    assert round(res['actual_usd']) == 140000
    assert round(res['budget_usd']) == 135000

def test_gm_trend_len():
    dfs = _dfs()
    res = gross_margin_trend_pct(dfs, last_n=2)
    assert len(res['series']) == 2

def test_cash_runway_positive():
    dfs = _dfs()
    res = cash_runway_months(dfs)
    assert 'months' in res