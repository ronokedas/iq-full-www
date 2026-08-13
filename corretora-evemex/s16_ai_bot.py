"""Robô S16 (Fundo Duplo / Topo Duplo) com filtro de IA na Evemex.

Estratégia: 4 velas M5 — V1 de cor oposta, V2 toca o nível de V1, V3 confirma
a reversão (literal). A IA (LightGBM) filtra o sinal: entrada apenas se
P(WIN) >= 0.55 (Regra de Ouro).

Regra de nível único: cada região de preço só pode ser usada UMA vez.
"""

from __future__ import annotations

import argparse
import getpass
import json
import joblib
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Garante que o pacote evemexapi seja encontrado independente do diretório de execução
sys.path.append(str(Path(__file__).parent))

from evemexapi import Candle, EvemexAPIError, EvemexClient


class JsonlLogger:
    def __init__(self, directory: Path = Path("logs")) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"trades-s16-{datetime.now():%Y-%m-%d}.jsonl"
        self._lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


class RiskManager:
    def __init__(self, *, stop_loss: float, max_operations: int) -> None:
        self.stop_loss = max(0.0, float(stop_loss))
        self.max_operations = max(0, int(max_operations))
        self.operations = 0
        self.realized_pnl = 0.0
        self._lock = threading.Lock()

    @property
    def stopped(self) -> bool:
        with self._lock:
            return self._stopped_unlocked()

    def allowed(self, requested: int) -> int:
        with self._lock:
            if self._stopped_unlocked():
                return 0
            if self.max_operations == 0:
                return max(0, requested)
            return max(0, min(requested, self.max_operations - self.operations))

    def reserve(self) -> bool:
        with self._lock:
            if self._stopped_unlocked():
                return False
            if self.max_operations and self.operations >= self.max_operations:
                return False
            self.operations += 1
            return True

    def release_failed(self) -> None:
        with self._lock:
            self.operations = max(0, self.operations - 1)

    def record_profit(self, profit: float) -> None:
        with self._lock:
            self.realized_pnl = round(self.realized_pnl + float(profit), 2)

    def _stopped_unlocked(self) -> bool:
        if self.max_operations and self.operations >= self.max_operations:
            return True
        return bool(self.stop_loss and self.realized_pnl <= -self.stop_loss)


def extract_operation_id(payload: dict[str, Any]) -> str | None:
    candidates: list[Any] = [payload]
    for key in ("result", "operation", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for item in candidates:
        if isinstance(item, dict):
            value = item.get("operationId", item.get("operation_id", item.get("id")))
            if value is not None and str(value):
                return str(value)
    return None


def pip_scale(close: float) -> float:
    return 1e-4 if close < 100 else 1e-2


def aggregate_m5(candles: list[Candle]) -> list[Candle]:
    """Agrega candles M1 em M5 (mesma lógica do backtest/dataset)."""
    if not candles:
        return []
    df = pd.DataFrame([asdict(c) for c in candles])
    df = df.sort_values("from_ts").reset_index(drop=True)
    ts5 = (df["from_ts"] // 300) * 300
    m5 = df.groupby(ts5).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        from_ts=("from_ts", "last"),
    ).reset_index(drop=True)
    return [
        Candle(
            from_ts=int(row["from_ts"]),
            to_ts=int(row["from_ts"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for _, row in m5.iterrows()
    ]


def detect_s16(m5: list[Candle], tol_pips: float = 0.5) -> tuple[str, int] | None:
    """Detecta o padrão S16 literal nas últimas 4 velas M5.

    Retorna (direção, from_ts da vela de confirmação) se o padrão for confirmado.

    COMPRA (CALL):
      - V1 fecha VERMELHA (fundo)
      - V2 abre VERDE e toca o nível de V1 (open de V2 ≈ close de V1)
      - V3 fecha VERMELHA (confirmação da reversão para cima)

    VENDA (PUT):
      - V1 fecha VERDE (topo)
      - V2 abre VERMELHA e toca o nível de V1
      - V3 fecha VERDE (confirmação da reversão para baixo)
    """
    if len(m5) < 4:
        return None
    recent = sorted(m5, key=lambda c: c.from_ts)[-4:]
    v1, v2, v3, _ = recent
    scale = pip_scale(v1.close)
    tol = scale * tol_pips
    nivel = v1.close

    # COMPRA
    if v1.close < v1.open and v2.close > v2.open and abs(v2.open - nivel) <= tol:
        if v3.low <= nivel + scale and v3.close < v3.open:
            return "CALL", v3.from_ts

    # VENDA
    if v1.close > v1.open and v2.close < v2.open and abs(v2.open - nivel) <= tol:
        if v3.high >= nivel - scale and v3.close > v3.open:
            return "PUT", v3.from_ts

    return None


class S16FeatureBuilder:
    """Constrói o vetor de features para o modelo de IA (mesmas do treinamento)."""

    def __init__(self, history: list[Candle]) -> None:
        self.history = sorted(history, key=lambda candle: candle.from_ts)

    def build(self) -> dict[str, float] | None:
        """Calcula as features na última vela M5 fechada."""
        if len(self.history) < 30:
            return None

        df = pd.DataFrame([asdict(c) for c in self.history])
        df["from"] = df["from_ts"]
        df = df.set_index("from")

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        open_ = df["open"].astype(float)

        # Volatilidade
        tr = np.maximum(
            high - low,
            np.maximum(
                abs(high - close.shift(1)),
                abs(low - close.shift(1)),
            ),
        )
        atr_14 = tr.rolling(14).mean().iloc[-1]
        std_14 = close.rolling(14).std().iloc[-1]

        # Tendência
        ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
        trend_slope = (ema9 - ema21) / ema21 * 100

        # Sazonalidade
        dt = pd.to_datetime(df.index[-1], unit="s")
        hour_sin = np.sin(2 * np.pi * dt.hour / 24)
        hour_cos = np.cos(2 * np.pi * dt.hour / 24)

        # Corpos/pavios (últimos 5 candles)
        body_size = abs(close - open_)
        upper_wick = high - pd.concat([open_, close], axis=1).max(axis=1)
        lower_wick = pd.concat([open_, close], axis=1).min(axis=1) - low
        rg = high - low
        body_ratio = body_size / rg.replace(0, np.nan)
        upper_wick_ratio = upper_wick / rg.replace(0, np.nan)
        lower_wick_ratio = lower_wick / rg.replace(0, np.nan)

        avg_body_5 = body_size.rolling(5).mean().iloc[-1]
        avg_upper_wick_5 = upper_wick.rolling(5).mean().iloc[-1]
        avg_lower_wick_5 = lower_wick.rolling(5).mean().iloc[-1]
        avg_body_ratio_5 = body_ratio.rolling(5).mean().iloc[-1]
        avg_upper_wick_ratio_5 = upper_wick_ratio.rolling(5).mean().iloc[-1]
        avg_lower_wick_ratio_5 = lower_wick_ratio.rolling(5).mean().iloc[-1]

        # Suporte/Resistência (M15 = 3 velas M5, H1 = 12 velas M5)
        res_m15 = high.rolling(3).max().iloc[-1]
        sup_m15 = low.rolling(3).min().iloc[-1]
        res_h1 = high.rolling(12).max().iloc[-1]
        sup_h1 = low.rolling(12).min().iloc[-1]

        pip_scale_arr = 1e-4 if close.iloc[-1] < 100 else 1e-2
        dist_res_m15 = (res_m15 - close.iloc[-1]) / pip_scale_arr
        dist_sup_m15 = (close.iloc[-1] - sup_m15) / pip_scale_arr
        dist_res_h1 = (res_h1 - close.iloc[-1]) / pip_scale_arr
        dist_sup_h1 = (close.iloc[-1] - sup_h1) / pip_scale_arr

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_14 = (100 - (100 / (1 + rs))).iloc[-1]

        # Momentum
        mom_3 = close.pct_change(3).iloc[-1] * 100
        mom_5 = close.pct_change(5).iloc[-1] * 100

        atr_pct = atr_14 / close.iloc[-1] * 100
        dist_ema9 = (close.iloc[-1] - ema9) / ema9 * 100
        dist_ema21 = (close.iloc[-1] - ema21) / ema21 * 100

        return {
            "atr_14": float(atr_14),
            "std_14": float(std_14),
            "trend_slope": float(trend_slope),
            "hour_sin": float(hour_sin),
            "hour_cos": float(hour_cos),
            "avg_body_5": float(avg_body_5),
            "avg_upper_wick_5": float(avg_upper_wick_5),
            "avg_lower_wick_5": float(avg_lower_wick_5),
            "avg_body_ratio_5": float(avg_body_ratio_5),
            "avg_upper_wick_ratio_5": float(avg_upper_wick_ratio_5),
            "avg_lower_wick_ratio_5": float(avg_lower_wick_ratio_5),
            "dist_res_m15": float(dist_res_m15),
            "dist_sup_m15": float(dist_sup_m15),
            "dist_res_h1": float(dist_res_h1),
            "dist_sup_h1": float(dist_sup_h1),
            "rsi_14": float(rsi_14),
            "mom_3": float(mom_3),
            "mom_5": float(mom_5),
            "atr_pct": float(atr_pct),
            "dist_ema9": float(dist_ema9),
            "dist_ema21": float(dist_ema21),
            "body_ratio": float(body_ratio.iloc[-1]),
            "upper_wick_ratio": float(upper_wick_ratio.iloc[-1]),
            "lower_wick_ratio": float(lower_wick_ratio.iloc[-1]),
        }


class S16AIBot:
    def __init__(
        self,
        client: EvemexClient,
        *,
        model_path: str,
        amount: float,
        stop_loss: float,
        max_operations: int,
        confidence_threshold: float = 0.55,
        dry_run: bool = False,
        logger: JsonlLogger | None = None,
    ) -> None:
        self.client = client
        self.amount = round(float(amount), 2)
        self.dry_run = dry_run
        self.logger = logger or JsonlLogger()
        self.risk = RiskManager(stop_loss=stop_loss, max_operations=max_operations)
        self.confidence_threshold = float(confidence_threshold)

        # Carregar modelo de IA
        model_data = joblib.load(model_path)
        self.model = model_data["model"]
        self.features = list(model_data["features"])

        self.symbols: list[str] = []
        self.history: dict[str, list[Candle]] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.used_levels: dict[str, list[float]] = {}
        self._last_cycle_minute: int | None = None
        self._total_signals = 0
        self._approved_signals = 0

    def initialize(self) -> None:
        assets = self.client.get_otc_assets(detailed=True)
        self.symbols = sorted(
            str(asset["symbol"])
            for asset in assets
            if isinstance(asset.get("symbol"), str) and str(asset["symbol"]).endswith("_otc")
        )
        if not self.symbols:
            raise EvemexAPIError("Nenhum ativo OTC ativo foi encontrado")
        self.client.get_expirations(self.symbols[0])
        print(f"Carregando histórico de {len(self.symbols)} ativos OTC...")
        for index, symbol in enumerate(self.symbols, start=1):
            candles = self._load_history(symbol)
            self.history[symbol] = candles
            self.used_levels[symbol] = []
            print(f"[{index:02d}/{len(self.symbols):02d}] {symbol}: {len(candles)} velas M1")
        print(f"Modelo de IA carregado: {len(self.features)} features | "
              f"threshold={self.confidence_threshold:.0%}")

    def run(self, *, once: bool = False) -> None:
        print(
            f"Robô S16+IA ativo | conta={self.client.selected_account.mode if self.client.selected_account else '?'} "
            f"| entrada=R$ {self.amount:.2f} | dry-run={'sim' if self.dry_run else 'não'}"
        )
        while not self.risk.stopped:
            self.refresh_results()
            self._sync_before_cycle()
            server_now = self.client.server_time()
            minute = int(server_now // 60)
            if self._last_cycle_minute == minute:
                time.sleep(0.1)
                continue

            self._wait_for_second(58.5)
            pre_candles = self.client.get_candles_batch(self.symbols, "1m", 30)
            self._prefetch_candidates(pre_candles)

            self._wait_for_second(59.0)
            final_candles = self.client.get_candles_batch(self.symbols, "1m", 30)
            signals = self.build_signals(final_candles)
            self.execute_signals(signals)
            self._last_cycle_minute = int(self.client.server_time() // 60)

            if once:
                print("Ciclo único concluído.")
                return
            self._wait_until_next_cycle()

        reason = "limite de operações" if self.risk.max_operations and self.risk.operations >= self.risk.max_operations else "stop-loss"
        print(f"Robô encerrado por {reason}. P&L: R$ {self.risk.realized_pnl:.2f}")

    def build_signals(self, batch: dict[str, list[Candle]]) -> list[dict[str, Any]]:
        """Detecta sinais S16 e aplica o filtro de IA.

        Returns:
            Lista de dicts com símbolo, direção, confiança e features.
        """
        signals: list[dict[str, Any]] = []
        current_minute = int(self.client.server_time() // 60) * 60
        for symbol in self.symbols:
            candles = sorted(batch.get(symbol, []), key=lambda item: item.from_ts)
            closed = [candle for candle in candles if candle.from_ts < current_minute]

            if not closed:
                continue

            # Atualizar histórico M1
            merged = {candle.from_ts: candle for candle in self.history.get(symbol, [])}
            merged.update({candle.from_ts: candle for candle in closed})
            self.history[symbol] = sorted(merged.values(), key=lambda candle: candle.from_ts)[-5000:]

            # Agregar em M5
            m5 = aggregate_m5(self.history[symbol])
            if len(m5) < 4:
                continue

            # Detectar S16 nas últimas 4 velas M5
            signal_info = detect_s16(m5)
            if signal_info is None:
                continue

            direction, signal_ts = signal_info
            self._total_signals += 1

            # Regra de nível único: verificar se o nível já foi usado
            nivel = m5[-3].close  # V1 (fundo/topo)
            scale = pip_scale(nivel)
            region_tol = scale * 2.0
            used = self.used_levels.get(symbol, [])
            if any(abs(nivel - u) <= region_tol for u in used):
                self.logger.write("signal_skipped", symbol=symbol, reason="level_already_used")
                continue

            # Construir features para o modelo
            builder = S16FeatureBuilder(m5)
            features = builder.build()
            if features is None:
                continue

            # Filtrar apenas as features usadas no treinamento
            missing = [f for f in self.features if f not in features]
            if missing:
                self.logger.write("ai_missing_features", symbol=symbol, missing=missing)
                continue

            x = pd.DataFrame([{f: features[f] for f in self.features}])
            proba = float(self.model.predict_proba(x)[0, 1])

            self.logger.write(
                "signal_detected",
                symbol=symbol,
                direction=direction,
                probability=round(proba, 4),
                approved=bool(proba >= self.confidence_threshold),
            )

            if proba < self.confidence_threshold:
                continue

            self._approved_signals += 1
            self.used_levels[symbol].append(nivel)
            signals.append({
                "symbol": symbol,
                "direction": direction,
                "probability": proba,
                "candle_from": signal_ts,
            })

        return sorted(signals, key=lambda s: -s["probability"])

    def execute_signals(self, signals: list[dict[str, Any]]) -> None:
        allowed = self.risk.allowed(len(signals))
        selected = signals[:allowed]
        for skipped in signals[allowed:]:
            self.logger.write("signal_skipped", symbol=skipped["symbol"], reason="session_limit")
        if not selected:
            return

        expirations = self._prefetch_expirations([s["symbol"] for s in selected])

        if self.dry_run:
            for signal in selected:
                if not self.risk.reserve():
                    continue
                expiration = expirations.get(signal["symbol"])
                self.logger.write(
                    "dry_run_operation",
                    symbol=signal["symbol"],
                    direction=signal["direction"],
                    amount=self.amount,
                    expiration_at=expiration,
                    probability=signal["probability"],
                )
                print(
                    f"[DRY-RUN] {signal['symbol']} {signal['direction']} | "
                    f"P(WIN)={signal['probability']:.1%}"
                )
            return

        with ThreadPoolExecutor(max_workers=min(12, len(selected))) as executor:
            future_map = {}
            for signal in selected:
                if not self.risk.reserve():
                    continue
                expiration = expirations.get(signal["symbol"])
                if expiration is None:
                    try:
                        expiration, _ = self.client.select_one_minute_expiration(signal["symbol"])
                    except EvemexAPIError as exc:
                        self.risk.release_failed()
                        self.logger.write("operation_error", symbol=signal["symbol"], error=str(exc))
                        continue
                remaining = expiration - self.client.server_time()
                if not 45 <= remaining <= 90:
                    self.risk.release_failed()
                    self.logger.write(
                        "operation_skipped",
                        symbol=signal["symbol"],
                        reason="invalid_expiration_window",
                        remaining_seconds=round(remaining, 3),
                    )
                    continue
                future = executor.submit(
                    self.client.open_operation,
                    signal["symbol"],
                    self.amount,
                    signal["direction"],
                    expiration,
                    price_start_hint=self._latest_price(signal["symbol"]),
                    client_request_id=f"req_s16_{signal['symbol'].lower()}_{signal['candle_from']}",
                )
                future_map[future] = (signal, expiration)

            for future in as_completed(future_map):
                signal, expiration = future_map[future]
                try:
                    response = future.result()
                    operation_id = extract_operation_id(response)
                    if not operation_id:
                        raise EvemexAPIError("A abertura não devolveu o ID da operação")
                    self.pending[operation_id] = {
                        "symbol": signal["symbol"],
                        "direction": signal["direction"],
                        "amount": self.amount,
                        "expiration_at": expiration,
                    }
                    self.logger.write(
                        "operation_opened",
                        operation_id=operation_id,
                        symbol=signal["symbol"],
                        direction=signal["direction"],
                        amount=self.amount,
                        expiration_at=expiration,
                        probability=signal["probability"],
                    )
                    print(
                        f"[ORDEM] {signal['symbol']} {signal['direction']} | "
                        f"ID {operation_id} | P(WIN)={signal['probability']:.1%}"
                    )
                except Exception as exc:
                    self.risk.release_failed()
                    self.logger.write("operation_error", symbol=signal["symbol"], error=str(exc))
                    print(f"[ERRO] {signal['symbol']}: {exc}")

    def refresh_results(self) -> None:
        if not self.pending:
            return
        try:
            history = self.client.get_operation_history(limit=200)
        except EvemexAPIError as exc:
            self.logger.write("result_poll_error", error=str(exc))
            return
        by_id = {
            parsed.operation_id: parsed
            for parsed in (self.client.parse_operation(item) for item in history)
            if parsed.operation_id
        }
        for operation_id in list(self.pending):
            result = by_id.get(operation_id)
            if result is None or result.result is None:
                continue
            profit = float(result.profit or 0.0)
            self.risk.record_profit(profit)
            meta = self.pending.pop(operation_id)
            self.logger.write(
                "operation_result",
                operation_id=operation_id,
                symbol=meta["symbol"],
                result=result.result,
                profit=profit,
                session_pnl=self.risk.realized_pnl,
            )
            print(
                f"[RESULTADO] {meta['symbol']} {result.result} | "
                f"R$ {profit:.2f} | sessão R$ {self.risk.realized_pnl:.2f}"
            )

    def _load_history(self, symbol: str) -> list[Candle]:
        collected: dict[int, Candle] = {}
        cursor_to = int(self.client.server_time())
        for _ in range(10):
            page = self.client.get_candles(
                symbol,
                "1m",
                500,
                from_ts=cursor_to - 30 * 24 * 60 * 60,
                to_ts=cursor_to,
            )
            if not page:
                break
            for candle in page:
                if candle.to_ts <= int(self.client.server_time()):
                    collected[candle.from_ts] = candle
            if len(collected) >= 5000:
                break
            oldest = min(candle.from_ts for candle in page)
            if oldest >= cursor_to:
                break
            cursor_to = oldest - 1
        return sorted(collected.values(), key=lambda candle: candle.from_ts)[-5000:]

    def _prefetch_candidates(self, batch: dict[str, list[Candle]]) -> list[str]:
        candidates: list[str] = []
        current_minute = int(self.client.server_time() // 60) * 60
        for symbol in self.symbols:
            candles = sorted(batch.get(symbol, []), key=lambda candle: candle.from_ts)
            closed = [candle for candle in candles if candle.from_ts < current_minute]
            if not closed:
                continue
            merged = {candle.from_ts: candle for candle in self.history.get(symbol, [])}
            merged.update({candle.from_ts: candle for candle in closed})
            m5 = aggregate_m5(sorted(merged.values(), key=lambda candle: candle.from_ts)[-5000:])
            if detect_s16(m5) is not None:
                candidates.append(symbol)
        return candidates

    def _prefetch_expirations(self, symbols: list[str]) -> dict[str, int]:
        result: dict[str, int] = {}
        if not symbols:
            return result
        with ThreadPoolExecutor(max_workers=min(12, len(symbols))) as executor:
            future_map = {
                executor.submit(self.client.select_one_minute_expiration, symbol): symbol
                for symbol in symbols
            }
            for future in as_completed(future_map):
                symbol = future_map[future]
                try:
                    expiration, _ = future.result()
                    result[symbol] = expiration
                except EvemexAPIError as exc:
                    self.logger.write("expiration_error", symbol=symbol, error=str(exc))
        return result

    def _latest_price(self, symbol: str) -> float | None:
        candles = self.history.get(symbol, [])
        return candles[-1].close if candles else None

    def _sync_before_cycle(self) -> None:
        now = self.client.server_time()
        second = now % 60
        if second < 57.5:
            time.sleep(max(0.0, 57.5 - second))
        try:
            self.client.get_expirations(self.symbols[0])
        except EvemexAPIError as exc:
            self.logger.write("clock_sync_error", error=str(exc))

    def _wait_for_second(self, target: float) -> None:
        while True:
            second = self.client.server_time() % 60
            if second >= target:
                return
            time.sleep(min(0.05, max(0.005, target - second)))

    def _wait_until_next_cycle(self) -> None:
        second = self.client.server_time() % 60
        time.sleep(max(0.1, 60.0 - second + 0.1))


def positive_float(value: str) -> float:
    number = float(value.replace(",", "."))
    if number <= 0:
        raise argparse.ArgumentTypeError("o valor deve ser maior que zero")
    return number


def non_negative_float(value: str) -> float:
    number = float(value.replace(",", "."))
    if number < 0:
        raise argparse.ArgumentTypeError("o valor não pode ser negativo")
    return number


def non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("o valor não pode ser negativo")
    return number


def read_float(prompt: str, *, allow_zero: bool) -> float:
    while True:
        try:
            value = float(input(prompt).strip().replace(",", "."))
            if value > 0 or (allow_zero and value == 0):
                return value
        except ValueError:
            pass
        print("Informe um número válido.")


def read_int(prompt: str) -> int:
    while True:
        try:
            value = int(input(prompt).strip())
            if value >= 0:
                return value
        except ValueError:
            pass
        print("Informe um número inteiro maior ou igual a zero.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="analisa e simula sem enviar ordens")
    parser.add_argument("--once", action="store_true", help="executa apenas o próximo ciclo do segundo 59")
    parser.add_argument("--account", choices=("DEMO", "REAL"), help="tipo de conta")
    parser.add_argument("--amount", type=positive_float, help="valor de cada entrada")
    parser.add_argument("--stop-loss", type=non_negative_float, help="stop-loss da sessão; zero desativa")
    parser.add_argument("--max-operations", type=non_negative_int, help="máximo da sessão; zero desativa")
    parser.add_argument(
        "--confidence",
        type=positive_float,
        default=0.55,
        help="confiança mínima do modelo de IA para operar (padrão: 0.55)",
    )
    parser.add_argument(
        "--model",
        default=str(Path(__file__).parent / "signal_filter_s16.pkl"),
        help="caminho do modelo de IA treinado",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    email = os.environ.get("EVEMEX_EMAIL", "").strip() or input("E-mail Evemex: ").strip()
    password = os.environ.get("EVEMEX_PASSWORD") or getpass.getpass("Senha Evemex: ")
    account = args.account or (input("Conta [DEMO/REAL] (padrão DEMO): ").strip().upper() or "DEMO")
    if account not in {"DEMO", "REAL"}:
        print("Conta inválida. Use DEMO ou REAL.", file=sys.stderr)
        return 2
    amount = args.amount if args.amount is not None else read_float("Valor por entrada: R$ ", allow_zero=False)
    stop_loss = args.stop_loss if args.stop_loss is not None else read_float(
        "Stop-loss da sessão (0 desativa): R$ ", allow_zero=True
    )
    max_operations = args.max_operations if args.max_operations is not None else read_int(
        "Máximo de operações da sessão (0 desativa): "
    )

    if account == "REAL" and not args.dry_run:
        confirmation = input('Digite "CONFIRMAR REAL" para permitir ordens reais: ').strip()
        if confirmation != "CONFIRMAR REAL":
            print("Operação real cancelada.")
            return 2

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"Erro: Modelo de IA não encontrado em {model_path}", file=sys.stderr)
        return 2

    client = EvemexClient(email, password)
    try:
        client.connect()
        selected = client.select_account(account)
        if amount > selected.balance:
            print(
                f"Entrada de R$ {amount:.2f} excede o saldo de R$ {selected.balance:.2f}.",
                file=sys.stderr,
            )
            return 2
        bot = S16AIBot(
            client,
            model_path=str(model_path),
            amount=amount,
            stop_loss=stop_loss,
            max_operations=max_operations,
            confidence_threshold=args.confidence,
            dry_run=args.dry_run,
        )
        bot.initialize()
        bot.run(once=args.once)
        if bot._total_signals:
            print(
                f"\nResumo: {bot._approved_signals}/{bot._total_signals} sinais "
                f"({bot._approved_signals / bot._total_signals:.0%}) aprovados pela IA"
            )
        return 0
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.")
        return 130
    except EvemexAPIError as exc:
        print(f"Erro Evemex: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())