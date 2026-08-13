from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from calibrated_model import SigmoidCalibratedModel
from retrain_models import ENTRY_THRESHOLD, _target, build_policy
from unified_ai_bot import UnifiedAIBot


class TradingPolicyTests(unittest.TestCase):
    class RawModel:
        def predict_proba(self, features):
            raw = features["raw"].to_numpy()
            return np.column_stack((1 - raw, raw))

    def test_sigmoid_calibrator_returns_probability_in_unit_interval(self):
        calibrator = LogisticRegression().fit([[0.1], [0.2], [0.8], [0.9]], [0, 0, 1, 1])
        model = SigmoidCalibratedModel(self.RawModel(), calibrator)
        probabilities = model.predict_proba(pd.DataFrame({"raw": [0.1, 0.9]}))[:, 1]
        self.assertTrue(np.all((probabilities >= 0) & (probabilities <= 1)))
        self.assertGreater(probabilities[1], probabilities[0])
    def test_target_uses_the_immediate_expiration_candle(self):
        next_candle = {"open": 10, "close": 11}
        self.assertEqual(_target(next_candle, "UP"), 1)
        self.assertEqual(_target(next_candle, "DOWN"), 0)

    def test_hour_is_released_only_with_minimum_samples_and_winrate(self):
        predictions = pd.DataFrame({
            "probability": [ENTRY_THRESHOLD] * 100 + [ENTRY_THRESHOLD] * 99,
            "target": [1] * 60 + [0] * 40 + [1] * 99,
            "from_ts": [0] * 100 + [3600] * 99,
        })
        policy = build_policy("s01", predictions, [])
        self.assertIn(21, policy["allowed_hours_brasilia"])  # UTC 00:00 = Brasília 21:00.
        self.assertNotIn(22, policy["allowed_hours_brasilia"])
        self.assertTrue(policy["active"])

    def test_disabled_strategy_and_hour_filter_block_signals(self):
        bot = object.__new__(UnifiedAIBot)
        bot.apply_hour_filter = True
        bot.policy = {"strategies": {"s01": {"active": False, "allowed_hours_brasilia": list(range(24))}}}
        self.assertIn("desativada", bot._policy_reason("s01", 0))
        bot.policy["strategies"]["s01"]["active"] = True
        bot.policy["strategies"]["s01"]["allowed_hours_brasilia"] = []
        self.assertIn("horário", bot._policy_reason("s01", 0))
        bot.apply_hour_filter = False
        self.assertIsNone(bot._policy_reason("s01", 0))

    def test_strategy_is_inactive_when_any_walk_forward_fold_has_no_qualified_signal(self):
        predictions = pd.DataFrame({"probability": [0.7] * 100, "target": [1] * 65 + [0] * 35, "from_ts": [0] * 100})
        folds = [
            {"winrate_65": 0.65},
            {"winrate_65": None},
            {"winrate_65": 0.65},
        ]
        self.assertFalse(build_policy("s16", predictions, folds)["active"])

    def test_strategy_is_active_at_exactly_sixty_percent_in_every_fold(self):
        predictions = pd.DataFrame({"probability": [0.7] * 100, "target": [1] * 60 + [0] * 40, "from_ts": [0] * 100})
        folds = [{"winrate_65": 0.60}, {"winrate_65": 0.60}, {"winrate_65": 0.60}]
        self.assertTrue(build_policy("s5_m5", predictions, folds)["active"])


if __name__ == "__main__":
    unittest.main()
