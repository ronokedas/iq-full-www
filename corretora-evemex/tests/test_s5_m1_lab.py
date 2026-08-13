from __future__ import annotations

import unittest

import pandas as pd

from lab.s5_m1.core import Command, backtest_asset, commands_from_m1, select_most_recent_touch


def candle(ts: int, open_: float, high: float, low: float, close: float) -> dict:
    return {"from_ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": 0}


class S5M1LabTests(unittest.TestCase):
    def test_green_command_first_confirmed_touch_opens_call_on_next_candle(self):
        rows = [
            candle(0, 10, 10.5, 10, 10.4),
            candle(60, 10.5, 10.6, 10, 10.2),
            candle(120, 10.2, 10.5, 10.1, 10.4),
        ]
        trades, metrics = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(metrics["commands"], 1)
        self.assertEqual(trades[0]["direction"], "UP")
        self.assertEqual(trades[0]["entry_from_ts"], 120)
        self.assertEqual(trades[0]["target"], 1)

    def test_red_command_first_confirmed_touch_opens_put_on_next_candle(self):
        rows = [
            candle(0, 11, 11, 10.5, 10.6),
            candle(60, 10.5, 11, 10.4, 10.8),
            candle(120, 10.8, 10.9, 10.3, 10.5),
        ]
        trades, _ = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(trades[0]["direction"], "DOWN")
        self.assertEqual(trades[0]["target"], 1)

    def test_strict_equality_rejects_near_command(self):
        rows = [candle(0, 10, 10.5, 9.9999, 10.4)]
        self.assertEqual(commands_from_m1(pd.DataFrame(rows)), [])

    def test_first_unconfirmed_touch_invalidates_command_without_second_attempt(self):
        rows = [
            candle(0, 10, 10.5, 10, 10.4),
            candle(60, 10.2, 10.5, 10, 10.3),  # verde: toque inválido para CALL
            candle(120, 10.5, 10.6, 10, 10.2),  # seria confirmado, mas já foi consumido
            candle(180, 10.2, 10.5, 10.1, 10.4),
        ]
        trades, metrics = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(trades, [])
        self.assertEqual(metrics["first_touches_invalidated"], 1)

    def test_touch_after_twenty_candles_expires_command(self):
        rows = [candle(0, 10, 10.5, 10, 10.4)]
        rows.extend(candle(ts, 10.5, 10.6, 10.2, 10.5) for ts in range(60, 21 * 60, 60))
        rows.extend([candle(21 * 60, 10.5, 10.6, 10, 10.2), candle(22 * 60, 10.2, 10.5, 10.1, 10.4)])
        trades, _ = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(trades, [])

    def test_recent_command_wins_when_touch_hits_multiple_levels(self):
        old = Command(0, 60, 1260, 10.0, "GREEN")
        recent = Command(60, 120, 1320, 10.0, "GREEN")
        selected, consumed = select_most_recent_touch([old, recent], candle(120, 10.3, 10.4, 10.0, 10.2))
        self.assertEqual(selected, recent)
        self.assertEqual(set(consumed), {old, recent})

    def test_doji_result_is_loss(self):
        rows = [
            candle(0, 10, 10.5, 10, 10.4),
            candle(60, 10.5, 10.6, 10, 10.2),
            candle(120, 10.2, 10.4, 10.1, 10.2),
        ]
        trades, _ = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(trades[0]["target"], 0)


if __name__ == "__main__":
    unittest.main()
