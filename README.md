# Option Finder

A Streamlit screen for **small and mid-cap growth companies with tradeable calls**. It is a research shortlist, not an automated trade or a forecast.

## Run

1. Unzip this folder. In a terminal in `option_finder`, run:

   ```bash
   python -m pip install -r requirements.txt
   streamlit run app.py
   ```

2. Enter your email in the left sidebar. SEC asks scripted visitors to identify themselves via the `User-Agent` header. The email is sent to SEC in this header and is not saved by the app.
3. Edit the ticker list and filters, then press **Scan companies**. The sector-agnostic starter universe includes power, software, shipping, healthcare, biotech and other industries. It is not exhaustive; expand it with your own tickers (up to 100 per scan). Broad scans make many SEC and market-data calls and may be slow or throttled; narrow the list if needed.
4. If a company reports a backlog, copy `backlog_template.csv`, add its backlog in **dollars** (not millions), the comparable previous backlog if known, trailing annual revenue if known, report date (`YYYY-MM-DD`), and a direct HTTPS link to the report. Upload the CSV before scanning. The app never invents backlog data.
5. For a specific event, copy `catalyst_template.csv`, add a dated *confirmed* event and an HTTPS source link, and upload it before scanning. Earnings, regulatory milestones, contracts and launches may qualify if the date is within the next 120 days. A company's growth story alone does not establish an upcoming event. You can turn off the momentum/event gate in the sidebar.
6. Open the company's SEC filing and backlog/event source from the results. Open its option chain in your broker and verify the **current** bid, ask, volume, open interest, expiration and buying power.

## What passes

- **Fundamentals:** at least 25% revenue growth against a matching prior-year 10-Q quarter; **or** documented backlog at least 1× annual revenue; **or** backlog growth at least 25% from a comparable prior backlog. Backlog sources must be no older than 366 days and have an HTTPS link. Change the revenue and backlog ratio cutoffs in the sidebar.
- **Size:** share price ≤ $25, market cap $100 million–$15 billion by default. Unknown market cap fails the size gate.
- **Near-term signal:** a documented, future event within 120 days **or** a stock up at least 5% over 20 trading sessions, above its 20-session average, with recent volume at least 1.2× the prior 16 sessions. This requirement can be disabled in the sidebar.
- **Options:** public ask × 100 ≤ $65, expiry 21–120 days out, strike 0–50% above spot, bid/ask spread ≤ 25% of ask, open interest ≥ 50 and day's volume ≥ 1. Missing quotes do not pass.
- **Ranking:** documented growth/backlog first, then prior 20/60 session price momentum and a five-session volume ratio. Ranking does **not** predict returns or assign win probability.

The option table includes the stock's **break-even at expiration** (`strike + ask`) and the stock price for **2× option value at expiration** (`strike + 2 × ask`). The latter means twice the contract cost returned, i.e. 100% profit before fees, **if held to expiration**. Prior to expiration, the option may reach 2× at a different underlying stock price because time value and implied volatility vary.

## Data and important limits

- SEC XBRL Company Facts: quarterly revenue from common US-GAAP USD tags on 10-Qs, with a standalone 70–110 day period and a quarter ending within the past 200 days. 10-K fourth quarters, uncommon custom tags and many foreign issuers are not inferred and may be skipped. Repeated historical facts are deduplicated by their reporting period.
- Yahoo Finance via `yfinance`: adjusted price history, indicative market cap, and public options quotes. Quotes may be delayed, missing, or inconsistent; never use a market order on the strength of this screen. Results are cached 10–15 minutes; SEC filings are cached eight hours.
- The list covers the names entered, not the whole market. The size gate will naturally remove large or newly repriced starter names.
- Backlog can be conditional, cancelable, or spread over years. Annual revenue must describe the same company and period as the backlog. Verify every source yourself.
- Earnings dates are not inferred; align expiration with confirmed company announcements yourself. A cheap far-out call can expire worthless even when the business grows.

Sources: [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [SEC fair access](https://www.sec.gov/about/developer-resources), [yfinance option-chain documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html).

## Tests

```bash
python -m unittest discover -s tests -v
```
