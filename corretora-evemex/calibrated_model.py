"""Modelo LightGBM com calibração sigmoid serializável entre processos."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression


class SigmoidCalibratedModel:
    def __init__(self, model: object, calibrator: LogisticRegression) -> None:
        self.model = model
        self.calibrator = calibrator

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        raw = self.model.predict_proba(features)[:, 1].reshape(-1, 1)
        calibrated = self.calibrator.predict_proba(raw)[:, 1]
        return np.column_stack((1.0 - calibrated, calibrated))
