import unittest
from datetime import date

from engine import catalyst_signal, quarterly_revenue, qualify_company, screen_option


class ScreenTests(unittest.TestCase):
    def test_revenue_uses_quarter_and_year_prior_not_ytd_or_later_restatement(self):
        facts = {"facts": {"us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax": {
            "units": {"USD": [
                {"start": "2025-01-01", "end": "2025-03-31", "filed": "2025-05-01", "val": 80, "form": "10-Q"},
                {"start": "2026-01-01", "end": "2026-03-31", "filed": "2026-05-01", "val": 100, "form": "10-Q"},
                {"start": "2026-01-01", "end": "2026-03-31", "filed": "2026-05-10", "val": 108, "form": "10-Q"},
                {"start": "2026-01-01", "end": "2026-06-30", "filed": "2026-07-30", "val": 800, "form": "10-Q"},
            ]}}}}}
        rev = quarterly_revenue(facts, date(2026, 9, 22))
        self.assertAlmostEqual(rev["growth_pct"], 35.0)
        self.assertEqual(rev["current"], 108)

    def test_backlog_requires_cited_fresh_source(self):
        base = {"backlog_usd": 300, "annual_revenue_usd": 200,
                "asof": "2026-08-01", "source_url": "https://example.com/filing"}
        self.assertTrue(qualify_company(None, base, today=date(2026, 9, 22))["pass"])
        self.assertFalse(qualify_company(None, {**base, "source_url": ""}, today=date(2026, 9, 22))["pass"])
        self.assertFalse(qualify_company(None, {**base, "asof": "2024-01-01"}, today=date(2026, 9, 22))["pass"])

    def test_future_catalyst_requires_source_and_event_date(self):
        event = {"event_date": "2026-11-04", "event_type": "Earnings",
                 "source_url": "https://example.com/investor-event"}
        self.assertTrue(catalyst_signal(event, None, date(2026, 9, 22))["pass"])
        self.assertFalse(catalyst_signal({**event, "source_url": ""}, None, date(2026, 9, 22))["pass"])
        self.assertFalse(catalyst_signal({**event, "event_date": "2026-09-01"}, None, date(2026, 9, 22))["pass"])

    def test_option_rejects_untradeable_cheap_ask_and_calculates_expiry_2x(self):
        row = {"bid": .50, "ask": .65, "strike": 36,
               "volume": 7, "openInterest": 200, "expiration": "2026-10-16"}
        result = screen_option(row, 31.24, today=date(2026, 9, 22))
        self.assertTrue(result["pass"])
        self.assertAlmostEqual(result["breakeven"], 36.65)
        self.assertAlmostEqual(result["stock_for_2x_at_expiry"], 37.30)
        self.assertFalse(screen_option({**row, "bid": .05}, 31.24, today=date(2026, 9, 22))["pass"])
        self.assertFalse(screen_option({**row, "ask": .75}, 31.24, today=date(2026, 9, 22))["pass"])


if __name__ == "__main__":
    unittest.main()
