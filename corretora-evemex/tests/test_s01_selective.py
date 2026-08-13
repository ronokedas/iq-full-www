from __future__ import annotations

import unittest

import pandas as pd
from pathlib import Path
from tempfile import TemporaryDirectory

from feature_builders import S01_FEATURES, s01_feature_frame
from retrain_s01_selective import choose_policy
from unified_ai_bot import JsonlLogger, UnifiedAIBot
from start_s13_candidate_shadow import THRESHOLD as S13_CANDIDATE_THRESHOLD


class S01SelectiveTests(unittest.TestCase):
    def test_indicators_are_real_and_schema_is_complete(self):
        rows = []
        for index in range(80):
            open_ = 100 + index * .1
            close = open_ + (.3 if index % 3 else -.2)
            rows.append({"from_ts": index * 60, "open": open_, "high": max(open_, close) + .2, "low": min(open_, close) - .2, "close": close})
        features = s01_feature_frame(pd.DataFrame(rows), ["UP"] * len(rows))
        self.assertEqual(list(features.columns), S01_FEATURES)
        self.assertGreater(features.iloc[-1]["rsi_14"], 0)
        self.assertNotEqual(features.iloc[-1]["atr_pct"], .1)
        self.assertTrue(features.iloc[-1].notna().all())

    def test_policy_requires_one_hundred_qualified_signals_in_each_fold(self):
        rows = []
        for fold in (1, 2, 3):
            rows.extend({"fold": fold, "probability": .75, "target": 1 if index < 60 else 0, "from_ts": index * 60} for index in range(100))
        policy = choose_policy(pd.DataFrame(rows), [{"fold": index, "test_samples": 100, "base_winrate": .6} for index in (1, 2, 3)])
        self.assertEqual(policy["mode"], "shadow")
        self.assertEqual(policy["threshold"], .75)

    def test_policy_stays_disabled_when_a_fold_has_insufficient_signals(self):
        rows = []
        for fold in (1, 2, 3):
            count = 99 if fold == 2 else 100
            rows.extend({"fold": fold, "probability": .75, "target": 1, "from_ts": index * 60} for index in range(count))
        policy = choose_policy(pd.DataFrame(rows), [{"fold": index, "test_samples": 100, "base_winrate": 1.0} for index in (1, 2, 3)])
        self.assertEqual(policy["mode"], "disabled")

    def test_shadow_campaign_records_are_isolated_and_reported(self):
        with TemporaryDirectory() as directory:
            logger = JsonlLogger(Path(directory))
            logger.write("s01_shadow_result", shadow_campaign="old", target=1, entry_from_ts=0, symbol="OLD", proba=.75)
            logger.write("s01_shadow_result", shadow_campaign="new", target=1, entry_from_ts=3600, symbol="TEST", proba=.65)
            records = logger.s01_shadow_records("new")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["symbol"], "TEST")

    def test_s13_candidate_pending_signal_is_restored_after_restart(self):
        with TemporaryDirectory() as directory:
            logger = JsonlLogger(Path(directory))
            logger.write("s13_candidate_shadow_opened", shadow_campaign="candidate", symbol="TEST", entry_from_ts=120, proba=.8)
            self.assertIn(("TEST", 120), logger.pending_s13_candidate_shadows("candidate"))
            logger.write("s13_candidate_shadow_result", shadow_campaign="candidate", symbol="TEST", entry_from_ts=120, target=1)
            self.assertEqual(logger.pending_s13_candidate_shadows("candidate"), {})

    def test_s13_candidate_campaign_uses_sixty_five_percent_threshold(self):
        self.assertEqual(S13_CANDIDATE_THRESHOLD, .65)


if __name__ == "__main__":
    unittest.main()
