from __future__ import annotations

import unittest

import pandas as pd

from lab.s5_m15.core import Command, aggregate_complete_m15, backtest_asset, commands_from_m15, select_most_recent_touch


def candle(ts: int, open_: float, high: float, low: float, close: float) -> dict:
    return {"from_ts": ts, "open": open_, "high": high, "low": low, "close": close}


class S5M15LabTests(unittest.TestCase):
    def green_command(self) -> list[dict]:
        rows = [candle(0, 10.0, 10.2, 10.0, 10.1)]
        rows.extend(candle(index * 60, 10.1, 10.4, 10.05, 10.2) for index in range(1, 15))
        return rows

    def test_green_command_first_confirmed_touch_enters_next_m1(self):
        rows = self.green_command() + [
            candle(900, 10.5, 10.6, 10.0, 10.2),
            candle(960, 10.2, 10.5, 10.1, 10.4),
        ]
        trades, metrics = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(metrics["commands"], 1)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "UP")
        self.assertEqual(trades[0]["entry_from_ts"], 960)
        self.assertEqual(trades[0]["target"], 1)

    def test_red_command_and_strict_equality(self):
        red = [candle(0, 11.0, 11.0, 10.5, 10.8)]
        red.extend(candle(index * 60, 10.8, 10.95, 10.4, 10.6) for index in range(1, 15))
        rows = red + [candle(900, 10.5, 11.0, 10.4, 10.8), candle(960, 10.8, 10.9, 10.3, 10.5)]
        trades, _ = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(trades[0]["direction"], "DOWN")
        red[0]["high"] = 11.0001
        self.assertEqual(commands_from_m15(aggregate_complete_m15(pd.DataFrame(red))), [])

    def test_incomplete_block_and_expired_or_invalid_first_touch(self):
        self.assertTrue(aggregate_complete_m15(pd.DataFrame(self.green_command()[:14])).empty)
        rows = self.green_command() + [candle(900, 10.2, 10.4, 10.0, 10.3), candle(960, 10.5, 10.6, 10.0, 10.2)]
        trades, metrics = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(trades, [])
        self.assertEqual(metrics["first_touches_invalidated"], 1)
        old = Command(0, 900, 2100, 10.0, "GREEN")
        recent = Command(900, 1800, 3000, 10.0, "GREEN")
        selected, _ = select_most_recent_touch([old, recent], candle(1800, 10.2, 10.3, 10.0, 10.1))
        self.assertEqual(selected, recent)


if __name__ == "__main__":
    unittest.main()
