"""Option Finder: SEC fundamentals + broker-checkable public option quotes."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import time

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from engine import catalyst_signal, momentum, qualify_company, quarterly_revenue, score_company, screen_option

st.set_page_config(page_title="Option Finder", layout="wide")
st.title("Option Finder")
st.caption("Business quality first · budget and liquidity second · no win probabilities or price predictions")

DEFAULT_UNIVERSE = (
    "NVTS, MX, MRAM, QUIK, RFIL, INDI, AMSC, WULF, CIFR, SOFI, APLD, RIOT, "
    "OCC, AEHR, ALGM, AOSL, SLAB, POWI, IREN, HUT, MARA, IONQ, QBTS, RGTI, "
    "ASTS, RKLB, AMPX, ENVX, SERV, ARBE, CLFD, HIMS, UPST, HOOD, AFRM, "
    "SBLK, GNK, SB, GOGL, EGLE, ZIM, DAC, MATX, FRO, DHT, STNG, "
    "RXRX, SDGR, CRSP, NTLA, BEAM, EDIT, VERV, VKTX, MDGL, RYTM, "
    "OCUL, ABCL, KROS, CYTK, INSM, AXSM, EXAS, NTRA, "
    "ACHR, JOBY, LUNR, PL, BKSY, GCT, CELH, TOST, DUOL"
)
USER_AGENT = ""


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def sec_tickers(user_agent: str) -> dict:
    response = requests.get("https://www.sec.gov/files/company_tickers.json",
                            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=15)
    response.raise_for_status()
    return {str(v["ticker"]).upper(): int(v["cik_str"]) for v in response.json().values()}


@st.cache_data(ttl=8 * 3600, show_spinner=False)
def sec_facts(cik: int, user_agent: str) -> dict:
    response = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=20)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=15 * 60, show_spinner=False)
def stock_snapshot(ticker: str) -> dict:
    stock = yf.Ticker(ticker)
    hist = stock.history(period="5mo", auto_adjust=True)
    if hist.empty:
        raise ValueError("No stock history returned")
    try:
        cap = stock.fast_info.get("market_cap")
    except Exception:
        cap = None
    trend = momentum(hist["Close"].dropna().tolist(), hist["Volume"].dropna().tolist())
    return {"price": float(hist["Close"].iloc[-1]), "market_cap": cap,
            "trend": trend, "quote_day": hist.index[-1].date().isoformat()}


@st.cache_data(ttl=10 * 60, show_spinner=False)
def option_quotes(ticker: str, min_dte: int, max_dte: int) -> list[dict]:
    stock = yf.Ticker(ticker)
    rows = []
    for expiry in stock.options:
        dte = (date.fromisoformat(expiry) - date.today()).days
        if min_dte <= dte <= max_dte:
            calls = stock.option_chain(expiry).calls
            for rec in calls.to_dict("records"):
                rec["expiration"] = expiry
                rows.append(rec)
    return rows


with st.sidebar:
    st.header("Screen settings")
    tickers_input = st.text_area("Ticker universe (comma or space separated)", DEFAULT_UNIVERSE)
    email = st.text_input("Email for SEC identification", help="SEC asks automated callers to identify themselves. Used only in request headers.")
    max_price = st.number_input("Maximum share price ($)", min_value=1.0, value=25.0)
    min_cap = st.number_input("Minimum market cap ($ millions)", min_value=0, value=100)
    max_cap = st.number_input("Maximum market cap ($ billions)", min_value=1, value=15)
    min_growth = st.number_input("Minimum quarterly revenue YoY (%)", min_value=0, value=25)
    backlog_ratio = st.number_input("Minimum backlog / annual revenue", min_value=0.1, value=1.0, step=0.1)
    budget = st.number_input("Maximum cost per call ($)", min_value=1, value=65)
    min_dte = st.number_input("Minimum days to expiry", min_value=1, value=21)
    max_dte = st.number_input("Maximum days to expiry", min_value=1, value=120)
    need_signal = st.checkbox("Require momentum or sourced upcoming catalyst", value=True)

st.subheader("Documented backlog")
st.write("Optional: add backlog from a company filing or investor release. A dated HTTPS source is required; blank entries never count as backlog evidence.")
uploaded = st.file_uploader("Upload backlog CSV", type=["csv"])
st.caption("Columns: ticker, backlog_usd, prior_backlog_usd, annual_revenue_usd, asof, source_url. A template is included in the download.")
backlogs: dict[str, dict] = {}
if uploaded:
    try:
        data = pd.read_csv(uploaded).fillna("")
        required = {"ticker", "backlog_usd", "prior_backlog_usd", "annual_revenue_usd", "asof", "source_url"}
        if not required.issubset(data.columns):
            st.error(f"Backlog CSV needs these columns: {', '.join(sorted(required))}")
        else:
            backlogs = {str(row["ticker"]).strip().upper(): row.to_dict()
                        for _, row in data.iterrows() if str(row["ticker"]).strip()}
    except Exception as exc:
        st.error(f"Could not read backlog CSV: {exc}")

st.subheader("Upcoming events")
st.write("Optional: import confirmed earnings dates, regulatory decisions, contract milestones, or other events with a source link. An estimate without a confirming source should remain a research note, not a confirmed event.")
events_file = st.file_uploader("Upload catalysts CSV", type=["csv"], key="events")
catalysts: dict[str, dict] = {}
if events_file:
    try:
        frame = pd.read_csv(events_file).fillna("")
        required = {"ticker", "event_date", "event_type", "source_url"}
        if not required.issubset(frame.columns):
            st.error(f"Catalysts CSV needs these columns: {', '.join(sorted(required))}")
        else:
            catalysts = {str(row["ticker"]).strip().upper(): row.to_dict()
                         for _, row in frame.iterrows() if str(row["ticker"]).strip()}
    except Exception as exc:
        st.error(f"Could not read catalysts CSV: {exc}")

tickers = list(dict.fromkeys(t for t in re.split(r"[\s,;]+", tickers_input.upper().strip()) if t))[:100]
st.write(f"Universe: **{len(tickers)}** names. The scan starts only when you press the button.")
if not st.button("Scan companies", type="primary"):
    st.stop()
if not email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
    st.error("Enter an email to identify SEC requests.")
    st.stop()
USER_AGENT = f"Personal Option Finder {email}"
if not tickers:
    st.error("Add at least one ticker.")
    st.stop()

results, issues = [], []
try:
    cik_map = sec_tickers(USER_AGENT)
except Exception as exc:
    st.error(f"SEC ticker directory unavailable: {exc}")
    st.stop()

progress = st.progress(0)
for index, ticker in enumerate(tickers):
    try:
        cik = cik_map.get(ticker)
        if not cik:
            issues.append(f"{ticker}: no SEC CIK found (foreign filers and some listings may need manual review)")
            continue
        facts = sec_facts(cik, USER_AGENT)
        rev = quarterly_revenue(facts)
        q = qualify_company(rev, backlogs.get(ticker), min_growth, backlog_ratio)
        if not q["pass"]:
            issues.append(f"{ticker}: did not meet a documented revenue or backlog gate; no qualifying 10-Q may be available")
            continue
        snap = stock_snapshot(ticker)
        cap = snap["market_cap"]
        if snap["price"] > max_price or cap is None or not min_cap * 1e6 <= cap <= max_cap * 1e9:
            issues.append(f"{ticker}: share-price or market-cap filter; missing cap is excluded")
            continue
        signal = catalyst_signal(catalysts.get(ticker), snap["trend"])
        if need_signal and not signal["pass"]:
            issues.append(f"{ticker}: no documented upcoming event or measured 20-day momentum")
            continue
        company = {"ticker": ticker, "price": snap["price"], "quote_day": snap["quote_day"],
                   "market_cap_m": cap / 1e6, "growth_pct": q["growth_pct"],
                   "backlog_to_sales": q["backlog_to_sales"], "backlog_growth_pct": q["backlog_growth_pct"],
                   "qualified_by": q["reason"],
                   "score": min(100, score_company(q, snap["trend"]) +
                                (10 if signal["upcoming_catalyst"] else 0)),
                   "signal": ("event + momentum" if signal["upcoming_catalyst"] and signal["strong_trend"]
                              else "event" if signal["upcoming_catalyst"] else "momentum" if signal["strong_trend"] else "none"),
                   "event_date": catalysts.get(ticker, {}).get("event_date", ""),
                   "event_type": catalysts.get(ticker, {}).get("event_type", ""),
                   "event_source": catalysts.get(ticker, {}).get("source_url", ""),
                   "momentum_20d_pct": snap["trend"]["return_20d_pct"] if snap["trend"] else None,
                   "volume_ratio": snap["trend"]["volume_ratio"] if snap["trend"] else None,
                   "revenue_period_end": rev["quarter_end"].isoformat() if rev else None,
                   "revenue_filed": rev["filed"].isoformat() if rev else None,
                   "sec_filing": (f"https://www.sec.gov/Archives/edgar/data/{cik}/{rev['accession'].replace('-', '')}/"
                                  if rev and rev["accession"] else ""),
                   "backlog_source": backlogs.get(ticker, {}).get("source_url", "")}
        results.append(company)
    except Exception as exc:
        issues.append(f"{ticker}: data request failed ({type(exc).__name__}: {exc})")
    finally:
        progress.progress((index + 1) / len(tickers))
        # SEC fair-access ceiling is 10 requests/s; intentionally scan serially.
        time.sleep(0.12)

st.subheader("Companies passing the fundamental and size gates")
if not results:
    st.info("No names qualified with the currently available filed data. Try a wider universe or supply sourced backlog.")
else:
    results.sort(key=lambda r: r["score"], reverse=True)
    st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
    st.download_button("Download company screen CSV", pd.DataFrame(results).to_csv(index=False),
                       file_name="option_finder_companies.csv", mime="text/csv")
    st.subheader("Call contracts")
    st.caption("Asks are indicative public quotes, not guaranteed fills. Check Webull's live bid/ask before ordering.")
    options, option_issues = [], []
    for company in results[:15]:
        ticker = company["ticker"]
        try:
            for quote in option_quotes(ticker, int(min_dte), int(max_dte)):
                screened = screen_option(quote, company["price"], budget, int(min_dte), int(max_dte))
                if screened.get("pass"):
                    options.append({"ticker": ticker, "score": company["score"], **screened})
        except Exception as exc:
            option_issues.append(f"{ticker}: option chain unavailable ({type(exc).__name__})")
    if options:
        options.sort(key=lambda r: (-r["score"], r["move_to_2x_at_expiry_pct"], r["spread_pct"]))
        st.dataframe(pd.DataFrame(options), hide_index=True, use_container_width=True)
        st.download_button("Download qualifying calls CSV", pd.DataFrame(options).to_csv(index=False),
                           file_name="option_finder_calls.csv", mime="text/csv")
    else:
        st.info("No calls passed budget, expiry, distance, spread, open-interest and volume filters.")
    issues.extend(option_issues)

with st.expander("Coverage, math and exclusions"):
    st.write("SEC revenue uses standalone 70–110 day USD facts from 10-Q filings, compared with a matching year-prior quarter. "
             "A missing match, international reporting or company-specific revenue tags are left unavailable. "
             "Q4 is not inferred from annual 10-K figures. Backlog is entered manually, dated within 366 days and linked "
             "to an HTTPS source; it passes if backlog is at least annual revenue or backlog is up at least 25%. "
             "The score ranks documented growth and historical trend; it is not a probability of profit. "
             "The 2× price is the stock price needed for a call's expiration value to equal twice its ask. "
             "A call can double before expiration at a different stock price. Options can lose 100% of their cost.")
    if issues:
        st.write("Skipped names and data limitations:")
        st.dataframe(pd.DataFrame({"detail": issues}), hide_index=True, use_container_width=True)
