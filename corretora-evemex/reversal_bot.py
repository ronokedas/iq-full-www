"""Robô M1: três velas iguais e entrada contrária na quarta vela."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from evemexapi import Candle, EvemexAPIError, EvemexClient, PatternStats, Signal
from evemexapi.strategy import LivePatternDetector, calculate_pattern_stats, candle_color


class JsonlLogger:
    def __init__(self, directory: Path = Path("logs")) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"trades-{datetime.now():%Y-%m-%d}.jsonl"
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


class ReversalBot:
    def __init__(
        self,
        client: EvemexClient,
        *,
        amount: float,
        stop_loss: float,
        max_operations: int,
        dry_run: bool = False,
        logger: JsonlLogger | None = None,
    ) -> None:
        self.client = client
        self.amount = round(float(amount), 2)
        self.dry_run = dry_run
        self.logger = logger or JsonlLogger()
        self.risk = RiskManager(stop_loss=stop_loss, max_operations=max_operations)
        self.detector = LivePatternDetector()
        self.symbols: list[str] = []
        self.history: dict[str, list[Candle]] = {}
        self.stats: dict[str, dict[str, PatternStats]] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self._last_cycle_minute: int | None = None

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
            calculated = calculate_pattern_stats(candles, symbol=symbol)
            self.stats[symbol] = calculated  # type: ignore[assignment]
            self.detector.seed(symbol, candles)
            green = calculated["GREEN"]
            red = calculated["RED"]
            print(
                f"[{index:02d}/{len(self.symbols):02d}] {symbol}: "
                f"3V {green.wins}/{green.sample_size} | 3R {red.wins}/{red.sample_size}"
            )
            self.logger.write(
                "statistics",
                symbol=symbol,
                green=asdict(green),
                red=asdict(red),
                candles=len(candles),
            )

    def run(self, *, once: bool = False) -> None:
        print(
            f"Robô ativo | conta={self.client.selected_account.mode if self.client.selected_account else '?'} "
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
            pre_candles = self.client.get_candles_batch(self.symbols, "1m", 4)
            pre_candidates = self._prefetch_candidates(pre_candles)
            expirations = self._prefetch_expirations(pre_candidates)

            self._wait_for_second(59.0)
            final_candles = self.client.get_candles_batch(self.symbols, "1m", 4)
            signals = self.build_signals(final_candles)
            self.execute_signals(signals, expirations)
            self._last_cycle_minute = int(self.client.server_time() // 60)

            if once:
                print("Ciclo único concluído.")
                return
            self._wait_until_next_cycle()

        reason = "limite de operações" if self.risk.max_operations and self.risk.operations >= self.risk.max_operations else "stop-loss"
        print(f"Robô encerrado por {reason}. P&L: R$ {self.risk.realized_pnl:.2f}")

    def build_signals(self, batch: dict[str, list[Candle]]) -> list[Signal]:
        signals: list[Signal] = []
        current_minute = int(self.client.server_time() // 60) * 60
        for symbol in self.symbols:
            candles = sorted(batch.get(symbol, []), key=lambda item: item.from_ts)
            closed = [candle for candle in candles if candle.from_ts < current_minute]
            current = next((candle for candle in reversed(candles) if candle.from_ts == current_minute), None)
            if closed:
                self._append_closed(symbol, closed)
                self.detector.observe_closed(symbol, closed[-1])
            if current is None or len(closed) < 2:
                continue
            recent = closed[-2:] + [current]
            signal = self.detector.evaluate(symbol, recent, self.stats[symbol])
            if signal is not None:
                signals.append(signal)
                self.logger.write("signal", **asdict(signal), provisional_close=current.close)
        return sorted(signals, key=lambda signal: (-signal.accuracy, signal.symbol))

    def execute_signals(
        self,
        signals: list[Signal],
        expirations: dict[str, int],
    ) -> None:
        signals = sorted(signals, key=lambda signal: (-signal.accuracy, signal.symbol))
        allowed = self.risk.allowed(len(signals))
        selected = signals[:allowed]
        for skipped in signals[allowed:]:
            self.detector.unblock(skipped.symbol)
            self.logger.write("signal_skipped", symbol=skipped.symbol, reason="session_limit")
        if not selected:
            return

        if self.dry_run:
            for signal in selected:
                if not self.risk.reserve():
                    self.detector.unblock(signal.symbol)
                    continue
                expiration = expirations.get(signal.symbol)
                self.logger.write(
                    "dry_run_operation",
                    symbol=signal.symbol,
                    direction=signal.direction,
                    amount=self.amount,
                    expiration_at=expiration,
                    accuracy=signal.accuracy,
                )
                print(
                    f"[DRY-RUN] {signal.symbol} {signal.direction} | "
                    f"{signal.wins}/{signal.sample_size} ({signal.accuracy:.0%})"
                )
            return

        with ThreadPoolExecutor(max_workers=min(12, len(selected))) as executor:
            future_map = {}
            for signal in selected:
                if not self.risk.reserve():
                    self.detector.unblock(signal.symbol)
                    continue
                expiration = expirations.get(signal.symbol)
                if expiration is None:
                    try:
                        expiration, _ = self.client.select_one_minute_expiration(signal.symbol)
                    except EvemexAPIError as exc:
                        self.risk.release_failed()
                        self.detector.unblock(signal.symbol)
                        self.logger.write("operation_error", symbol=signal.symbol, error=str(exc))
                        continue
                remaining = expiration - self.client.server_time()
                if not 45 <= remaining <= 90:
                    self.risk.release_failed()
                    self.detector.unblock(signal.symbol)
                    self.logger.write(
                        "operation_skipped",
                        symbol=signal.symbol,
                        reason="invalid_expiration_window",
                        remaining_seconds=round(remaining, 3),
                    )
                    continue
                future = executor.submit(
                    self.client.open_operation,
                    signal.symbol,
                    self.amount,
                    signal.direction,
                    expiration,
                    price_start_hint=self._latest_price(signal.symbol),
                    client_request_id=f"req_bot_{signal.symbol.lower()}_{signal.candle_from}",
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
                        "symbol": signal.symbol,
                        "direction": signal.direction,
                        "amount": self.amount,
                        "expiration_at": expiration,
                    }
                    self.logger.write(
                        "operation_opened",
                        operation_id=operation_id,
                        symbol=signal.symbol,
                        direction=signal.direction,
                        amount=self.amount,
                        expiration_at=expiration,
                        accuracy=signal.accuracy,
                    )
                    print(f"[ORDEM] {signal.symbol} {signal.direction} | ID {operation_id}")
                except Exception as exc:
                    self.risk.release_failed()
                    self.detector.unblock(signal.symbol)
                    self.logger.write("operation_error", symbol=signal.symbol, error=str(exc))
                    print(f"[ERRO] {signal.symbol}: {exc}")

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
            ordered = sorted(collected.values(), key=lambda candle: candle.from_ts)
            stats = calculate_pattern_stats(ordered, symbol=symbol)
            if stats["GREEN"].sample_size >= 20 and stats["RED"].sample_size >= 20:
                return ordered[-5000:]
            oldest = min(candle.from_ts for candle in page)
            if oldest >= cursor_to:
                break
            cursor_to = oldest - 1
        return sorted(collected.values(), key=lambda candle: candle.from_ts)[-5000:]

    def _append_closed(self, symbol: str, candles: list[Candle]) -> None:
        merged = {candle.from_ts: candle for candle in self.history.get(symbol, [])}
        merged.update({candle.from_ts: candle for candle in candles})
        ordered = sorted(merged.values(), key=lambda candle: candle.from_ts)[-5000:]
        self.history[symbol] = ordered
        self.stats[symbol] = calculate_pattern_stats(ordered, symbol=symbol)  # type: ignore[assignment]

    def _prefetch_candidates(self, batch: dict[str, list[Candle]]) -> list[str]:
        candidates: list[str] = []
        current_minute = int(self.client.server_time() // 60) * 60
        for symbol in self.symbols:
            if self.detector.is_blocked(symbol):
                continue
            candles = sorted(batch.get(symbol, []), key=lambda candle: candle.from_ts)
            closed = [candle for candle in candles if candle.from_ts < current_minute]
            if len(closed) < 2:
                continue
            colors = [candle_color(candle) for candle in closed[-2:]]
            if colors[0] in {"GREEN", "RED"} and colors[0] == colors[1]:
                stat = self.stats[symbol].get(colors[0])
                if stat is not None and stat.qualifies:
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
        bot = ReversalBot(
            client,
            amount=amount,
            stop_loss=stop_loss,
            max_operations=max_operations,
            dry_run=args.dry_run,
        )
        bot.initialize()
        bot.run(once=args.once)
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
