from __future__ import annotations

import unittest

from evemexapi.models import Candle, PatternStats
from evemexapi.strategy import LivePatternDetector, calculate_pattern_stats, candle_color


def candle(index: int, color: str, symbol: str = "TEST_otc") -> Candle:
    opening = 10.0
    close = 11.0 if color == "G" else 9.0 if color == "R" else 10.0
    return Candle(symbol, "1m", index * 60, (index + 1) * 60, opening, 12.0, 8.0, close)


def green_occurrences(wins: int, losses: int) -> list[Candle]:
    result: list[Candle] = []
    index = 0
    for is_win in [True] * wins + [False] * losses:
        for color in ("G", "G", "G", "R" if is_win else "G", "D"):
            result.append(candle(index, color))
            index += 1
    return result


class StrategyTests(unittest.TestCase):
    def test_exact_color_classification(self):
        self.assertEqual(candle_color(candle(0, "G")), "GREEN")
        self.assertEqual(candle_color(candle(0, "R")), "RED")
        self.assertEqual(candle_color(candle(0, "D")), "DOJI")

    def test_threshold_is_strictly_above_sixty_percent(self):
        stats_12 = calculate_pattern_stats(green_occurrences(12, 8))["GREEN"]
        stats_13 = calculate_pattern_stats(green_occurrences(13, 7))["GREEN"]
        self.assertEqual((stats_12.sample_size, stats_12.wins), (20, 12))
        self.assertFalse(stats_12.qualifies)
        self.assertEqual((stats_13.sample_size, stats_13.wins), (20, 13))
        self.assertTrue(stats_13.qualifies)

    def test_only_last_twenty_occurrences_are_used(self):
        candles = green_occurrences(5, 5) + [
            Candle(c.symbol, c.timeframe, c.from_ts + 10000, c.to_ts + 10000, c.open, c.high, c.low, c.close)
            for c in green_occurrences(13, 7)
        ]
        stats = calculate_pattern_stats(candles)["GREEN"]
        self.assertEqual(stats.sample_size, 20)
        self.assertEqual(stats.wins, 13)

    def test_live_detector_blocks_overlapping_sequence(self):
        detector = LivePatternDetector()
        stats = {
            "GREEN": PatternStats("TEST_otc", "GREEN", 20, 13, 0.65),
            "RED": PatternStats("TEST_otc", "RED", 20, 13, 0.65),
        }
        first = detector.evaluate("TEST_otc", [candle(0, "G"), candle(1, "G"), candle(2, "G")], stats)
        overlap = detector.evaluate("TEST_otc", [candle(1, "G"), candle(2, "G"), candle(3, "G")], stats)
        self.assertIsNotNone(first)
        self.assertEqual(first.direction, "DOWN")
        self.assertIsNone(overlap)
        detector.observe_closed("TEST_otc", candle(3, "R"))
        self.assertFalse(detector.is_blocked("TEST_otc"))

    def test_doji_releases_block(self):
        detector = LivePatternDetector()
        stats = {"GREEN": PatternStats("TEST_otc", "GREEN", 20, 20, 1.0)}
        detector.evaluate("TEST_otc", [candle(0, "G"), candle(1, "G"), candle(2, "G")], stats)
        detector.observe_closed("TEST_otc", candle(3, "D"))
        self.assertFalse(detector.is_blocked("TEST_otc"))


if __name__ == "__main__":
    unittest.main()

