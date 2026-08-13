"""Robô de execução S13 com filtro de IA na Evemex.

Somente a S13 está habilitada para análise e entradas automáticas.
"""

from __future__ import annotations

import argparse
import getpass
import json
import joblib
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# Garante que o pacote evemexapi seja encontrado
sys.path.append(str(Path(__file__).parent))

from evemexapi import AuthenticationError, Candle, EvemexAPIError, EvemexClient
from evemexapi.strategy import candle_color
from feature_builders import latest_m1_features, latest_m5_features, latest_s01_features, latest_s13_features, latest_s5_m5_features
from s5_m5_rules import iter_s5_m5_events
from strategy_rules import detect_s01 as detect_s01_rule, detect_s13 as detect_s13_rule, detect_s16 as detect_s16_rule
from retrain_models import _archive

# --- CONFIGURAÇÕES VISUAIS ---
CLR_S01 = "\033[94m"  # Azul
CLR_S13 = "\033[93m"  # Amarelo
CLR_S16 = "\033[95m"  # Magenta
CLR_S5 = "\033[92m"   # Verde
CLR_WIN = "\033[92m"  # Verde
CLR_LOSS = "\033[91m" # Vermelho
CLR_CYAN = "\033[96m"
CLR_BOLD = "\033[1m"
CLR_RESET = "\033[0m"
# S01 permanece sem ordens até concluir a política de sombra publicada.
ENABLED_STRATEGIES = {"s01", "s13"}

# --- UTILITÁRIOS ---

class JsonlLogger:
    def __init__(self, directory: Path = Path("logs")) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"unified-trades-{datetime.now():%Y-%m-%d}.jsonl"
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

    def has_opened_s5(self, command_from_ts: int, touch_from_ts: int) -> bool:
        """Evita uma segunda entrada do mesmo toque após reiniciar o processo."""
        for path in self.path.parent.glob("unified-trades-*.jsonl"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        record = json.loads(line)
                        if (record.get("event") == "opened" and record.get("strategy") == "S5-M5"
                                and record.get("command_from_ts") == command_from_ts
                                and record.get("touch_from_ts") == touch_from_ts):
                            return True
            except (OSError, json.JSONDecodeError):
                continue
        return False

    def s01_shadow_records(self, campaign: str) -> list[dict[str, Any]]:
        """Resultados persistidos da validação sombra, inclusive após reinício."""
        records: list[dict[str, Any]] = []
        for path in self.path.parent.glob("unified-trades-*.jsonl"):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    record = json.loads(line)
                    if record.get("event") == "s01_shadow_result" and record.get("shadow_campaign") == campaign:
                        records.append(record)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
        return sorted(records, key=lambda record: (int(record.get("entry_from_ts", 0)), str(record.get("timestamp", ""))))

    def s01_shadow_results(self, campaign: str) -> list[int]:
        return [int(record.get("target", 0)) for record in self.s01_shadow_records(campaign)]

    def pending_s01_shadows(self, campaign: str) -> dict[tuple[str, int], dict[str, Any]]:
        pending: dict[tuple[str, int], dict[str, Any]] = {}
        for path in self.path.parent.glob("unified-trades-*.jsonl"):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    record = json.loads(line)
                    if record.get("shadow_campaign") != campaign:
                        continue
                    key = (str(record.get("symbol")), int(record.get("entry_from_ts", -1)))
                    if record.get("event") == "s01_shadow_opened" and key[1] >= 0:
                        pending[key] = {name: value for name, value in record.items() if name not in {"timestamp", "event"}}
                    elif record.get("event") == "s01_shadow_result":
                        pending.pop(key, None)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        return pending

    def shadow_records(self, event: str, campaign: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in self.path.parent.glob("unified-trades-*.jsonl"):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    record = json.loads(line)
                    if record.get("event") == event and record.get("shadow_campaign") == campaign:
                        records.append(record)
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda record: (int(record.get("entry_from_ts", 0)), str(record.get("timestamp", ""))))

    def pending_s13_candidate_shadows(self, campaign: str) -> dict[tuple[str, int], dict[str, Any]]:
        pending: dict[tuple[str, int], dict[str, Any]] = {}
        for path in self.path.parent.glob("unified-trades-*.jsonl"):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    record = json.loads(line)
                    if record.get("shadow_campaign") != campaign:
                        continue
                    key = (str(record.get("symbol")), int(record.get("entry_from_ts", -1)))
                    if record.get("event") == "s13_candidate_shadow_opened" and key[1] >= 0:
                        pending[key] = {name: value for name, value in record.items() if name not in {"timestamp", "event"}}
                    elif record.get("event") == "s13_candidate_shadow_result":
                        pending.pop(key, None)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        return pending

# --- DETECTORES DE ESTRATÉGIA ---

def is_doji(c: Candle) -> bool:
    return abs(c.close - c.open) < 1e-12

def detect_s01(candles: list[Candle]) -> str | None:
    return detect_s01_rule(candles)

def detect_s13(candles: list[Candle]) -> str | None:
    return detect_s13_rule(candles)

def aggregate_m5(candles: list[Candle]) -> list[Candle]:
    if not candles: return []
    df = pd.DataFrame([asdict(c) for c in candles])
    df["bucket"] = (df["from_ts"] // 300) * 300
    m5 = df.groupby("bucket", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).reset_index()
    symbol = candles[0].symbol
    timeframe = "M5"
    return [Candle(symbol=symbol, timeframe=timeframe, from_ts=int(r["bucket"]), to_ts=int(r["bucket"] + 300), open=float(r["open"]), high=float(r["high"]), low=float(r["low"]), close=float(r["close"])) for _, r in m5.iterrows()]

def detect_s16(m5: list[Candle]) -> str | None:
    return detect_s16_rule(m5)

# --- FEATURE BUILDERS ---

class FeatureBuilder:
    @staticmethod
    def build_m1(history: list[Candle]) -> dict[str, float] | None:
        return latest_m1_features(history)

    @staticmethod
    def build_s01(history: list[Candle], direction: str) -> dict[str, float] | None:
        return latest_s01_features(history, direction)

    @staticmethod
    def build_s13(history: list[Candle], direction: str) -> dict[str, float] | None:
        return latest_s13_features(history, direction)

    @staticmethod
    def build_m5(m5_history: list[Candle]) -> dict[str, float] | None:
        return latest_m5_features(m5_history)

    @staticmethod
    def build_s5(history: list[Candle], command: Any, touch: Candle, direction: str) -> dict[str, float] | None:
        return latest_s5_m5_features(history, command, touch, direction)

# --- BOT PRINCIPAL ---

class UnifiedAIBot:
    def __init__(self, client: EvemexClient, amount: float, *, apply_hour_filter: bool = False):
        self.client = client
        self.amount = amount
        self.apply_hour_filter = apply_hour_filter
        self.logger = JsonlLogger()
        self.policy = self._load_policy()
        
        # Modelos
        self.models = {}
        for s in sorted(ENABLED_STRATEGIES):
            path = Path(__file__).parent / f"signal_filter_{s}.pkl"
            if path.exists():
                data = joblib.load(path)
                self.models[s] = {"model": data["model"], "features": data["features"], "threshold": float(data.get("threshold", 0.65))}
                print(f"✅ Modelo {s.upper()} carregado (limiar {self.models[s]['threshold']:.0%}).")
            else:
                print(f"⚠️ Modelo {s.upper()} não encontrado em {path}")
        candidate_config = self.policy.get("candidates", {}).get("s13", {})
        self.s13_candidate: dict[str, Any] | None = None
        candidate_path = Path(__file__).parent / "signal_filter_s13_candidate.pkl"
        if "s13" in ENABLED_STRATEGIES and candidate_config.get("mode") == "shadow" and candidate_path.exists():
            data = joblib.load(candidate_path)
            self.s13_candidate = {"model": data["model"], "features": data["features"], "threshold": float(data["threshold"])}
            print(f"👁️ Candidata S13 carregada para sombra (limiar {self.s13_candidate['threshold']:.0%}).")

        self.symbols: list[str] = []
        self.history: dict[str, list[Candle]] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.used_levels_s16: dict[str, list[float]] = {}
        self.sent_s5_keys: set[tuple[int, int]] = set()
        campaign = str(self.policy.get("strategies", {}).get("s01", {}).get("shadow_campaign", ""))
        self.s01_shadow_pending = self.logger.pending_s01_shadows(campaign) if campaign else {}
        s13_campaign = str(candidate_config.get("shadow_campaign", ""))
        self.s13_shadow_pending = self.logger.pending_s13_candidate_shadows(s13_campaign) if s13_campaign else {}
        
        # Estatísticas de sessão
        self._last_heartbeat = 0.0
        self._cycles = 0
        self._wins = 0
        self._losses = 0
        self._realized_pnl = 0.0
        self._stop_reason: str | None = None

    @staticmethod
    def _load_policy() -> dict[str, Any]:
        path = Path(__file__).parent / "trading_policy.json"
        if not path.exists():
            print("⚠️ Política de operação não encontrada; sinais serão bloqueados. Execute retrain_models.py.")
            return {"strategies": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"⚠️ Política inválida; sinais serão bloqueados: {error}")
            return {"strategies": {}}

    def _policy_reason(self, strategy_key: str, now: float) -> str | None:
        config = self.policy.get("strategies", {}).get(strategy_key, {})
        is_s01_shadow = strategy_key == "s01" and config.get("mode") == "shadow"
        if not config.get("active", False) and not is_s01_shadow:
            return "estratégia desativada pela validação walk-forward"
        if self.apply_hour_filter:
            hour = datetime.fromtimestamp(now, tz=ZoneInfo("America/Sao_Paulo")).hour
            if hour not in config.get("allowed_hours_brasilia", []):
                return f"horário {hour:02d}:00 Brasília não liberado"
        return None

    def initialize(self):
        assets = self.client.get_otc_assets(detailed=True)
        self.symbols = sorted([str(a["symbol"]) for a in assets if str(a.get("symbol","")).endswith("_otc")])
        print(f"Carregando histórico de {len(self.symbols)} ativos (paralelo, timeout 20s)...")
        
        # Carregamento paralelo com timeout para não travar em ativo lento
        def _load(symbol: str) -> tuple[str, list[Candle]]:
            return symbol, self._load_history(symbol)
        
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_load, s): s for s in self.symbols}
            try:
                for fut in as_completed(futures, timeout=20):
                    symbol = futures[fut]
                    try:
                        sym, candles = fut.result()
                        self.history[sym] = candles
                    except Exception as e:
                        print(f"  ⚠️ Falha ao carregar {symbol}: {e}")
                        self.history[symbol] = []
                    self.used_levels_s16[symbol] = []
            except FuturesTimeout:
                print(f"  {CLR_LOSS}⚠️ Timeout ao carregar histórico. Continuando com dados parciais.{CLR_RESET}")
                for symbol in self.symbols:
                    if symbol not in self.history:
                        self.history[symbol] = []
                    self.used_levels_s16.setdefault(symbol, [])
        
        # Banner de status
        account = self.client.selected_account.mode if self.client.selected_account else "?"
        print("\n" + "=" * 58)
        print(f"  {CLR_BOLD}🟢 SISTEMA ONLINE{CLR_RESET}")
        print(f"  Conta: {account} | Entradas automáticas ativadas")
        print(f"  Ativos monitorados: {len(self.symbols)}")
        print(f"  Valor por entrada: R$ {self.amount:.2f}")
        print(f"  Filtro por horário Brasília: {'ATIVADO' if self.apply_hour_filter else 'DESATIVADO'}")
        print("=" * 58)
        print("  Aguardando sinais... (heartbeat a cada 5s)\n")

    def _force_reconnect(self) -> bool:
        """Força reconexão completa (limpa token expirado e refaz login)."""
        print(f"\n{CLR_LOSS}🔌 Token expirado/inválido! Forçando reconexão...{CLR_RESET}")
        for attempt in range(1, 6):
            try:
                self.client.connect()
                if self.client.connected:
                    print(f"{CLR_WIN}✅ Reconectado com sucesso!{CLR_RESET}\n")
                    return True
            except Exception as e:
                print(f"  ⚠️ Tentativa {attempt}/5 falhou: {e}")
            time.sleep(2 * attempt)
        print(f"{CLR_LOSS}❌ Não foi possível reconectar após 5 tentativas.{CLR_RESET}")
        return False

    def _ensure_connected(self) -> bool:
        """Verifica conexão e reconecta automaticamente se necessário."""
        if self.client.connected:
            return True
        print(f"\n{CLR_LOSS}🔌 Conexão perdida! Tentando reconectar...{CLR_RESET}")
        for attempt in range(1, 6):
            try:
                self.client.connect()
                if self.client.connected:
                    print(f"{CLR_WIN}✅ Reconectado com sucesso!{CLR_RESET}\n")
                    return True
            except Exception as e:
                print(f"  ⚠️ Tentativa {attempt}/5 falhou: {e}")
            time.sleep(2 * attempt)
        print(f"{CLR_LOSS}❌ Não foi possível reconectar após 5 tentativas.{CLR_RESET}")
        return False

    def _heartbeat(self, now: float) -> None:
        """Mostra status online em tempo real a cada 5 segundos."""
        if now - self._last_heartbeat < 5:
            return
        self._last_heartbeat = now
        status = f"{CLR_WIN}🟢 ONLINE{CLR_RESET}" if self.client.connected else f"{CLR_LOSS}🔴 OFFLINE{CLR_RESET}"
        pnl = self._realized_pnl
        pnl_clr = CLR_WIN if pnl >= 0 else CLR_LOSS
        print(f"  {status} | {datetime.fromtimestamp(now):%H:%M:%S} | "
              f"ciclos: {self._cycles} | W/L: {self._wins}/{self._losses} | "
              f"P&L: {pnl_clr}R$ {pnl:.2f}{CLR_RESET}")

    def run(self):
        last_min = -1
        last_s13_bucket = -1
        last_s01_bucket = -1
        while True:
            ciclo_inicio = time.monotonic()
            try:
                # 1. Garante conexão (reconecta se cair)
                if not self._ensure_connected():
                    self._stop_reason = "conexão indisponível"
                    break

                # 2. Atualiza resultados pendentes
                self.refresh_results()

                # 3. Sincroniza com o servidor
                now = self.client.server_time()

                # 4. Heartbeat visual (prova de vida em tempo real)
                self._heartbeat(now)

                # 5. Sincroniza o ciclo da S13 com o minuto da corretora.
                curr_min = int(now // 60)
                sec = now % 60

                # S01 confirmada: V3 fechada, ordem (ou sombra) somente no começo de V4.
                if (curr_min != last_s01_bucket and "s01" in ENABLED_STRATEGIES
                        and "s01" in self.models and self._is_s01_postclose_window(now, int(now // 60) * 60)):
                    batch = self.client.get_candles_batch(self.symbols, "1m", 61)
                    decision_now = self.client.server_time()
                    if self._is_s01_postclose_window(decision_now, int(now // 60) * 60):
                        self.resolve_s01_shadow(batch)
                        self.execute_signals(self.scan_s01_postclose(batch, decision_now))
                    else:
                        print("⚠️ S01 ignorada: dados chegaram após a janela de entrada da V4.")
                    last_s01_bucket = curr_min

                # Não executa nem consulta o ciclo S13 se ela não foi escolhida.
                if "s13" not in ENABLED_STRATEGIES:
                    time.sleep(0.1)
                    continue

                # 6. Deduplicação por minuto do ciclo S13.
                if curr_min == last_min:
                    if curr_min % 5 == 0 and sec < 1.0:
                        time.sleep(max(0.1, 1.0 - sec))
                    else:
                        time.sleep(0.1)
                    continue

                # 7. A S13 precisa do snapshot do segundo 59 da vela atual.
                if sec < 59.0:
                    wait = 59.0 - sec
                    print(f"  {CLR_CYAN}⏳ Próximo ciclo em {wait:.0f}s...{CLR_RESET}")
                    time.sleep(max(0.1, wait))
                    continue

                # 8. A S13 usa a terceira vela ainda em formação no segundo
                # 59 e envia a ordem antes da abertura da quarta vela.
                print(f"\n{CLR_BOLD}--- Ciclo {datetime.fromtimestamp(now):%H:%M:%S} ---{CLR_RESET}")
                t0 = time.monotonic()
                # Histórico suficiente para as features M1 e a vela ao vivo.
                batch = self.client.get_candles_batch(self.symbols, "1m", 31)
                latencia = time.monotonic() - t0
                if latencia > 10:
                    print(f"  {CLR_LOSS}⚠️ API lenta: batch demorou {latencia:.1f}s{CLR_RESET}")
                # Nunca decide com o ``now`` anterior ao batch. Se a API
                # respondeu depois da virada, V3 já fechou e seu snapshot de
                # segundo 59 não é mais confiável para entrar na V4.
                decision_now = self.client.server_time()
                if not self._is_s13_preclose_window(decision_now, int(now // 60) * 60):
                    print(f"  {CLR_LOSS}⚠️ S13 ignorada: batch chegou após o fechamento da vela.{CLR_RESET}")
                    continue
                s13_bucket = int(now // 60)
                if s13_bucket != last_s13_bucket:
                    self.resolve_s13_candidate_shadow(batch)
                    self.execute_signals(self.scan_s13_preclose(batch, decision_now))
                    last_s13_bucket = s13_bucket
                self._cycles += 1
                last_min = curr_min

            except KeyboardInterrupt:
                raise
            except AuthenticationError as e:
                # Token expirado (401) — força reconexão em vez de travar
                status = getattr(e, "status", None)
                if status == 401 or "401" in str(e):
                    print(f"{CLR_LOSS}⚠️ Sessão expirada (401): {e}{CLR_RESET}")
                    if not self._force_reconnect():
                        self._stop_reason = "não foi possível renovar a sessão"
                        break
                else:
                    print(f"{CLR_LOSS}⚠️ Erro de autenticação: {e}{CLR_RESET}")
                    time.sleep(1)
            except Exception as e:
                print(f"{CLR_LOSS}⚠️ Erro no ciclo: {e}{CLR_RESET}")
                time.sleep(1)

            # Watchdog: se o ciclo inteiro demorou mais que 45s, algo está errado
            duracao = time.monotonic() - ciclo_inicio
            if duracao > 45:
                print(f"{CLR_LOSS}⚠️ WATCHDOG: ciclo demorou {duracao:.0f}s (anormal). Verificando API...{CLR_RESET}")
                try:
                    t_ping = time.monotonic()
                    self.client.get_otc_assets(detailed=False)
                    print(f"  {CLR_WIN}✅ API respondeu em {time.monotonic()-t_ping:.1f}s{CLR_RESET}")
                except Exception as ping_err:
                    print(f"  {CLR_LOSS}❌ API sem resposta: {ping_err}{CLR_RESET}")
                    if not self._force_reconnect():
                        self._stop_reason = "API indisponível"
                        break

        print(f"\n🏁 Robô encerrado: {self._stop_reason or 'finalizado'}. P&L: R$ {self._realized_pnl:.2f}")

    def scan_strategies(
        self,
        batch: dict[str, list[Candle]],
        *,
        include_m1: bool = True,
        include_s13: bool = True,
        include_s16: bool = True,
    ) -> list[dict]:
        found = []
        now_ts = int(self.client.server_time() // 60) * 60
        
        for symbol, candles in batch.items():
            closed = sorted([c for c in candles if c.from_ts < now_ts], key=lambda x: x.from_ts)
            if not closed: continue
            
            # Atualiza histórico
            h = {c.from_ts: c for c in self.history.get(symbol, [])}
            h.update({c.from_ts: c for c in closed})
            self.history[symbol] = sorted(h.values(), key=lambda x: x.from_ts)[-1000:]
            
            # 1. S01 (M1)
            if include_m1 and "s01" in ENABLED_STRATEGIES and "s01" in self.models:
                dir_s01 = detect_s01(closed)
                if dir_s01:
                    self._process_signal(symbol, "S01", dir_s01, self.history[symbol], found)

            # 2. S13 (M1)
            if include_m1 and include_s13 and "s13" in ENABLED_STRATEGIES and "s13" in self.models:
                dir_s13 = detect_s13(closed)
                if dir_s13:
                    self._process_signal(symbol, "S13", dir_s13, self.history[symbol], found)

            # 3. S16 (M5)
            if include_s16 and "s16" in ENABLED_STRATEGIES and "s16" in self.models:
                m5 = aggregate_m5(self.history[symbol])
                m5_boundary = int(self.client.server_time() // 300) * 300
                m5 = [c for c in m5 if c.to_ts <= m5_boundary]
                dir_s16 = detect_s16(m5)
                if dir_s16:
                    # Regra de nível único S16
                    nivel = m5[-3].close
                    region = (1e-4 if nivel < 100 else 1e-2) * 2.0
                    if not any(abs(nivel - u) <= region for u in self.used_levels_s16[symbol]):
                        self._process_signal(symbol, "S16", dir_s16, m5, found)
                        self.used_levels_s16[symbol].append(nivel)

        return sorted(found, key=lambda x: -x["proba"])

    @staticmethod
    def _is_s01_postclose_window(server_time: float, entry_bucket: int) -> bool:
        """A S01 só pode entrar nos primeiros dois segundos da V4."""
        return int(server_time // 60) * 60 == entry_bucket and 0.0 <= server_time % 60 < 2.0

    def scan_s01_postclose(self, batch: dict[str, list[Candle]], now: float) -> list[dict]:
        """Confirma V3 fechada e cria a entrada S01 para a abertura de V4."""
        found: list[dict] = []
        entry_bucket = int(now // 60) * 60
        if not self._is_s01_postclose_window(now, entry_bucket):
            return found
        for symbol, candles in batch.items():
            closed = sorted((candle for candle in candles if candle.from_ts < entry_bucket), key=lambda candle: candle.from_ts)
            if len(closed) < 4:
                continue
            history = {candle.from_ts: candle for candle in self.history.get(symbol, [])}
            history.update({candle.from_ts: candle for candle in closed})
            current_history = sorted(history.values(), key=lambda candle: candle.from_ts)[-1000:]
            self.history[symbol] = current_history
            direction = detect_s01(current_history)
            if not direction:
                continue
            v0, v1, v2, v3 = current_history[-4:]
            details = {
                "signal_timing": "postclose_first_2_seconds", "signal_bucket": v3.from_ts,
                "entry_from_ts": entry_bucket, "server_time_observed": now,
                "v0": {"from_ts": v0.from_ts, "open": v0.open, "high": v0.high, "low": v0.low, "close": v0.close},
                "v1": {"from_ts": v1.from_ts, "open": v1.open, "high": v1.high, "low": v1.low, "close": v1.close},
                "v2": {"from_ts": v2.from_ts, "open": v2.open, "high": v2.high, "low": v2.low, "close": v2.close},
                "v3": {"from_ts": v3.from_ts, "open": v3.open, "high": v3.high, "low": v3.low, "close": v3.close},
            }
            self._process_signal(symbol, "S01", direction, current_history, found, details=details)
        return found

    def resolve_s01_shadow(self, batch: dict[str, list[Candle]]) -> None:
        """Fecha resultados sombra quando a vela de expiração V4 já está fechada."""
        for key, signal in list(self.s01_shadow_pending.items()):
            symbol, entry_from_ts = key
            candle = next((item for item in batch.get(symbol, []) if item.from_ts == entry_from_ts), None)
            if candle is None:
                continue
            target = int(candle.close > candle.open) if signal["direction"] in {"UP", "CALL"} else int(candle.close < candle.open)
            self.logger.write("s01_shadow_result", target=target, result_candle={"from_ts": candle.from_ts, "open": candle.open, "high": candle.high, "low": candle.low, "close": candle.close}, **signal)
            del self.s01_shadow_pending[key]
        self._complete_s01_shadow_if_ready()

    def _complete_s01_shadow_if_ready(self) -> None:
        config = self.policy.get("strategies", {}).get("s01", {})
        if config.get("mode") != "shadow":
            return
        campaign = str(config.get("shadow_campaign", ""))
        records = self.logger.s01_shadow_records(campaign)
        required = int(config.get("shadow_required_signals", 100))
        if len(records) < required:
            return
        records = records[:required]
        results = [int(record.get("target", 0)) for record in records]
        winrate = sum(results[:required]) / required
        config["shadow_signals"] = required
        config["shadow_winrate"] = winrate
        config["mode"] = "live" if winrate >= float(config.get("shadow_min_winrate", .60)) else "disabled"
        config["active"] = config["mode"] == "live"
        path = Path(__file__).parent / "trading_policy.json"
        path.write_text(json.dumps(self.policy, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_s01_shadow_report(records, campaign, winrate)
        self.logger.write("s01_shadow_completed", signals=required, winrate=winrate, mode=config["mode"])
        print(f"📊 S01 sombra concluída: {winrate:.1%} em {required} sinais; modo {config['mode']}.")

    @staticmethod
    def _write_s01_shadow_report(records: list[dict[str, Any]], campaign: str, winrate: float) -> None:
        """Gera o resumo verificável da campanha de 100 sinais S01."""
        frame = pd.DataFrame(records)
        frame["target"] = frame["target"].astype(int)
        frame["proba"] = frame["proba"].astype(float)
        frame["hour_brasilia"] = pd.to_datetime(frame["entry_from_ts"], unit="s", utc=True).dt.tz_convert(ZoneInfo("America/Sao_Paulo")).dt.hour
        lines = [
            "# Relatório da campanha sombra S01", "", f"Campanha: `{campaign}`", f"Sinais: {len(frame)}", f"Vitórias: {int(frame.target.sum())}",
            f"Derrotas: {int((1 - frame.target).sum())}", f"Taxa de acerto: {winrate:.2%}", f"Confiança média: {frame.proba.mean():.2%}", "",
            "## Por ativo", "", "| Ativo | Sinais | Vitórias | Derrotas | Acerto | Confiança média |", "|---|---:|---:|---:|---:|---:|",
        ]
        for symbol, row in frame.groupby("symbol").agg(sinais=("target", "size"), vitorias=("target", "sum"), acerto=("target", "mean"), confianca=("proba", "mean")).sort_index().iterrows():
            lines.append(f"| {symbol} | {int(row.sinais)} | {int(row.vitorias)} | {int(row.sinais - row.vitorias)} | {row.acerto:.2%} | {row.confianca:.2%} |")
        lines.extend(["", "## Por hora de Brasília", "", "| Hora | Sinais | Vitórias | Derrotas | Acerto | Confiança média |", "|---:|---:|---:|---:|---:|---:|"])
        for hour, row in frame.groupby("hour_brasilia").agg(sinais=("target", "size"), vitorias=("target", "sum"), acerto=("target", "mean"), confianca=("proba", "mean")).sort_index().iterrows():
            lines.append(f"| {int(hour):02d}:00 | {int(row.sinais)} | {int(row.vitorias)} | {int(row.sinais - row.vitorias)} | {row.acerto:.2%} | {row.confianca:.2%} |")
        (Path(__file__).parent / "S01_SHADOW_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def scan_s13_preclose(self, batch: dict[str, list[Candle]], now: float) -> list[dict]:
        """Confirma S13 no segundo 59 usando V3 em formação e abre a V4."""
        found: list[dict] = []
        current_bucket = int(now // 60) * 60
        if not self._is_s13_preclose_window(now, current_bucket):
            return found
        for symbol, candles in batch.items():
            ordered = sorted(candles, key=lambda candle: candle.from_ts)
            live = [candle for candle in ordered if candle.from_ts == current_bucket]
            closed = [candle for candle in ordered if candle.from_ts < current_bucket]
            if len(live) != 1 or len(closed) < 2 or "s13" not in self.models:
                continue
            pattern = [closed[-2], closed[-1], live[0]]
            direction = detect_s13(pattern)
            if not direction:
                continue
            history = {candle.from_ts: candle for candle in self.history.get(symbol, [])}
            history[live[0].from_ts] = live[0]
            current_history = sorted(history.values(), key=lambda candle: candle.from_ts)[-1000:]
            v1, v2, v3 = pattern
            level = v1.low if direction == "UP" else v1.high
            details = {
                "signal_timing": "preclose_second_59",
                "signal_bucket": current_bucket,
                "server_time_observed": now,
                "reference_level": level,
                "v1": {"from_ts": v1.from_ts, "open": v1.open, "high": v1.high, "low": v1.low, "close": v1.close},
                "v2": {"from_ts": v2.from_ts, "open": v2.open, "high": v2.high, "low": v2.low, "close": v2.close},
                "v3": {"from_ts": v3.from_ts, "open": v3.open, "high": v3.high, "low": v3.low, "close": v3.close},
                "sent_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            }
            self._process_signal(symbol, "S13", direction, current_history, found, details=details)
            self._process_s13_candidate(symbol, direction, current_history, details)
        return found

    def _process_s13_candidate(self, symbol: str, direction: str, candles: list[Candle], details: dict[str, Any]) -> None:
        """Avalia modelo candidato sem interferir na ordem da S13 publicada."""
        if getattr(self, "s13_candidate", None) is None:
            return
        config = self.policy.get("candidates", {}).get("s13", {})
        features = FeatureBuilder.build_s13(candles, direction)
        if not features:
            return
        missing = [name for name in self.s13_candidate["features"] if name not in features]
        if missing:
            raise RuntimeError(f"Candidata S13 incompatível: {', '.join(missing)}")
        probability = float(self.s13_candidate["model"].predict_proba(pd.DataFrame([{name: features[name] for name in self.s13_candidate["features"]}]))[0, 1])
        if probability < self.s13_candidate["threshold"]:
            print(f"{CLR_S13}[S13 candidata]{CLR_RESET} {symbol:15} | {direction:4} | P(WIN): {probability:.1%} | BLOQUEADO: confiança insuficiente")
            return
        signal = {"symbol": symbol, "strategy": "S13_CANDIDATE", "direction": direction, "proba": probability,
                  "execution_mode": "shadow", "shadow_campaign": config["shadow_campaign"],
                  "entry_from_ts": int(details["signal_bucket"]) + 60, **details}
        key = (symbol, signal["entry_from_ts"])
        if key not in self.s13_shadow_pending:
            self.s13_shadow_pending[key] = signal
            self.logger.write("s13_candidate_shadow_opened", **signal)
            print(f"{CLR_S13}[S13 candidata]{CLR_RESET} {symbol:15} | {direction:4} | P(WIN): {probability:.1%} | SOMBRA")

    def resolve_s13_candidate_shadow(self, batch: dict[str, list[Candle]]) -> None:
        for key, signal in list(self.s13_shadow_pending.items()):
            symbol, entry_from_ts = key
            candle = next((item for item in batch.get(symbol, []) if item.from_ts == entry_from_ts), None)
            if candle is None:
                continue
            target = int(candle.close > candle.open) if signal["direction"] == "UP" else int(candle.close < candle.open)
            self.logger.write("s13_candidate_shadow_result", target=target, result_candle={"from_ts": candle.from_ts, "open": candle.open, "high": candle.high, "low": candle.low, "close": candle.close}, **signal)
            del self.s13_shadow_pending[key]
        self._complete_s13_candidate_shadow()

    def _complete_s13_candidate_shadow(self) -> None:
        config = self.policy.get("candidates", {}).get("s13", {})
        if config.get("mode") != "shadow":
            return
        records = self.logger.shadow_records("s13_candidate_shadow_result", str(config.get("shadow_campaign", "")))
        required = int(config.get("shadow_required_signals", 100))
        if len(records) < required:
            return
        records = records[:required]
        winrate = sum(int(record.get("target", 0)) for record in records) / required
        config.update(shadow_signals=required, shadow_winrate=winrate)
        # A candidata só substitui a S13 se superar o desempenho OOS publicado.
        baseline = float(config.get("baseline_winrate", 1.0))
        config["mode"] = "approved" if winrate > baseline else "rejected"
        config["active"] = config["mode"] == "approved"
        if config["active"]:
            self._promote_s13_candidate(config)
        self.policy["generated_at"] = datetime.now().astimezone().isoformat()
        (Path(__file__).parent / "trading_policy.json").write_text(json.dumps(self.policy, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_s13_candidate_report(records, str(config.get("shadow_campaign", "")), winrate, baseline)
        self.logger.write("s13_candidate_shadow_completed", signals=required, winrate=winrate, baseline=baseline, mode=config["mode"])
        print(f"📊 S13 candidata concluída: {winrate:.1%}; referência {baseline:.1%}; modo {config['mode']}.")

    def _promote_s13_candidate(self, config: dict[str, Any]) -> None:
        """Troca o modelo ativo somente após a candidata superar a referência."""
        active_path = Path(__file__).parent / "signal_filter_s13.pkl"
        candidate_path = Path(__file__).parent / "signal_filter_s13_candidate.pkl"
        _archive(active_path)
        shutil.copy2(candidate_path, active_path)
        active_policy = self.policy.setdefault("strategies", {}).setdefault("s13", {})
        active_policy.update({"threshold": float(config["threshold"]), "candidate_promoted": True,
                              "candidate_campaign": config["shadow_campaign"], "candidate_winrate": config["shadow_winrate"]})

    @staticmethod
    def _write_s13_candidate_report(records: list[dict[str, Any]], campaign: str, winrate: float, baseline: float) -> None:
        frame = pd.DataFrame(records)
        frame["target"], frame["proba"] = frame["target"].astype(int), frame["proba"].astype(float)
        frame["hour_brasilia"] = pd.to_datetime(frame["entry_from_ts"], unit="s", utc=True).dt.tz_convert(ZoneInfo("America/Sao_Paulo")).dt.hour
        lines = ["# Relatório sombra — candidata S13", "", f"Campanha: `{campaign}`", f"Sinais: {len(frame)}", f"Vitórias: {int(frame.target.sum())}", f"Derrotas: {int((1-frame.target).sum())}", f"Acerto: {winrate:.2%}", f"Referência S13 atual: {baseline:.2%}", f"Confiança média: {frame.proba.mean():.2%}", "", "| Ativo | Sinais | Acerto | Confiança média |", "|---|---:|---:|---:|"]
        for symbol, row in frame.groupby("symbol").agg(sinais=("target", "size"), acerto=("target", "mean"), confianca=("proba", "mean")).sort_index().iterrows():
            lines.append(f"| {symbol} | {int(row.sinais)} | {row.acerto:.2%} | {row.confianca:.2%} |")
        lines.extend(["", "| Hora Brasília | Sinais | Acerto | Confiança média |", "|---:|---:|---:|---:|"])
        for hour, row in frame.groupby("hour_brasilia").agg(sinais=("target", "size"), acerto=("target", "mean"), confianca=("proba", "mean")).sort_index().iterrows():
            lines.append(f"| {int(hour):02d}:00 | {int(row.sinais)} | {row.acerto:.2%} | {row.confianca:.2%} |")
        (Path(__file__).parent / "S13_CANDIDATE_SHADOW_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _is_s13_preclose_window(server_time: float, candle_bucket: int) -> bool:
        """V3 só é válida durante seu segundo 59, antes da abertura da V4."""
        return int(server_time // 60) * 60 == candle_bucket and 59.0 <= server_time % 60 < 60.0

    def scan_s5_m5_preclose(self, batch: dict[str, list[Candle]], now: float) -> list[dict]:
        """Confirma o primeiro toque S5-M5 no segundo 59 e abre a próxima M1."""
        found: list[dict] = []
        current_bucket = int(now // 60) * 60
        for symbol, candles in batch.items():
            if "s5_m5" not in ENABLED_STRATEGIES or "s5_m5" not in self.models:
                continue
            ordered = sorted(candles, key=lambda candle: candle.from_ts)
            if not any(candle.from_ts == current_bucket for candle in ordered):
                continue
            frame = pd.DataFrame([asdict(candle) for candle in ordered])
            event = next(((command, touch, direction) for command, touch, direction in iter_s5_m5_events(frame)
                          if int(touch["from_ts"]) == current_bucket), None)
            if event is None:
                continue
            command, touch, direction = event
            key = (command.formed_at, int(touch["from_ts"]))
            seen = getattr(self, "sent_s5_keys", set())
            if key in seen or (hasattr(self.logger, "has_opened_s5") and self.logger.has_opened_s5(*key)):
                continue
            history = {candle.from_ts: candle for candle in self.history.get(symbol, [])}
            history.update({candle.from_ts: candle for candle in ordered})
            current_history = sorted(history.values(), key=lambda candle: candle.from_ts)[-1000:]
            touch_candle = next(candle for candle in ordered if candle.from_ts == current_bucket)
            features = FeatureBuilder.build_s5(current_history, command, touch_candle, direction)
            details = {
                "signal_timing": "preclose_second_59",
                "command_from_ts": command.formed_at,
                "command_available_at": command.available_at,
                "command_expires_at": command.expires_at,
                "command_color": command.color,
                "reference_level": command.level,
                "command_m5": {"open": command.open, "high": command.high, "low": command.low, "close": command.close},
                "touch_from_ts": int(touch["from_ts"]),
                "touch_m1": {name: float(touch[name]) for name in ("open", "high", "low", "close")},
                "command_age_m1": (int(touch["from_ts"]) - command.available_at) // 60,
                "sent_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            }
            if self._process_signal(symbol, "S5-M5", direction, current_history, found, details=details, features=features):
                seen.add(key)
                self.sent_s5_keys = seen
        return found

    def _process_signal(self, symbol: str, name: str, direction: str, candles: list[Candle], found_list: list, *, details: dict[str, Any] | None = None, features: dict[str, float] | None = None):
        s_key = "s5_m5" if name == "S5-M5" else name.lower()
        builder = FeatureBuilder.build_m5 if s_key == "s16" else FeatureBuilder.build_m1
        feats = features if features is not None else (FeatureBuilder.build_s01(candles, direction) if s_key == "s01" else builder(candles))
        if not feats: return False
        
        # Filtra features do modelo
        model_feats = self.models[s_key]["features"]
        missing_features = [feature for feature in model_feats if feature not in feats]
        if missing_features:
            raise RuntimeError(f"Modelo {name} incompatível; features ausentes: {', '.join(missing_features)}")
        x_dict = {feature: feats[feature] for feature in model_feats}
        x = pd.DataFrame([x_dict])
        proba = float(self.models[s_key]["model"].predict_proba(x)[0, 1])
        
        color = CLR_S01 if name == "S01" else (CLR_S13 if name == "S13" else (CLR_S16 if name == "S16" else CLR_S5))
        threshold = self.models[s_key]["threshold"]
        policy_reason = self._policy_reason(s_key, self.client.server_time()) if proba >= threshold else None
        shadow = s_key == "s01" and self.policy.get("strategies", {}).get("s01", {}).get("mode") == "shadow"
        status = "👁️ SOMBRA" if proba >= threshold and not policy_reason and shadow else ("✅ APROVADO" if proba >= threshold and not policy_reason else f"❌ BLOQUEADO: {policy_reason or 'confiança insuficiente'}")
        print(f"{color}[{name}]{CLR_RESET} {symbol:15} | {direction:4} | P(WIN): {proba:.1%} | {status}")
        
        if proba >= threshold and not policy_reason:
            signal = {"symbol": symbol, "strategy": name, "direction": direction, "proba": proba, "execution_mode": "shadow" if shadow else "live", **(details or {})}
            if shadow:
                signal["shadow_campaign"] = self.policy["strategies"]["s01"]["shadow_campaign"]
            found_list.append(signal)
            return True
        return False

    def execute_signals(self, signals: list[dict]):
        for s in signals:
            if s.get("execution_mode") == "shadow":
                key = (s["symbol"], int(s["entry_from_ts"]))
                if key not in self.s01_shadow_pending:
                    self.s01_shadow_pending[key] = s
                    self.logger.write("s01_shadow_opened", **s)
                continue
            if s.get("strategy") == "S01" and s.get("signal_timing") == "postclose_first_2_seconds":
                entry_bucket = s.get("entry_from_ts")
                server_now = self.client.server_time()
                if not isinstance(entry_bucket, int) or not self._is_s01_postclose_window(server_now, entry_bucket):
                    print(f"⚠️ S01 {s['symbol']} cancelada: janela de 2 segundos da V4 encerrada.")
                    self.logger.write("blocked_late_s01", server_time=server_now, **s)
                    continue
            if s.get("strategy") == "S13" and s.get("signal_timing") == "preclose_second_59":
                signal_bucket = s.get("signal_bucket")
                server_now = self.client.server_time()
                if not isinstance(signal_bucket, int) or not self._is_s13_preclose_window(server_now, signal_bucket):
                    print(f"⚠️ S13 {s['symbol']} cancelada: o fechamento da V3 já passou; nenhuma ordem tardia foi enviada.")
                    self.logger.write(
                        "blocked_late_s13", server_time=server_now, **s,
                    )
                    continue
            color = CLR_S01 if s["strategy"] == "S01" else (CLR_S13 if s["strategy"] == "S13" else (CLR_S16 if s["strategy"] == "S16" else CLR_S5))
            print(f"🚀 {color}ENTRANDO {s['strategy']}{CLR_RESET} em {s['symbol']} ({s['direction']})")
            try:
                expiration_tf_sec = 300 if s["strategy"] == "S16" else 60
                exp, _ = self.client.select_expiration(s["symbol"], expiration_tf_sec)
                res = self.client.open_operation(
                    s["symbol"], self.amount,
                    "UP" if s["direction"] == "CALL" or s["direction"] == "UP" else "DOWN",
                    exp, expiration_tf_sec=expiration_tf_sec,
                )
                op_id = str(res.get("id") or res.get("operationId") or res.get("data", {}).get("id") or res.get("result", {}).get("id") or "")
                if op_id:
                    self.pending[op_id] = s
                    self.logger.write(
                        "opened", op_id=op_id, expiration_at=exp,
                        expiration_tf_sec=expiration_tf_sec, **s,
                    )
                else:
                    print("⚠️ Ordem enviada, mas a corretora não retornou o identificador da operação.")
            except Exception as e:
                print(f"❌ Erro ao abrir: {e}")

    def refresh_results(self):
        if not self.pending: return
        try:
            hist = self.client.get_operation_history(limit=50)
            results = {str(self.client.parse_operation(i).operation_id): self.client.parse_operation(i) for i in hist}
            for op_id in list(self.pending):
                if op_id in results and results[op_id].result:
                    r = results[op_id]
                    meta = self.pending.pop(op_id)
                    profit = float(r.profit or 0)
                    self._realized_pnl = round(self._realized_pnl + profit, 2)
                    if profit > 0:
                        self._wins += 1
                    elif profit < 0:
                        self._losses += 1
                    
                    res_clr = CLR_WIN if profit > 0 else (CLR_LOSS if profit < 0 else CLR_RESET)
                    print(f"💰 {res_clr}RESULTADO {meta['strategy']}{CLR_RESET} {meta['symbol']}: {r.result} (R$ {profit:.2f}) | P&L: R$ {self._realized_pnl:.2f}")
                    self.logger.write("result", op_id=op_id, result=r.result, profit=profit, **meta)
        except Exception as e:
            print(f"⚠️ Erro ao consultar resultados: {e}")

    def _load_history(self, symbol: str) -> list[Candle]:
        try:
            page = self.client.get_candles(symbol, "1m", 500)
            return sorted(page, key=lambda x: x.from_ts)
        except: return []

# --- INTERFACE ---

def _ask_choice(prompt: str, options: dict[str, str], default: str = "1") -> str:
    """Pergunta com opções numeradas e explicação clara."""
    print(prompt)
    for key, desc in options.items():
        print(f"   {key}) {desc}")
    choice = input(f"   Opção [1-{len(options)}] (padrão {default}): ").strip() or default
    return choice


def _parse_strategy_choice(value: str) -> set[str] | None:
    """Converte a escolha simples do terminal nas estratégias instaladas."""
    normalized = value.replace(" ", "")
    choices = {"1": "s01", "2": "s13"}
    if normalized == "0":
        return set(choices.values())
    parts = normalized.split(",")
    if not parts or any(part not in choices for part in parts):
        return None
    return {choices[part] for part in parts}


def _ask_strategies(s01_mode: str = "shadow") -> set[str]:
    while True:
        print("\n🎯 Escolha as estratégias:")
        s01_status = "entradas automáticas" if s01_mode == "live" else "modo sombra"
        print(f"   1) S01 — Três Velas Reversão ({s01_status})")
        print("   2) S13 — Pavios de Rejeição (entradas automáticas)")
        print("   1,2) S01 e S13")
        print("   0) Todas (S01 e S13)")
        selected = _parse_strategy_choice(input("   Opção (padrão 2): ").strip() or "2")
        if selected:
            return selected
        print("⚠️ Opção inválida. Use 1, 2, 1,2 ou 0.")

def main():
    global ENABLED_STRATEGIES
    print("\n" + "=" * 58)
    print(f"  {CLR_BOLD}🤖 ROBÔ IA{CLR_RESET}")
    print("  Entradas automáticas com filtro de Inteligência Artificial")
    print("=" * 58 + "\n")

    policy_path = Path(__file__).parent / "trading_policy.json"
    try:
        menu_policy = json.loads(policy_path.read_text(encoding="utf-8"))
        s01_mode = str(menu_policy.get("strategies", {}).get("s01", {}).get("mode", "shadow"))
    except (OSError, json.JSONDecodeError):
        s01_mode = "shadow"
    ENABLED_STRATEGIES = _ask_strategies(s01_mode)
    print(f"✅ Estratégias selecionadas: {', '.join(sorted(item.upper() for item in ENABLED_STRATEGIES))}")
    
    auth_choice = _ask_choice(
        "🔐 Como deseja autenticar na Evemex?",
        {"1": "E-mail e senha", "2": "Google (abre uma janela dedicada do Edge)"},
    )
    if auth_choice == "2":
        client = EvemexClient.with_google()
    else:
        email = input("📧 E-mail Evemex: ").strip()
        password = getpass.getpass("🔑 Senha Evemex: ")
        client = EvemexClient(email, password)
    
    # Conta
    acc_choice = _ask_choice(
        "\n🏦 Selecione o tipo de conta:",
        {
            "1": "DEMO - Conta de testes (recomendado para começar)",
            "2": "REAL - Conta com dinheiro de verdade",
        },
    )
    acc_type = "REAL" if acc_choice == "2" else "DEMO"
    
    # Parâmetro obrigatório para enviar cada ordem
    amount = float(input("💵 Valor por operação (R$): ").replace(",", "."))
    hour_filter = _ask_choice(
        "\n🕒 Aplicar filtro automático por horário de Brasília?",
        {"1": "SIM - operar apenas horários validados", "2": "NÃO - ignorar somente o filtro de horário"},
    ) == "1"
    
    try:
        client.connect()
        if not client.connected:
            print(f"\n{CLR_LOSS}❌ Falha na conexão. Verifique e-mail/senha e tente novamente.{CLR_RESET}")
            return
        client.select_account(acc_type)
        bot = UnifiedAIBot(client, amount, apply_hour_filter=hour_filter)
        bot.initialize()
        bot.run()
    except KeyboardInterrupt:
        print(f"\n\n{CLR_CYAN}👋 Encerrado pelo usuário.{CLR_RESET}")
    except Exception as e:
        print(f"\n{CLR_LOSS}❌ Erro fatal: {e}{CLR_RESET}")
    finally:
        client.close()

if __name__ == "__main__":
    main()
