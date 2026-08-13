from __future__ import annotations

import unittest

import pandas as pd

from lab.s5_m5.core import Command, aggregate_complete_m5, backtest_asset, select_most_recent_touch


def candle(ts: int, open_: float, high: float, low: float, close: float) -> dict:
    return {"from_ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": 0}


class S5M5LabTests(unittest.TestCase):
    def green_command(self) -> list[dict]:
        return [
            candle(0, 10, 10.2, 10, 10.1), candle(60, 10.1, 10.4, 10.05, 10.2),
            candle(120, 10.2, 10.5, 10.1, 10.3), candle(180, 10.3, 10.6, 10.2, 10.4),
            candle(240, 10.4, 11, 10.3, 11),
        ]

    def test_green_command_first_confirmed_touch_opens_call_on_next_candle(self):
        rows = self.green_command() + [
            candle(300, 10.5, 10.6, 10, 10.2),  # vermelho, fecha acima do nível 10
            candle(360, 10.2, 10.5, 10.1, 10.4),  # resultado CALL vencedor
        ]
        trades, metrics = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(metrics["commands"], 1)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "UP")
        self.assertEqual(trades[0]["entry_from_ts"], 360)
        self.assertEqual(trades[0]["target"], 1)

    def test_red_command_first_confirmed_touch_opens_put_on_next_candle(self):
        rows = [
            candle(0, 11, 11, 10.8, 10.9), candle(60, 10.9, 10.95, 10.5, 10.7),
            candle(120, 10.7, 10.8, 10.3, 10.5), candle(180, 10.5, 10.7, 10.1, 10.3),
            candle(240, 10.3, 10.5, 10.0, 10.0),
            candle(300, 10.5, 11.0, 10.4, 10.8),  # verde, fecha abaixo do nível 11
            candle(360, 10.8, 10.9, 10.4, 10.5),  # resultado PUT vencedor
        ]
        trades, _ = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "DOWN")
        self.assertEqual(trades[0]["target"], 1)

    def test_strict_equality_rejects_near_command(self):
        rows = self.green_command()
        rows[0]["low"] = 9.9999
        m5 = aggregate_complete_m5(pd.DataFrame(rows))
        trades, metrics = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(len(m5), 1)
        self.assertEqual(metrics["commands"], 0)
        self.assertEqual(trades, [])

    def test_incomplete_m5_block_is_ignored(self):
        rows = self.green_command()[:4]
        m5 = aggregate_complete_m5(pd.DataFrame(rows))
        self.assertTrue(m5.empty)

    def test_first_unconfirmed_touch_invalidates_command(self):
        rows = self.green_command() + [
            candle(300, 10.2, 10.4, 10, 10.3),  # verde: toca, mas não confirma CALL
            candle(360, 10.5, 10.6, 10, 10.2),  # segundo toque seria confirmado, mas não vale
            candle(420, 10.2, 10.5, 10.1, 10.4),
        ]
        trades, _ = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(trades, [])

    def test_touch_after_twenty_m1_candles_expires_command(self):
        rows = self.green_command()
        rows.extend(candle(ts, 10.5, 10.7, 10.2, 10.6) for ts in range(300, 1500, 60))
        rows.extend([candle(1500, 10.5, 10.6, 10, 10.2), candle(1560, 10.2, 10.4, 10.1, 10.3)])
        trades, _ = backtest_asset(pd.DataFrame(rows), "TEST")
        self.assertEqual(trades, [])

    def test_most_recent_command_wins_when_levels_are_touched_together(self):
        old = Command(0, 300, 1500, 10.0, "GREEN")
        recent = Command(300, 600, 1800, 10.0, "GREEN")
        selected, consumed = select_most_recent_touch([old, recent], candle(600, 10.2, 10.3, 10.0, 10.1))
        self.assertEqual(selected, recent)
        self.assertEqual(set(consumed), {old, recent})


if __name__ == "__main__":
    unittest.main()
