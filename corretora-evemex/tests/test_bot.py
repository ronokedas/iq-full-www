from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evemexapi.models import Account, Candle, PatternStats, Signal
from evemexapi.strategy import calculate_pattern_stats
from reversal_bot import JsonlLogger, ReversalBot, RiskManager, extract_operation_id


class StubClient:
    def __init__(self):
        self.selected_account = Account("demo", 1, "DEMO", 10000)

    def server_time(self):
        return 179.1


class MemoryLogger:
    def __init__(self):
        self.events = []

    def write(self, event, **fields):
        self.events.append((event, fields))


def candle(index: int, close: float) -> Candle:
    return Candle("A_otc", "1m", index * 60, (index + 1) * 60, 10, 12, 8, close)


def qualified_history(symbol: str, pattern: str) -> list[Candle]:
    rows = []
    index = -200
    same_close = 11 if pattern == "GREEN" else 9
    win_close = 9 if pattern == "GREEN" else 11
    for occurrence in range(20):
        outcome_close = win_close if occurrence < 13 else same_close
        for close in (same_close, same_close, same_close, outcome_close, 10):
            rows.append(Candle(symbol, "1m", index * 60, (index + 1) * 60, 10, 12, 8, close))
            index += 1
    return rows


class BotTests(unittest.TestCase):
    def test_risk_limits_and_stop_loss(self):
        risk = RiskManager(stop_loss=5, max_operations=2)
        self.assertEqual(risk.allowed(5), 2)
        self.assertTrue(risk.reserve())
        self.assertTrue(risk.reserve())
        self.assertTrue(risk.stopped)
        risk.release_failed()
        risk.record_profit(-5)
        self.assertTrue(risk.stopped)

    def test_extract_operation_id_from_supported_shapes(self):
        self.assertEqual(extract_operation_id({"result": {"id": "a"}}), "a")
        self.assertEqual(extract_operation_id({"operationId": "b"}), "b")
        self.assertIsNone(extract_operation_id({"ok": True}))

    def test_builds_all_qualified_signals(self):
        logger = MemoryLogger()
        bot = ReversalBot(StubClient(), amount=2, stop_loss=0, max_operations=0, dry_run=True, logger=logger)
        bot.symbols = ["A_otc", "B_otc"]
        bot.history = {
            "A_otc": qualified_history("A_otc", "GREEN"),
            "B_otc": qualified_history("B_otc", "RED"),
        }
        bot.stats = {
            symbol: calculate_pattern_stats(history, symbol=symbol)
            for symbol, history in bot.history.items()
        }
        batch = {
            "A_otc": [candle(0, 11), candle(1, 11), candle(2, 11)],
            "B_otc": [
                Candle("B_otc", "1m", c.from_ts, c.to_ts, c.open, c.high, c.low, c.close)
                for c in [candle(0, 9), candle(1, 9), candle(2, 9)]
            ],
        }
        signals = bot.build_signals(batch)
        self.assertEqual({signal.symbol for signal in signals}, {"A_otc", "B_otc"})
        self.assertEqual({signal.direction for signal in signals}, {"UP", "DOWN"})

    def test_dry_run_honors_maximum_and_logs(self):
        logger = MemoryLogger()
        bot = ReversalBot(StubClient(), amount=2, stop_loss=0, max_operations=1, dry_run=True, logger=logger)
        signals = [
            Signal("B_otc", "GREEN", "DOWN", 0.65, 13, 20, 120),
            Signal("A_otc", "RED", "UP", 0.80, 16, 20, 120),
        ]
        bot.execute_signals(signals, {"A_otc": 240, "B_otc": 240})
        simulated = [fields for event, fields in logger.events if event == "dry_run_operation"]
        self.assertEqual(len(simulated), 1)
        self.assertEqual(simulated[0]["symbol"], "A_otc")

    def test_json_logger_writes_valid_line(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = JsonlLogger(Path(directory))
            logger.write("test", value=1)
            content = logger.path.read_text(encoding="utf-8")
            self.assertIn('"event":"test"', content)


if __name__ == "__main__":
    unittest.main()
