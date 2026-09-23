"""Transparent fundamentals and option filters for a research watchlist."""
from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from typing import Any

REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)


def _parse_day(value: str) -> date:
    return date.fromisoformat(value[:10])


def quarterly_revenue(companyfacts: dict[str, Any], today: date | None = None) -> dict[str, Any] | None:
    """Use filed, standalone 10-Q quarter facts; pair equivalent prior-year periods.

    Annual and year-to-date facts are intentionally excluded. A fiscal Q4 derived
    from a 10-K is not inferred and remains unavailable until a valid 10-Q is filed.
    """
    today = today or date.today()
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    matches = []
    for tag in REVENUE_TAGS:
        rows = us_gaap.get(tag, {}).get("units", {}).get("USD", [])
        candidates = []
        for row in rows:
            try:
                start, end, filed = map(_parse_day, (row["start"], row["end"], row["filed"]))
                val = float(row["val"])
            except (KeyError, ValueError, TypeError):
                continue
            if (row.get("form") != "10-Q" or not 70 <= (end - start).days <= 110
                    or filed > today or end > today or val <= 0 or not isfinite(val)):
                continue
            candidates.append({"start": start, "end": end, "filed": filed,
                               "value": val, "accn": row.get("accn", ""),
                               "fy": row.get("fy"), "fp": row.get("fp")})
        # Amended and comparative repetitions: prefer the latest filed version.
        by_period = {}
        for row in candidates:
            key = (row["start"], row["end"])
            if key not in by_period or row["filed"] > by_period[key]["filed"]:
                by_period[key] = row
        periods = sorted(by_period.values(), key=lambda r: (r["end"], r["filed"]), reverse=True)
        for curr in periods:
            prior = next((p for p in periods if 330 <= (curr["end"] - p["end"]).days <= 400
                          and abs((curr["end"] - curr["start"]).days -
                                  (p["end"] - p["start"]).days) <= 12
                          and (curr["start"] - p["start"]).days >= 330), None)
            if prior and 0 <= (today - curr["end"]).days <= 200:
                matches.append({"current": curr["value"], "prior": prior["value"],
                        "growth_pct": 100 * (curr["value"] / prior["value"] - 1),
                        "quarter_end": curr["end"], "filed": curr["filed"],
                        "source_tag": tag, "accession": curr["accn"]})
                break
    return max(matches, key=lambda m: (m["quarter_end"], m["filed"])) if matches else None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (ValueError, TypeError):
        return None


def qualify_company(revenue: dict | None, backlog: dict | None,
                    min_growth: float = 25.0, min_backlog_ratio: float = 1.0,
                    today: date | None = None) -> dict:
    """Two explicit paths; sourced backlog must be dated within 12 months."""
    today = today or date.today()
    growth = revenue["growth_pct"] if revenue else None
    growth_pass = growth is not None and growth >= min_growth
    backlog_pass, ratio, backlog_growth = False, None, None
    if backlog:
        current = _number(backlog.get("backlog_usd"))
        annual = _number(backlog.get("annual_revenue_usd"))
        prior = _number(backlog.get("prior_backlog_usd"))
        url = str(backlog.get("source_url", "")).strip()
        try:
            asof = _parse_day(backlog["asof"])
        except (KeyError, ValueError, TypeError):
            asof = None
        source_ok = bool(url.startswith("https://") and asof and 0 <= (today - asof).days <= 366)
        if current is not None and current > 0 and annual and annual > 0:
            ratio = current / annual
        if current is not None and prior and prior > 0:
            backlog_growth = 100 * (current / prior - 1)
        backlog_pass = bool(source_ok and ((ratio is not None and ratio >= min_backlog_ratio)
                                           or (backlog_growth is not None and backlog_growth >= 25)))
    return {"pass": growth_pass or backlog_pass,
            "revenue_pass": growth_pass, "backlog_pass": backlog_pass,
            "growth_pct": growth, "backlog_to_sales": ratio,
            "backlog_growth_pct": backlog_growth,
            "reason": "revenue + backlog" if growth_pass and backlog_pass else
                      "revenue" if growth_pass else "backlog" if backlog_pass else "neither"}


def momentum(closes: list[float], volumes: list[float]) -> dict | None:
    if len(closes) < 61 or len(volumes) < 21:
        return None
    try:
        last, old20, old60 = [float(x) for x in (closes[-1], closes[-21], closes[-61])]
        recent_vol = sum(float(x) for x in volumes[-5:]) / 5
        past_vol = sum(float(x) for x in volumes[-21:-5]) / 16
        if min(last, old20, old60, past_vol) <= 0:
            return None
        return {"return_20d_pct": 100 * (last / old20 - 1),
                "return_60d_pct": 100 * (last / old60 - 1),
                "volume_ratio": recent_vol / past_vol,
                "above_20d_avg": last > sum(closes[-20:]) / 20}
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def score_company(qualification: dict, trend: dict | None) -> int:
    if not qualification["pass"]:
        return 0
    score = 40
    if qualification["revenue_pass"]:
        score += min(25, max(0, int((qualification["growth_pct"] - 25) / 2) + 10))
    if qualification["backlog_pass"]:
        score += 10
    if trend:
        score += 8 if trend["return_20d_pct"] > 0 else 0
        score += 7 if trend["return_60d_pct"] > 0 else 0
        score += 5 if trend["above_20d_avg"] else 0
        score += 5 if trend["volume_ratio"] >= 1.5 else 0
    return min(score, 100)


def catalyst_signal(catalyst: dict | None, trend: dict | None,
                    today: date | None = None) -> dict:
    """A dated future event or a measurable uptrend can make a near-term watchlist."""
    today = today or date.today()
    upcoming = False
    if catalyst:
        try:
            event_day = _parse_day(catalyst["event_date"])
            upcoming = bool(str(catalyst.get("source_url", "")).strip().startswith("https://")
                            and str(catalyst.get("event_type", "")).strip()
                            and 0 <= (event_day - today).days <= 120)
        except (KeyError, TypeError, ValueError):
            pass
    strong_trend = bool(trend and trend["return_20d_pct"] >= 5
                        and trend["above_20d_avg"] and trend["volume_ratio"] >= 1.2)
    return {"pass": upcoming or strong_trend, "upcoming_catalyst": upcoming,
            "strong_trend": strong_trend}


def screen_option(row: dict, stock_price: float, max_cost: float = 65,
                  min_dte: int = 21, max_dte: int = 120,
                  today: date | None = None) -> dict:
    """Return executable-cost math, not a probability or a price forecast."""
    today = today or date.today()
    bid, ask = _number(row.get("bid")), _number(row.get("ask"))
    strike = _number(row.get("strike"))
    volume, oi = _number(row.get("volume")) or 0, _number(row.get("openInterest")) or 0
    try:
        expiry = _parse_day(row["expiration"])
        dte = (expiry - today).days
    except (ValueError, TypeError, KeyError):
        dte = -1
    flags = []
    if not ask or ask <= 0 or bid is None or bid < 0 or bid > ask or not strike or stock_price <= 0:
        flags.append("invalid quote")
        return {"pass": False, "flags": flags}
    cost = ask * 100
    spread_pct = 100 * (ask - bid) / ask
    distance_pct = 100 * (strike / stock_price - 1)
    if cost > max_cost: flags.append("over budget")
    if not min_dte <= dte <= max_dte: flags.append("expiration outside range")
    if not 0 <= distance_pct <= 50: flags.append("strike distance outside 0–50%")
    if spread_pct > 25: flags.append("wide spread")
    if oi < 50: flags.append("low open interest")
    if volume < 1: flags.append("no trading today")
    try:
        trade_day = datetime.fromisoformat(str(row.get("lastTradeDate", "")).replace("Z", "+00:00")).date()
        if (today - trade_day).days > 5: flags.append("stale last trade")
    except ValueError:
        pass
    return {"pass": not flags, "flags": flags, "cost_usd": cost, "dte": dte,
            "spread_pct": spread_pct, "distance_pct": distance_pct,
            "breakeven": strike + ask,
            "move_to_breakeven_pct": 100 * ((strike + ask) / stock_price - 1),
            "stock_for_2x_at_expiry": strike + 2 * ask,
            "move_to_2x_at_expiry_pct": 100 * ((strike + 2 * ask) / stock_price - 1),
            "bid": bid, "ask": ask, "strike": strike, "expiration": row["expiration"],
            "volume": int(volume), "open_interest": int(oi)}
