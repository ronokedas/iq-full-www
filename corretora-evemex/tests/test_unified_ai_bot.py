from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
from evemexapi import Candle
from feature_builders import S01_FEATURES, S5_M5_FEATURES
from unified_ai_bot import FeatureBuilder, UnifiedAIBot, _ask_strategies, _parse_strategy_choice, detect_s13


class MemoryLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def write(self, event: str, **fields) -> None:
        self.events.append((event, fields))


class TradingClient:
    def __init__(self) -> None:
        self.opened: list[tuple[str, float, str, int]] = []

    def select_expiration(self, symbol: str, timeframe_seconds: int):
        return 600 + timeframe_seconds, {"symbol": symbol}

    def open_operation(self, symbol: str, amount: float, direction: str, expiration: int, *, expiration_tf_sec: int):
        self.opened.append((symbol, amount, direction, expiration, expiration_tf_sec))
        return {"result": {"id": f"op-{len(self.opened)}"}}


class OfflineClient:
    connected = False

    def __init__(self) -> None:
        self.attempts = 0

    def connect(self) -> bool:
        self.attempts += 1
        return False


class AlwaysApprovedModel:
    def predict_proba(self, features):
        return np.array([[0.2, 0.8]])


class ClockClient:
    def __init__(self, now: float) -> None:
        self.now = now

    def server_time(self) -> float:
        return self.now


class UnifiedAIBotTests(unittest.TestCase):
    @staticmethod
    def candle(open_: float, close: float, high: float, low: float, timestamp: int) -> Candle:
        return Candle("TEST_otc", "1m", timestamp, timestamp + 60, open_, high, low, close)

    def make_bot(self, client) -> UnifiedAIBot:
        # execute_signals e _force_reconnect não precisam carregar modelos de IA.
        bot = object.__new__(UnifiedAIBot)
        bot.client = client
        bot.amount = 2.0
        bot.logger = MemoryLogger()
        bot.pending = {}
        return bot

    def test_every_approved_signal_opens_an_operation_without_blocking(self):
        client = TradingClient()
        bot = self.make_bot(client)
        signals = [
            {"symbol": "A_otc", "strategy": "S01", "direction": "UP", "proba": 0.70},
            {"symbol": "B_otc", "strategy": "S13", "direction": "DOWN", "proba": 0.80},
            {"symbol": "C_otc", "strategy": "S16", "direction": "UP", "proba": 0.90},
            {"symbol": "D_otc", "strategy": "S01", "direction": "DOWN", "proba": 0.60},
        ]

        with patch("builtins.print"):
            bot.execute_signals(signals)

        self.assertEqual([call[0] for call in client.opened], ["A_otc", "B_otc", "C_otc", "D_otc"])
        self.assertEqual([call[2] for call in client.opened], ["UP", "DOWN", "UP", "DOWN"])
        self.assertEqual([call[4] for call in client.opened], [60, 60, 300, 60])
        self.assertEqual(set(bot.pending), {"op-1", "op-2", "op-3", "op-4"})

    def test_strategy_selector_accepts_individual_combined_and_all_choices(self):
        self.assertEqual(_parse_strategy_choice("1"), {"s01"})
        self.assertEqual(_parse_strategy_choice("2"), {"s13"})
        self.assertEqual(_parse_strategy_choice("1,2"), {"s01", "s13"})
        self.assertEqual(_parse_strategy_choice("0"), {"s01", "s13"})
        self.assertIsNone(_parse_strategy_choice("3"))

    def test_strategy_menu_shows_live_s01_status(self):
        with patch("builtins.input", return_value="1"), patch("builtins.print") as printer:
            self.assertEqual(_ask_strategies("live"), {"s01"})
        self.assertIn("entradas automáticas", " ".join(str(call) for call in printer.call_args_list))

    def test_s13_candidate_shadow_never_opens_a_broker_order(self):
        client = TradingClient()
        bot = self.make_bot(client)
        bot.s13_candidate = {"model": AlwaysApprovedModel(), "features": ["atr_14"], "threshold": .75}
        bot.policy = {"candidates": {"s13": {"mode": "shadow", "shadow_campaign": "test"}}}
        bot.s13_shadow_pending = {}
        history = [self.candle(10, 11, 12, 9, index * 60) for index in range(60)]
        details = {"signal_bucket": 59 * 60}
        with patch.object(FeatureBuilder, "build_s13", return_value={"atr_14": 1.0}), patch("builtins.print"):
            bot._process_s13_candidate("TEST_otc", "UP", history, details)
        self.assertEqual(client.opened, [])
        self.assertIn(("TEST_otc", 60 * 60), bot.s13_shadow_pending)

    def test_failed_reconnection_returns_false_after_five_attempts(self):
        client = OfflineClient()
        bot = self.make_bot(client)

        with patch("unified_ai_bot.time.sleep"), patch("builtins.print"):
            self.assertFalse(bot._force_reconnect())

        self.assertEqual(client.attempts, 5)

    def test_s13_opens_put_after_three_green_candles_hold_below_first_high(self):
        candles = [
            self.candle(10.0, 11.0, 12.0, 9.5, 0),
            self.candle(10.8, 11.2, 11.5, 10.5, 60),
            self.candle(11.0, 11.4, 11.7, 10.8, 120),
        ]
        self.assertEqual(detect_s13(candles), "DOWN")

    def test_s13_opens_call_after_three_red_candles_hold_above_first_low(self):
        candles = [
            self.candle(13.0, 12.0, 13.5, 11.0, 0),
            self.candle(12.2, 11.8, 12.5, 11.5, 60),
            self.candle(12.0, 11.6, 12.2, 11.3, 120),
        ]
        self.assertEqual(detect_s13(candles), "UP")

    def test_s13_rejects_when_a_later_green_closes_at_or_above_first_high(self):
        candles = [
            self.candle(10.0, 11.0, 12.0, 9.5, 0),
            self.candle(10.8, 11.2, 11.5, 10.5, 60),
            self.candle(11.4, 12.0, 12.2, 11.2, 120),
        ]
        self.assertIsNone(detect_s13(candles))

    def test_s13_requires_a_real_wick_on_first_candle(self):
        candles = [
            self.candle(13.0, 12.0, 13.5, 12.0, 0),
            self.candle(12.5, 11.8, 12.7, 11.5, 60),
            self.candle(12.0, 11.6, 12.2, 11.3, 120),
        ]
        self.assertIsNone(detect_s13(candles))

    def test_s13_does_not_require_the_first_wick_to_be_largest(self):
        candles = [
            self.candle(13.0, 12.0, 13.5, 11.9, 0),
            self.candle(12.5, 11.95, 12.7, 11.2, 60),
            self.candle(12.2, 11.93, 12.3, 11.2, 120),
        ]
        self.assertEqual(detect_s13(candles), "UP")

    def test_s13_rejects_when_a_later_red_closes_at_or_below_first_low(self):
        candles = [
            self.candle(13.0, 12.0, 13.5, 11.0, 0),
            self.candle(12.5, 11.8, 12.7, 11.5, 60),
            self.candle(12.0, 11.0, 12.2, 10.8, 120),
        ]
        self.assertIsNone(detect_s13(candles))

    def test_s13_preclose_uses_live_third_candle_and_logs_pattern_metadata(self):
        now = 59 * 60 + 59.0
        bot = object.__new__(UnifiedAIBot)
        bot.client = ClockClient(now)
        bot.apply_hour_filter = False
        bot.policy = {"strategies": {"s13": {"active": True}}}
        bot.models = {"s13": {"model": AlwaysApprovedModel(), "features": [
            "atr_14", "std_14", "trend_slope", "hour_sin", "hour_cos", "rsi_14", "atr_pct",
            "dist_ema9", "dist_ema21", "body_ratio", "avg_body_5", "dist_res_h1", "dist_sup_h1",
        ], "threshold": 0.65}}
        history = [self.candle(10, 11, 12, 9, index * 60) for index in range(57)]
        v1 = self.candle(13.0, 12.0, 13.5, 11.0, 57 * 60)
        v2 = self.candle(12.2, 11.8, 12.5, 11.5, 58 * 60)
        live_v3 = self.candle(12.0, 11.6, 12.2, 11.3, 59 * 60)
        bot.history = {"TEST_otc": history + [v1, v2]}

        with patch("builtins.print"):
            found = bot.scan_s13_preclose({"TEST_otc": [v1, v2, live_v3]}, now)

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["direction"], "UP")
        self.assertEqual(found[0]["signal_timing"], "preclose_second_59")
        self.assertEqual(found[0]["signal_bucket"], 59 * 60)
        self.assertEqual(found[0]["v3"]["from_ts"], live_v3.from_ts)

    def test_s13_preclose_rejects_snapshot_after_the_candle_closed(self):
        now = 60 * 60 + 0.1
        bot = object.__new__(UnifiedAIBot)
        self.assertEqual(bot.scan_s13_preclose({}, now), [])

    def test_s13_late_order_is_cancelled_before_opening(self):
        client = ClockClient(60 * 60 + 0.1)
        bot = self.make_bot(client)
        bot.logger = MemoryLogger()
        signal = {"symbol": "TEST_otc", "strategy": "S13", "direction": "UP", "proba": .8,
                  "signal_timing": "preclose_second_59", "signal_bucket": 59 * 60}
        with patch("builtins.print"):
            bot.execute_signals([signal])
        self.assertEqual(bot.pending, {})
        self.assertEqual(bot.logger.events[0][0], "blocked_late_s13")

    def test_s01_late_order_is_cancelled_after_two_second_window(self):
        client = ClockClient(60 * 60 + 2.1)
        bot = self.make_bot(client)
        signal = {"symbol": "TEST_otc", "strategy": "S01", "direction": "UP", "proba": .8,
                  "signal_timing": "postclose_first_2_seconds", "entry_from_ts": 60 * 60}
        with patch("builtins.print"):
            bot.execute_signals([signal])
        self.assertEqual(bot.pending, {})
        self.assertEqual(bot.logger.events[0][0], "blocked_late_s01")

    def test_s01_shadow_records_signal_without_opening_order(self):
        client = TradingClient()
        bot = self.make_bot(client)
        bot.s01_shadow_pending = {}
        signal = {"symbol": "TEST_otc", "strategy": "S01", "direction": "UP", "proba": .8,
                  "execution_mode": "shadow", "entry_from_ts": 60 * 60}
        bot.execute_signals([signal])
        self.assertEqual(client.opened, [])
        self.assertIn(("TEST_otc", 60 * 60), bot.s01_shadow_pending)

    def test_s5_m5_is_disabled_in_s13_only_execution_mode(self):
        now = 60 * 60 + 59.0
        bot = object.__new__(UnifiedAIBot)
        bot.client = ClockClient(now)
        bot.apply_hour_filter = False
        bot.policy = {"strategies": {"s5_m5": {"active": True}}}
        bot.models = {"s5_m5": {"model": AlwaysApprovedModel(), "features": S5_M5_FEATURES, "threshold": 0.65}}
        bot.logger = MemoryLogger()
        bot.sent_s5_keys = set()
        generic = [self.candle(10.0, 10.0, 10.2, 9.8, index * 60) for index in range(55)]
        command = [
            self.candle(10.0, 10.1, 10.2, 10.0, 55 * 60),
            self.candle(10.1, 10.2, 10.4, 10.05, 56 * 60),
            self.candle(10.2, 10.3, 10.5, 10.1, 57 * 60),
            self.candle(10.3, 10.4, 10.6, 10.2, 58 * 60),
            self.candle(10.4, 11.0, 11.0, 10.3, 59 * 60),
        ]
        touch = self.candle(10.5, 10.2, 10.6, 10.0, 60 * 60)
        bot.history = {"TEST_otc": generic + command}

        found = bot.scan_s5_m5_preclose({"TEST_otc": generic + command + [touch]}, now)

        self.assertEqual(found, [])

    def test_production_feature_vectors_match_published_model_schemas(self):
        m1_history = [self.candle(10, 11, 12, 9, index * 60) for index in range(60)]
        m5_history = [self.candle(10, 11, 12, 9, index * 300) for index in range(15)]
        m1_features = FeatureBuilder.build_m1(m1_history)
        s01_features = FeatureBuilder.build_s01(m1_history, "UP")
        m5_features = FeatureBuilder.build_m5(m5_history)
        base = Path(__file__).parent.parent
        saved = joblib.load(base / "signal_filter_s01.pkl")
        self.assertEqual(set(saved["features"]), set(S01_FEATURES))
        self.assertEqual(set(saved["features"]), set(s01_features))
        saved = joblib.load(base / "signal_filter_s13.pkl")
        self.assertEqual(set(saved["features"]), set(m1_features))
        saved = joblib.load(base / "signal_filter_s16.pkl")
        self.assertEqual(set(saved["features"]), set(m5_features))
        saved = joblib.load(base / "signal_filter_s5_m5.pkl")
        self.assertEqual(set(saved["features"]), set(S5_M5_FEATURES))


if __name__ == "__main__":
    unittest.main()
