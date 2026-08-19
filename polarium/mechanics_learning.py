"""Coleta append-only da Mecânica para treinamento futuro no Polarium Full."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from app_runtime import data_path

OPENED_EVENT = "mechanics_learning_observed"
RESULT_EVENT = "mechanics_learning_result"
INVALID_EVENT = "mechanics_learning_invalid"
EXECUTION_EVENT = "mechanics_learning_execution"
SCHEMA_VERSION = "mechanics-learning-v1"
SNAPSHOT_EVERY = 1000


class MechanicsLearning:
    def __init__(self, log_directory: Path, logger: Any, directory: Path | None = None) -> None:
        self.log_directory = Path(log_directory)
        self.logger = logger
        self.directory = directory or data_path(Path("data") / "mechanics_learning")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.visual_directory = data_path(Path("data") / "visual_learning")
        self.visual_directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.pending: dict[str, dict[str, Any]] = {}
        self.resolved: dict[str, dict[str, Any]] = {}
        self._restore()

    @staticmethod
    def signal_id(signal: dict[str, Any]) -> str:
        identity = "|".join(str(signal.get(key, "")) for key in (
            "rule_version", "symbol", "direction", "level", "pivot_from_ts", "validated_from_ts", "trigger_from_ts", "entry_from_ts"
        ))
        return "mec-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    def _restore(self) -> None:
        execution_updates: dict[str, dict[str, Any]] = {}
        for path in sorted(self.log_directory.glob("unified-trades-*.jsonl")):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    item = json.loads(line)
                    signal_id = str(item.get("signal_id", ""))
                    if not signal_id:
                        continue
                    if item.get("event") == OPENED_EVENT:
                        self.pending[signal_id] = {key: value for key, value in item.items() if key not in {"event", "timestamp"}}
                    elif item.get("event") in {RESULT_EVENT, INVALID_EVENT}:
                        self.pending.pop(signal_id, None)
                        self.resolved[signal_id] = item
                    elif item.get("event") == EXECUTION_EVENT:
                        update = dict(item)
                        if item.get("operational_status") == "financial_result":
                            update["financial_result"] = item.get("result")
                            update["financial_profit"] = item.get("profit")
                        execution_updates[signal_id] = update
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        for signal_id, update in execution_updates.items():
            target = self.pending.get(signal_id) or self.resolved.get(signal_id)
            if target is not None:
                target.update({key: value for key, value in update.items() if key not in {"event", "timestamp", "signal_id"}})

    def observe(self, signal: dict[str, Any]) -> str:
        signal_id = self.signal_id(signal)
        if signal_id in self.pending or signal_id in self.resolved:
            return signal_id
        record = {**signal, "signal_id": signal_id, "schema_version": SCHEMA_VERSION,
                  "operational_status": "detected", "financial_result": None, "financial_profit": None}
        with self._lock:
            self.pending[signal_id] = record
            self.logger.write(OPENED_EVENT, **record)
        return signal_id

    def update_execution(self, signal_id: str, operational_status: str, **extra: Any) -> None:
        with self._lock:
            target = self.pending.get(signal_id) or self.resolved.get(signal_id)
            if target is not None:
                target["operational_status"] = operational_status
                target.update(extra)
                self.logger.write(EXECUTION_EVENT, signal_id=signal_id, operational_status=operational_status, **extra)

    def resolve(self, signal_id: str, outcome: str, profit: float | None = None, **extra: Any) -> None:
        with self._lock:
            record = self.pending.pop(signal_id, None)
            if record is None:
                return
            record["financial_result"] = outcome
            record["financial_profit"] = profit
            record.update(extra)
            self.resolved[signal_id] = record
            self.logger.write(RESULT_EVENT, signal_id=signal_id, outcome=outcome, profit=profit, **extra)
