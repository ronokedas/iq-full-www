"""
Polarium Full - Robo de Trading com IA (V3 - WebSocket Real)
Usa WebSocket para capturar candles reais e a PolariumClient para enviar ordens.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import websockets

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app_runtime import APP_NAME, APP_USER_MODEL_ID, APP_VERSION, data_path
from polariumapi import AuthenticationError, PolariumClient
from licensing import LicenseClient

import pandas as pd

from strategy_smc_m2 import STRATEGY_ID as SMC_M2_ID, STRATEGY_LABEL as SMC_M2_LABEL, detect_latest as detect_smc_m2
from strategy_sniper_m1 import STRATEGY_ID as SNIPER_M1_ID, STRATEGY_LABEL as SNIPER_M1_LABEL, detect_latest as detect_sniper_m1
from strategy_smc_m1 import STRATEGY_ID as SMC_M1_ID, STRATEGY_LABEL as SMC_M1_LABEL, detect_latest as detect_smc_m1
from ai_confidence_engine import is_approved_by_ai

logging.basicConfig(level=logging.WARNING, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger("PolariumIA")

CLR_GREEN = "\033[92m"
CLR_RED = "\033[91m"
CLR_BLUE = "\033[94m"
CLR_BOLD = "\033[1m"
CLR_RESET = "\033[0m"

MAX_ORDERS_PER_MINUTE = 3
CANDLES_BUFFER = 50  # Velas de historico por par
ACTIVE_PAIRS: list[str] = []  # Preenchido pela config do usuario


def _normalize_symbol(value: str) -> str:
    return "".join(char for char in str(value).lower().removeprefix("front.") if char.isalnum())


# ============================================================
# CLASSE CANDLE SIMPLES PARA COMPATIBILIDADE COM AS ESTRATEGIAS
# ============================================================
class Candle:
    def __init__(self, from_ts, open_, high, low, close):
        self.from_ts = from_ts
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.to_ts = from_ts + 60
        self.volume = 0.0
        self.tick_count = 0
        self.timeframe = "1m"
        self.symbol = ""


# ============================================================
# GERENCIADOR DE CANDLES POR PAR
# ============================================================
class PairManager:
    def __init__(self, symbol: str, active_id: int):
        self.symbol = symbol
        self.active_id = active_id
        self.buffer: deque[dict] = deque(maxlen=CANDLES_BUFFER)
        self.current_candle: dict | None = None

    def update_candle(self, raw: dict) -> bool:
        """Atualiza a vela viva e informa se uma vela anterior acabou de fechar."""
        ts = int(raw.get("from", 0))
        if self.current_candle and self.current_candle.get("from") == ts:
            self.current_candle = raw
            return False
        else:
            if self.current_candle:
                self.buffer.append(self.current_candle)
            self.current_candle = raw
            return bool(self.buffer)

    def get_closed_candles(self) -> list[Candle]:
        candles = []
        for c in self.buffer:
            candles.append(Candle(
                from_ts=int(c.get("from", 0)),
                open_=float(c.get("open", 0)),
                high=float(c.get("high", 0)),
                low=float(c.get("low", 0)),
                close=float(c.get("close", 0)),
            ))
        return candles


# ============================================================
# BOT PRINCIPAL
# ============================================================
class PolariumIABot:
    def __init__(self, ws_url: str, ssid: str, polarium_client: PolariumClient,
                 amount: float, pairs: list[str], strategies: set[str],
                 use_ai_filter: bool = True):
        self.ws_url = ws_url
        self.ssid = ssid
        self.client = polarium_client
        self.amount = amount
        self.pairs = pairs
        self.strategies = strategies
        self.use_ai_filter = use_ai_filter

        self.ws = None
        self._req_counter = 0
        self._subscriptions: dict[str, Any] = {}
        self._pair_managers: dict[str, PairManager] = {}

        self._wins = self._losses = 0
        self._pnl = 0.0
        self._in_operation = False
        self._last_entry_minute = -1
        self._signal_tasks: dict[str, asyncio.Task] = {}
        self._operation_events: dict[str, asyncio.Event] = {}
        self._operation_results: dict[str, dict[str, Any]] = {}
        self._stream_error: Exception | None = None
        self._candle_events = 0
        self._closed_candles = 0

    def _next_id(self) -> str:
        self._req_counter += 1
        return str(self._req_counter)

    async def _send(self, payload: dict) -> None:
        await self.ws.send(json.dumps(payload))

    async def _listen_loop(self) -> None:
        try:
            async for raw_msg in self.ws:
                try:
                    data = json.loads(raw_msg)
                    name = data.get("name", "")

                    if name == "candle-generated":
                        candle_data = data.get("msg", {})
                        if isinstance(candle_data, list):
                            candle_data = candle_data[0] if candle_data else {}
                        active_id = candle_data.get("active_id") if isinstance(candle_data, dict) else None
                        try:
                            active_id = int(active_id)
                        except (TypeError, ValueError):
                            active_id = None
                        # Encontrar o par pelo active_id
                        for pm in self._pair_managers.values():
                            if pm.active_id == active_id:
                                self._candle_events += 1
                                candle_closed = pm.update_candle(candle_data)
                                if candle_closed:
                                    self._closed_candles += 1
                                task = self._signal_tasks.get(pm.symbol)
                                if candle_closed and (task is None or task.done()):
                                    self._signal_tasks[pm.symbol] = asyncio.create_task(self._check_signals(pm))
                                break

                    elif name == "initialization-data":
                        msg = data.get("msg", {})
                        # Mapear actives disponíveis para descobrir IDs
                        actives = msg.get("binary", {}).get("actives", {})
                        for active_id_str, info in actives.items():
                            sym = info.get("name", "").lower().removeprefix("front.")
                            sym = sym.replace("/", "").replace("_", "").replace("-", "").replace(" ", "").upper()
                            for pair in self.pairs:
                                norm = pair.upper().replace("_OTC", "").replace("-OTC", "").replace("_", "").replace("-", "").replace(" ", "")
                                if norm == sym:
                                    if pair not in self._pair_managers:
                                        self._pair_managers[pair] = PairManager(pair, int(active_id_str))
                                        break

                    elif name in {"option", "option-closed", "position-changed", "order-changed", "binary-option", "result"}:
                        self._record_operation_event(data)

                except Exception as error:
                    log.exception("Mensagem WebSocket inválida: %s", error)
        except Exception as error:
            self._stream_error = error
            log.exception("Listener WebSocket encerrado: %s", error)

    def _record_operation_event(self, data: dict[str, Any]) -> None:
        raw = data.get("msg", data)
        if not isinstance(raw, dict):
            return
        candidates = [raw, raw.get("result"), raw.get("operation"), raw.get("option"), raw.get("position")]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            operation_id = item.get("id") or item.get("option_id") or item.get("optionId") or item.get("order_id")
            result = str(item.get("result") or item.get("status") or item.get("state") or "").upper()
            if not operation_id or result not in {"WIN", "LOSS", "DRAW", "WON", "LOST", "CLOSED", "EXPIRED"}:
                continue
            normalized = "WIN" if result == "WON" else "LOSS" if result == "LOST" else result
            self._operation_results[str(operation_id)] = {
                "result": normalized,
                "profit": item.get("profit", item.get("profit_amount")),
                "raw": data,
            }
            event = self._operation_events.get(str(operation_id))
            if event:
                event.set()

    async def _check_signals(self, pm: PairManager) -> None:
        if self._in_operation:
            return

        now = time.time()
        entry_bucket = int(now // 60) * 60
        if self._last_entry_minute == entry_bucket:
            return  # Ja operou nesse minuto

        candles = pm.get_closed_candles()
        if len(candles) < 10:
            return

        signals = []
        try:
            if SMC_M2_ID in self.strategies:
                signals.extend(detect_smc_m2(candles, pm.symbol, entry_bucket))
            if SNIPER_M1_ID in self.strategies:
                signals.extend(detect_sniper_m1(candles, pm.symbol, entry_bucket))
            if SMC_M1_ID in self.strategies:
                signals.extend(detect_smc_m1(candles, pm.symbol, entry_bucket))
        except Exception:
            return

        for signal in signals:
            if self.use_ai_filter:
                ok, conf = is_approved_by_ai(signal["strategy_id"], pm.symbol)
                if not ok:
                    if conf > 0:
                        print(f"{CLR_RED}[IA REJEITOU]{CLR_RESET} {pm.symbol} | {signal['direction']} | Confianca: {conf:.0f}%")
                    continue
                print(f"{CLR_GREEN}[SINAL IA {conf:.0f}%]{CLR_RESET} {pm.symbol} | {signal['direction']} | {signal['strategy']}")
            else:
                print(f"{CLR_GREEN}[SINAL]{CLR_RESET} {pm.symbol} | {signal['direction']} | {signal['strategy']}")

            await self._place_order(signal)
            self._last_entry_minute = entry_bucket
            break

    async def _place_order(self, signal: dict) -> None:
        self._in_operation = True
        direction = signal["direction"]
        symbol = signal["symbol"]
        exp_sec = int(signal.get("expiration_tf_sec", 60))
        entry = int(signal["entry_from_ts"])
        expiration = entry + exp_sec

        print(f"{CLR_BLUE}[ORDEM]{CLR_RESET} {direction} {symbol} (Exp: {exp_sec}s) -> Polarium...")
        try:
            resp = self.client.open_operation(
                symbol, self.amount, direction, expiration,
                expiration_tf_sec=exp_sec,
                client_request_id=f"ia:{symbol}:{entry}:{direction}"
            )
            op_id = str(resp.get("operation", {}).get("id", ""))
            if op_id:
                print(f"  OK Ordem aceita ID: {op_id}")
            event = asyncio.Event()
            self._operation_events[op_id] = event
            try:
                await asyncio.wait_for(event.wait(), timeout=exp_sec + 15)
            except asyncio.TimeoutError:
                pass
            result_data = self._operation_results.pop(op_id, None)
            if result_data and result_data.get("result") == "WIN":
                self._wins += 1
                profit = float(result_data.get("profit") or 0)
                self._pnl += profit
                print(f"{CLR_GREEN}[WIN]{CLR_RESET} +R${profit:.2f} | W:{self._wins} L:{self._losses} PnL:R${self._pnl:+.2f}")
            elif result_data and result_data.get("result") == "LOSS":
                self._losses += 1
                profit = float(result_data.get("profit") or -self.amount)
                self._pnl += profit
                print(f"{CLR_RED}[LOSS]{CLR_RESET} {profit:+.2f} | W:{self._wins} L:{self._losses} PnL:R${self._pnl:+.2f}")
            else:
                print(f"⚠️ Resultado não confirmado pela corretora para {op_id}; não contabilizado.")
            self._operation_events.pop(op_id, None)
        except Exception as e:
            print(f"  ERRO ao enviar ordem: {e}")
        finally:
            await asyncio.sleep(5)
            self._in_operation = False

    async def start(self) -> None:
        print(f"\n{'=' * 70}")
        print(f"  {CLR_BOLD}POLARIUM FULL IA v{APP_VERSION} ONLINE{CLR_RESET}")
        ai_status = "LIGADO (>60% Win Rate)" if self.use_ai_filter else "DESLIGADO (todos os sinais)"
        strat_names = []
        if SMC_M2_ID in self.strategies: strat_names.append("SMC M2")
        if SNIPER_M1_ID in self.strategies: strat_names.append("Sniper M1")
        if SMC_M1_ID in self.strategies: strat_names.append("SMC M1")
        print(f"  Estrategias: {' | '.join(strat_names)} | Filtro IA: {ai_status}")
        print(f"  Pares monitorados: {len(self.pairs)}")
        print(f"{'=' * 70}\n")

        print(f"Conectando ao WebSocket da Polarium...")
        self.ws = await websockets.connect(self.ws_url, max_size=20_000_000)

        # Autenticar
        await self._send({
            "name": "authenticate",
            "msg": {"ssid": self.ssid, "protocol": 3, "session_id": "", "client_session_id": ""}
        })
        try:
            auth_response = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=15))
        except Exception as error:
            raise AuthenticationError(f"Falha ao autenticar WebSocket: {error}") from error
        if auth_response.get("name") != "authenticated" or auth_response.get("msg") is not True:
            raise AuthenticationError("Sessão rejeitada pelo WebSocket da Polarium")

        # O catálogo do cliente já está autenticado e evita depender de uma
        # condição de corrida entre initialization-data e o listener.
        assets = self.client.get_otc_assets()
        for asset in assets:
            asset_symbol = _normalize_symbol(str(asset.get("symbol", "")))
            for pair in self.pairs:
                if asset_symbol == _normalize_symbol(pair):
                    self._pair_managers.setdefault(pair, PairManager(pair, int(asset["active_id"])))
                    break

        # Iniciar listener em background
        asyncio.create_task(self._listen_loop())
        await asyncio.sleep(1)

        # Subscribir nas velas dos pares configurados pelo active_id
        # Primeiro mapear os ativos
        await self._send({
            "name": "sendMessage",
            "request_id": self._next_id(),
            "msg": {"name": "get-initialization-data", "version": "3.0", "body": {}}
        })
        await asyncio.sleep(2)

        # Subscribir em candles-generated para cada par (por active_id)
        subscribed = 0
        for pair in self.pairs:
            pm = self._pair_managers.get(pair)
            if pm:
                await self._send({
                    "name": "subscribeMessage",
                    "request_id": self._next_id(),
                    "msg": {
                        "name": "candle-generated",
                        "params": {"routingFilters": {"active_id": pm.active_id, "size": 60}}
                    }
                })
                subscribed += 1
                print(f"  Inscrito em {pair} (ID: {pm.active_id})")

        if subscribed == 0:
            raise RuntimeError("Nenhum dos pares selecionados foi encontrado no Traderoom")

        print(f"\nMonitorando {subscribed} pares em tempo real. Ctrl+C para parar.\n")

        # Loop principal - manter vivo
        while True:
            if self._stream_error is not None:
                print(f"⚠️ WebSocket interrompido: {self._stream_error}. Reconectando...")
                await self._reconnect_stream()
            await asyncio.sleep(60)
            hour = datetime.now()
            total = self._wins + self._losses
            wr = (self._wins / total * 100) if total > 0 else 0
            print(f"[{hour:%H:%M}] Vivo | Eventos:{self._candle_events} | Fechadas:{self._closed_candles} | W:{self._wins} L:{self._losses} ({wr:.0f}%) | PnL: R${self._pnl:+.2f}")

    async def _reconnect_stream(self) -> None:
        self._stream_error = None
        try:
            if self.ws is not None:
                await self.ws.close()
            self.ws = await websockets.connect(self.ws_url, max_size=20_000_000)
            await self._send({"name": "authenticate", "msg": {
                "ssid": self.ssid, "protocol": 3, "session_id": "", "client_session_id": ""
            }})
            response = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=15))
            if response.get("name") != "authenticated" or response.get("msg") is not True:
                raise AuthenticationError("Sessão rejeitada durante reconexão")
            asyncio.create_task(self._listen_loop())
            await self._send({"name": "sendMessage", "request_id": self._next_id(),
                              "msg": {"name": "get-initialization-data", "version": "3.0", "body": {}}})
            await asyncio.sleep(2)
            for pair, manager in self._pair_managers.items():
                await self._send({"name": "subscribeMessage", "request_id": self._next_id(), "msg": {
                    "name": "candle-generated", "params": {"routingFilters": {"active_id": manager.active_id, "size": 60}}
                }})
        except Exception as error:
            self._stream_error = error
            await asyncio.sleep(5)


# ============================================================
# CONFIGURACAO E MENUS
# ============================================================

def configure_windows_identity() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(f"{APP_NAME} IA {APP_VERSION}")
    except Exception:
        pass


def _ask_choice(prompt: str, options: dict[str, str]) -> str:
    while True:
        print(prompt)
        for key, label in options.items():
            print(f"   {key}) {label}")
        value = input("Opcao: ").strip()
        if value in options:
            return value
        print("Opcao invalida.")


def _ask_amount() -> float:
    while True:
        try:
            value = float(input("Valor por operacao (R$): ").strip().replace(",", "."))
            if value > 0:
                return value
        except ValueError:
            pass
        print("Informe um valor maior que zero.")


def _ask_strategies() -> set[str]:
    while True:
        print("\nEstrategias para operar:")
        print(f"   0) TODAS AS 3 (Recomendado)")
        print(f"   1) {SMC_M2_LABEL}")
        print(f"   2) {SNIPER_M1_LABEL}")
        print(f"   3) {SMC_M1_LABEL}")
        value = input("Opcao (0 ou combinacao, ex: 1,2): ").strip()
        if value == "0":
            return {SMC_M2_ID, SNIPER_M1_ID, SMC_M1_ID}
        selected = set(value.split(","))
        if selected <= {"1", "2", "3"}:
            res = set()
            if "1" in selected: res.add(SMC_M2_ID)
            if "2" in selected: res.add(SNIPER_M1_ID)
            if "3" in selected: res.add(SMC_M1_ID)
            if res:
                return res
        print("Escolha 0, 1, 2, 3 ou combinacao como 1,2.")


def _ask_ai_filter() -> bool:
    print("\nFiltro de IA (Win Rate minimo):")
    print("   1) COM IA - So opera pares com >60% Win Rate [Recomendado]")
    print("   2) SEM IA - Opera todos os sinais (mais entradas)")
    value = input("Opcao: ").strip()
    return value != "2"


def _ask_pairs(strategies: set[str], use_ai: bool) -> list[str]:
    """Retorna os melhores pares para as estrategias selecionadas."""
    from ai_confidence_engine import CONFIDENCE_DATABASE, MINIMUM_CONFIDENCE_THRESHOLD

    best_pairs: set[str] = set()
    for strat_id in strategies:
        if strat_id in CONFIDENCE_DATABASE:
            for sym, wr in CONFIDENCE_DATABASE[strat_id].items():
                if not use_ai or wr >= MINIMUM_CONFIDENCE_THRESHOLD:
                    # Converter para formato Polarium: EURCAD-OTC -> eurcad_otc
                    polarium_sym = sym.lower().replace("-", "_")
                    best_pairs.add(polarium_sym)

    best_pairs_list = sorted(best_pairs)
    print(f"\nPares selecionados com base nas estrategias ({len(best_pairs_list)}):")
    for p in best_pairs_list:
        print(f"  - {p}")
    return best_pairs_list


def package_smoke_test() -> int:
    try:
        from strategy_smc_m2 import STRATEGY_ID
        from strategy_sniper_m1 import STRATEGY_ID as s2
        print(f"PACKAGE_SMOKE_OK app={APP_NAME} version={APP_VERSION}")
        return 0
    except Exception as e:
        print(f"PACKAGE_SMOKE_FAILED: {e}")
        return 5


def main() -> None:
    configure_windows_identity()

    print("=" * 70)
    print(f"  {CLR_BOLD}{APP_NAME.upper()} IA v{APP_VERSION}{CLR_RESET}")
    print("=" * 70)

    client: PolariumClient | None = None
    saved_email = PolariumClient.get_saved_email()
    if saved_email:
        use_saved = _ask_choice(
            f"\nSessao salva ({saved_email}). Reutilizar?",
            {"1": "SIM", "2": "NAO"}
        )
        if use_saved == "1":
            try:
                client = PolariumClient.from_saved_session()
                client.connect()
            except Exception as error:
                print(f"Sessão salva inválida: {error}")
                client = None

    if client is None:
        auth = _ask_choice("\nAutenticacao:", {"1": "E-mail e senha", "2": "Google"})
        if auth == "2":
            client = PolariumClient.with_google()
        else:
            email = input("E-mail Polarium: ").strip()
            password = getpass.getpass("Senha: ")
            client = PolariumClient(email=email, password=password)
        while True:
            try:
                client.connect()
                client.save_session()
                break
            except AuthenticationError as e:
                print(f"Falha: {e}")
                if _ask_choice("Tentar novamente?", {"1": "SIM", "2": "NAO"}) != "1":
                    return

    account_choice = _ask_choice("\nConta:", {"1": "DEMO", "2": "REAL"})
    account_mode = "REAL" if account_choice == "2" else "DEMO"
    if account_mode == "REAL":
        confirmation = input("Digite REAL para confirmar operações em dinheiro real: ").strip().upper()
        if confirmation != "REAL":
            print("Operação real cancelada.")
            client.close()
            return
    client.select_account(account_mode)
    amount = _ask_amount()

    strategies = _ask_strategies()
    use_ai = _ask_ai_filter()

    # A sessão direta fornece o SSID sem depender de cookies do navegador.
    ws_url, ssid = client.websocket_url, client.session_id

    # Definir pares a monitorar
    pairs = _ask_pairs(strategies, use_ai)
    if not pairs:
        print("Nenhum par disponivel. Verifique as configuracoes.")
        return

    bot = PolariumIABot(
        ws_url=ws_url,
        ssid=ssid,
        polarium_client=client,
        amount=amount,
        pairs=pairs,
        strategies=strategies,
        use_ai_filter=use_ai
    )

    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        print("\nBot encerrado.")


if __name__ == "__main__":
    if "--package-smoke-test" in sys.argv:
        raise SystemExit(package_smoke_test())
    main()
