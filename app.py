import os, re
import pandas as pd
import streamlit as st
from agent import plan_and_execute

st.set_page_config(page_title="CFO Copilot", layout="wide")

EXAMPLES = [
    "What was June 2025 revenue vs budget in USD?",
    "Show Gross Margin % trend for the last 3 months.",
    "Break down Opex by category for June 2025.",
    "What is our cash runway right now?",
]

# ----------------------------
# Smart CSV ingest
# ----------------------------
BASE_KEYS = {"date", "entity", "currency"}
WIDE_NAME_HINTS = re.compile(
    r"(revenue|sales|cogs|cost\s*of\s*goods|opex|operating\s*exp|g&a|general|admin|r&d|research|marketing|sales\s*&\s*marketing)",
    re.I,
)

def _read_csv_smart(path: str) -> pd.DataFrame:
    """Try to find the correct header row if the first row is junk."""
    # quick read
    df0 = pd.read_csv(path, nrows=0)
    cols0 = [str(c).strip().lower() for c in df0.columns]
    if any(c in cols0 for c in ("date", "month", "period")):
        return pd.read_csv(path)

    # scan first ~10 lines to find a row that looks like headers
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        lines = [next(f) for _ in range(50)]
    header_idx = None
    for i, line in enumerate(lines):
        low = line.strip().lower()
        if not low:
            continue
        if any(k in low for k in ("date", "month", "period")) and "," in line:
            header_idx = i
            break
    if header_idx is None:
        # fallback to default
        return pd.read_csv(path)
    return pd.read_csv(path, header=header_idx)

def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df

def _rename_by_aliases(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    alias_map = {
        "date": ["month", "period", "reporting month"],
        "entity": ["company", "org", "business unit", "bu"],
        "account": ["account_category", "gl account", "line item", "category", "acct", "account name", "name"],
        "amount": ["value", "total", "usd", "amount (usd)", "amount usd"],
        "currency": ["curr", "ccy"],
        "cash": ["cash balance", "balance", "ending cash"],
        "rate_to_usd": ["fx rate", "rate", "usd_per_unit", "rate to usd"],
    }
    for target, aliases in alias_map.items():
        if target in df.columns:
            continue
        for a in aliases:
            if a in df.columns:
                df.rename(columns={a: target}, inplace=True)
                break
    return df

def _ensure_date(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "date" not in df.columns:
        # try promoting first column if it looks like a date-ish name
        first = df.columns[0]
        if first.startswith("unnamed") or any(k in first for k in ("date", "month", "period")):
            df.rename(columns={first: "date"}, inplace=True)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
    return df

def _coerce_numeric(df: pd.DataFrame, cols) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = (
                df[c].astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("$", "", regex=False)
                .str.replace("%", "", regex=False)
            )
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def _numeric_like(s: pd.Series) -> bool:
    tmp = (
        s.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("%", "", regex=False)
    )
    n = pd.to_numeric(tmp, errors="coerce")
    # treat as numeric-like if we get at least a couple numeric values
    return n.notna().sum() >= 2

def _wide_to_long(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Aggressively melt wide sheets into account/amount for actuals/budget."""
    if kind not in ("actuals", "budget"):
        return df

    if "account" in df.columns and "amount" in df.columns:
        return df

    cols = list(df.columns)
    # Identify id vars first
    id_vars = [c for c in cols if c in BASE_KEYS]
    # Keep one descriptor if present
    for extra in ("account", "line item", "category", "department", "name"):
        if extra in cols:
            id_vars.append(extra)
            break
    id_vars = list(dict.fromkeys(id_vars))

    # Candidates to melt: not id_vars and either numeric-like OR name hints like Revenue/COGS/Opex
    cand = []
    for c in cols:
        if c in id_vars:
            continue
        if WIDE_NAME_HINTS.search(c) or _numeric_like(df[c]):
            cand.append(c)

    cand = [c for c in cand if c not in ("rate_to_usd", "cash")]  # don't melt fx/cash columns

    # If multiple candidates -> melt
    if len(cand) >= 2:
        melted = df.melt(id_vars=id_vars or ["date"], value_vars=cand,
                         var_name="account", value_name="amount")
        return melted

    # If exactly one numeric column -> promote to amount, try to find an account name column
    if len(cand) == 1 and "amount" not in df.columns:
        df = df.rename(columns={cand[0]: "amount"})
        for nm in ("account", "line item", "category", "name"):
            if nm in df.columns:
                df = df.rename(columns={nm: "account"})
                break
        return df

    return df

def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in set(df.columns) & {"currency", "entity", "account"}:
        df[c] = df[c].astype(str).str.strip()
    if "currency" in df.columns:
        df["currency"] = df["currency"].str.upper()
    return df

def _load_one(fixtures_dir: str, name: str) -> pd.DataFrame:
    path = os.path.join(fixtures_dir, f"{name}.csv")
    df = _read_csv_smart(path)
    df = _normalize_headers(df)
    df = _rename_by_aliases(df)
    df = _ensure_date(df)

    if name in ("actuals", "budget"):
        if "entity" not in df.columns:
            df["entity"] = "Consolidated"
        if "currency" not in df.columns:
            df["currency"] = "USD"
        df = _wide_to_long(df, name)
        # last chance: if we still don't have amount, promote the only numeric column
        if "amount" not in df.columns:
            numeric_cols = [c for c in df.columns if c not in BASE_KEYS and df[c].dtype.kind in "biufc"]
            if len(numeric_cols) == 1:
                df = df.rename(columns={numeric_cols[0]: "amount"})
        df = _coerce_numeric(df, ["amount"])
        if "account" not in df.columns or "amount" not in df.columns:
            # surface a helpful preview in the error
            raise ValueError(
                f"'{name}.csv' still lacks 'account'/'amount'. "
                f"Found columns: {list(df.columns)[:10]} …"
            )

    elif name == "fx":
        if "currency" not in df.columns:
            df["currency"] = "USD"
        if "rate_to_usd" not in df.columns and "rate" in df.columns:
            df.rename(columns={"rate": "rate_to_usd"}, inplace=True)
        if "rate_to_usd" not in df.columns:
            raise ValueError("'fx.csv' needs a 'rate_to_usd' column.")
        df = _coerce_numeric(df, ["rate_to_usd"])

    elif name == "cash":
        if "cash" not in df.columns and "amount" in df.columns:
            df.rename(columns={"amount": "cash"}, inplace=True)
        if "cash" not in df.columns:
            # promote a single numeric column if present
            numeric_cols = [c for c in df.columns if c not in BASE_KEYS and df[c].dtype.kind in "biufc"]
            if len(numeric_cols) == 1:
                df.rename(columns={numeric_cols[0]: "cash"}, inplace=True)
        if "cash" not in df.columns:
            raise ValueError("'cash.csv' needs a 'cash' column.")
        if "entity" not in df.columns:
            df["entity"] = "Consolidated"
        if "currency" not in df.columns:
            df["currency"] = "USD"
        df = _coerce_numeric(df, ["cash"])

    df = _finalize(df)
    return df

@st.cache_data(show_spinner=False)
def load_data(fixtures_dir: str = "fixtures"):
    dfs = {}
    for name in ["actuals", "budget", "fx", "cash"]:
        path = os.path.join(fixtures_dir, f"{name}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing file: {path}")
        dfs[name] = _load_one(fixtures_dir, name)
    return dfs

# ----------------------------
# UI
# ----------------------------
st.title("💼 CFO Copilot — FP&A Mini")
st.caption("Ask finance questions from monthly CSVs. Example: “What was June 2025 revenue vs budget?”")

with st.sidebar:
    st.header("Data status")
    try:
        dfs = load_data()
        for k, v in dfs.items():
            st.write(f"**{k}**: {v.shape[0]} rows • {v.shape[1]} cols")
        with st.expander("Preview first rows", expanded=False):
            for k, v in dfs.items():
                st.markdown(f"**{k}.csv**")
                st.dataframe(v.head(8), use_container_width=True)
        if st.button("Clear cache & reload"):
            load_data.clear()
            st.experimental_rerun()
    except Exception as e:
        st.error(f"Problem loading data: {e}")
        st.info(
            "If your sheet had Revenue/COGS/Opex as columns or the header wasn't on the first row, "
            "the app now auto-detects and unpivots. If you still see this, please open the CSV and "
            "share just the **header line** and 2–3 data rows so I can add an exact mapping."
        )
        st.stop()

q = st.text_input("Ask a question:", value=EXAMPLES[0], placeholder=EXAMPLES[0])

col1, col2 = st.columns([1, 3])
with col1:
    ask = st.button("Ask", type="primary")
with col2:
    st.markdown("Examples: " + " • ".join([f"_{ex}_" for ex in EXAMPLES]))

if ask or q:
    try:
        res = plan_and_execute(q, dfs)
        st.markdown("### Answer")
        st.write(res.get("text", ""))
        if res.get("chart") is not None:
            st.plotly_chart(res["chart"], use_container_width=True)
    except Exception as e:
        st.error("Sorry, something went wrong while processing your question.")
        with st.expander("Show error details"):
            st.exception(e)
