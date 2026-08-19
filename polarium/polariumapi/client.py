"""Cliente direto de autenticação, dados e operações da Polarium Broker."""

from __future__ import annotations

import http.cookiejar
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import TimeoutException

from app_runtime import data_path
from .exceptions import AuthenticationError, PolariumAPIError, RequestError
from .models import Account, AccountMode, Candle, Direction, OperationResult
from .secure_store import SessionStore
from .ws_transport import PolariumWebSocket, WS_URL

TRADEROOM_URL = "https://trade.polariumbroker.com/traderoom"
AUTH_URL = "https://api.trade.polariumbroker.com/v2/login"


class PolariumClient:
    """Cliente sem navegador para e-mail/senha; Selenium fica restrito ao Google."""

    def __init__(self, email: str = "", password: str = "", *,
                 base_url: str = "https://trade.polariumbroker.com", headless: bool = False,
                 timeout: float = 15.0, auth_mode: str = "EMAIL_PASSWORD") -> None:
        self.email = email.strip()
        self._password: str | None = password or None
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.timeout = timeout
        self.auth_mode = auth_mode.upper()
        self.driver: webdriver.Edge | None = None
        self._selected_account: Account | None = None
        self._accounts: list[Account] = []
        self._token: str | None = None
        self._ssid: str | None = None
        self._ws_url = WS_URL
        self._ws: PolariumWebSocket | None = None
        self._active_ids: dict[str, int] = {}
        self._opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    @property
    def session_file(self) -> Path:
        return data_path("polarium_session.dpapi")

    @property
    def profile_dir(self) -> Path:
        return data_path("polarium_edge_profile")

    @classmethod
    def get_saved_email(cls) -> str | None:
        payload = SessionStore(cls().session_file).load()
        email = str((payload or {}).get("email") or "").strip()
        return email or None

    @classmethod
    def from_saved_session(cls, base_url: str = "https://trade.polariumbroker.com", headless: bool = False) -> "PolariumClient":
        client = cls(base_url=base_url, headless=headless)
        payload = SessionStore(client.session_file).load()
        if not payload:
            raise AuthenticationError("Nenhuma sessão segura encontrada; faça login novamente.")
        client.email = str(payload.get("email") or "").strip()
        client._token = str(payload.get("token") or "").strip() or None
        client._ssid = str(payload.get("ssid") or "").strip() or None
        client._ws_url = str(payload.get("ws_url") or WS_URL)
        return client

    @classmethod
    def with_google(cls, base_url: str = "https://trade.polariumbroker.com") -> "PolariumClient":
        return cls(base_url=base_url, auth_mode="GOOGLE")

    def save_session(self) -> None:
        if self.email and self._ssid:
            SessionStore(self.session_file).save({
                "email": self.email, "token": self._token or "", "ssid": self._ssid,
                "ws_url": self._ws_url, "saved_at": int(time.time()),
            })

    def clear_saved_session(self) -> None:
        SessionStore(self.session_file).clear()
        data_path("polarium_session.json").unlink(missing_ok=True)

    def connect(self) -> bool:
        if self.auth_mode == "GOOGLE":
            return self._connect_google()
        if self._ssid:
            try:
                self._validate_websocket_session()
                return True
            except AuthenticationError:
                self._ssid = None
        return self._authenticate_email()

    def _authenticate_email(self) -> bool:
        if not self.email or not self._password:
            raise AuthenticationError("E-mail e senha são obrigatórios")
        body = json.dumps({"identifier": self.email, "password": self._password}).encode("utf-8")
        request = Request(AUTH_URL, data=body, method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "PolariumFull/1.0",
        })
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {}
            raise AuthenticationError(str(payload.get("message") or "Login recusado pela Polarium"),
                                      code=str(payload.get("code") or "login_failed"), data=payload) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RequestError(f"Falha ao acessar autenticação Polarium: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AuthenticationError("Resposta de autenticação Polarium inválida") from exc
        if not isinstance(payload, dict):
            raise AuthenticationError("Resposta de autenticação Polarium inválida")
        self._ssid = str(payload.get("ssid") or payload.get("session_id") or "").strip()
        if not self._ssid:
            self._ssid = next((c.value for c in self._cookie_jar() if c.name.lower() in {"ssid", "session"}), "")
        if not self._ssid:
            raise AuthenticationError("A Polarium não forneceu uma sessão utilizável")
        self._token = str(payload.get("token") or self._ssid)
        self._password = None
        self._validate_websocket_session()
        self.save_session()
        return True

    def _cookie_jar(self) -> http.cookiejar.CookieJar:
        for handler in self._opener.handlers:
            if isinstance(handler, HTTPCookieProcessor):
                return handler.cookiejar
        raise RuntimeError("Cookie jar não disponível")

    def _validate_websocket_session(self) -> None:
        ws = PolariumWebSocket(self._ssid or "", url=self._ws_url, timeout=self.timeout)
        try:
            ws.connect()
        finally:
            ws.close()

    def _connect_google(self) -> bool:
        driver = self._get_driver()
        print("🌐 Login Google: abrindo o Traderoom no navegador...")
        try:
            driver.get(TRADEROOM_URL)
        except TimeoutException:
            pass
        deadline = time.time() + 180
        while time.time() < deadline:
            if "/traderoom" in driver.current_url and "login" not in driver.current_url:
                self._ssid = next((str(c.get("value")) for c in driver.get_cookies()
                                   if str(c.get("name", "")).lower() in {"ssid", "session"}), "")
                if not self._ssid:
                    raise AuthenticationError("Login Google concluiu, mas nenhum SSID foi encontrado")
                self._token = self._ssid
                self._validate_websocket_session()
                self.save_session()
                return True
            time.sleep(1)
        raise AuthenticationError("Tempo esgotado aguardando o login Google")

    def _get_driver(self) -> webdriver.Edge:
        if self.driver is not None:
            try:
                _ = self.driver.title
                return self.driver
            except Exception:
                self.driver = None
        options = webdriver.EdgeOptions()
        options.page_load_strategy = "eager"
        options.add_argument("--disable-notifications")
        options.add_argument(f"--user-data-dir={self.profile_dir.resolve()}")
        if self.headless:
            options.add_argument("--headless=new")
        else:
            options.add_argument("--start-maximized")
        self.driver = webdriver.Edge(options=options)
        self.driver.set_page_load_timeout(30)
        return self.driver

    def hide_window(self) -> None:
        return

    def close(self) -> None:
        self._reset_ws()
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self._password = None

    def invalidate_session(self) -> None:
        self.clear_saved_session()
        self._ssid = None
        self._token = None
        self._accounts.clear()
        self._selected_account = None
        self._reset_ws()

    @property
    def selected_account(self) -> Account | None:
        return self._selected_account

    @property
    def session_id(self) -> str:
        if not self._ssid:
            raise AuthenticationError("Cliente Polarium não autenticado")
        return self._ssid

    @property
    def websocket_url(self) -> str:
        return self._ws_url

    def get_accounts(self, *, refresh: bool = True) -> list[Account]:
        if self._accounts and not refresh:
            return list(self._accounts)
        response = self._ensure_ws().request("internal-billing.get-balances",
                                             body={"types_ids": [1, 4, 2], "tournaments_statuses_ids": [3, 2]})
        raw = response.get("msg") if response.get("name") == "balances" else []
        accounts: list[Account] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            mode = "DEMO" if int(item.get("type") or 0) == 4 else "REAL"
            accounts.append(Account(account_id=str(item["id"]), trade_id=int(item["id"]), mode=mode, balance=float(item.get("amount") or 0.0)))  # type: ignore[arg-type]
        if not accounts:
            raise RequestError("A Polarium não retornou contas disponíveis")
        self._accounts = accounts
        return list(accounts)

    def select_account(self, mode: AccountMode | str) -> Account:
        normalized = str(mode).upper()
        if normalized not in {"DEMO", "REAL"}:
            raise ValueError("A conta deve ser DEMO ou REAL")
        for account in self.get_accounts():
            if account.mode == normalized:
                self._selected_account = account
                return account
        raise PolariumAPIError(f"Conta {normalized} não está disponível")

    def get_otc_assets(self, *, detailed: bool = True, instrument: str = "binary") -> list[dict[str, Any]]:
        response = self._ensure_ws().request("get-initialization-data", version="3.0", body={})
        message = response.get("msg") if response.get("name") == "initialization-data" else {}
        actives = message.get("binary", {}).get("actives", {}) if isinstance(message, dict) else {}
        assets: list[dict[str, Any]] = []
        for raw_id, info in actives.items() if isinstance(actives, dict) else []:
            if not isinstance(info, dict) or not info.get("name"):
                continue
            raw_name = str(info["name"]).lower().removeprefix("front.")
            symbol = re.sub(r"[^a-z0-9]", "", raw_name)
            self._active_ids[symbol] = int(raw_id)
            assets.append({"symbol": symbol, "name": info["name"], "instrument": instrument, "active_id": int(raw_id)})
        return sorted(assets, key=lambda item: str(item["symbol"]))

    def get_candles(self, symbol: str, timeframe: str = "1m", limit: int = 500, *, from_ts: int | None = None,
                    to_ts: int | None = None) -> list[Candle]:
        return []

    def select_expiration(self, symbol: str, timeframe_seconds: int) -> tuple[int, dict[str, Any]]:
        now = int(time.time())
        return now + (timeframe_seconds - (now % timeframe_seconds)), {}

    def select_one_minute_expiration(self, symbol: str) -> tuple[int, dict[str, Any]]:
        return self.select_expiration(symbol, 60)

    def open_operation(self, symbol: str, amount: float, direction: Direction | str, expiration_at: int, *,
                       instrument: str = "binary", expiration_tf_sec: int = 60, price_start_hint: float | None = None,
                       client_request_id: str | None = None) -> dict[str, Any]:
        if self._selected_account is None or self._selected_account.trade_id is None:
            raise PolariumAPIError("Selecione uma conta antes de abrir operações")
        if amount <= 0 or expiration_at <= int(time.time()):
            raise ValueError("Valor positivo e expiração futura são obrigatórios")
        active_id = self._resolve_active_id(symbol)
        response = self._ensure_ws().open_option(balance_id=self._selected_account.trade_id, active_id=active_id,
                                                 amount=amount, direction=str(direction), expiration_at=expiration_at,
                                                 request_id=client_request_id)
        message = response.get("msg") if isinstance(response, dict) else None
        operation_id = (message.get("id") or message.get("option_id")) if isinstance(message, dict) else None
        if not operation_id:
            raise RequestError("A Polarium respondeu sem ID de operação")
        return {"ok": True, "operation": {"id": str(operation_id), "status": "ACCEPTED", "raw": response}}

    def check_operation_result(self, operation_id: str) -> OperationResult:
        return OperationResult(operation_id=str(operation_id), status="UNKNOWN", result=None, profit=None,
                               raw={"reason": "Resultado deve ser recebido pelos eventos do WebSocket"})

    def _resolve_active_id(self, symbol: str) -> int:
        normalized = re.sub(r"[^a-z0-9]", "", str(symbol).lower())
        if normalized not in self._active_ids:
            self.get_otc_assets()
        if normalized not in self._active_ids:
            raise RequestError(f"Ativo não encontrado na Polarium: {symbol}")
        return self._active_ids[normalized]

    def _ensure_ws(self) -> PolariumWebSocket:
        if self._ws is None:
            if not self._ssid:
                raise AuthenticationError("Cliente Polarium não autenticado")
            self._ws = PolariumWebSocket(self._ssid, url=self._ws_url, timeout=self.timeout)
            self._ws.connect()
        return self._ws

    def _reset_ws(self) -> None:
        if self._ws is not None:
            self._ws.close()
        self._ws = None
