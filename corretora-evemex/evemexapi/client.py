"""Cliente síncrono e isolado para os endpoints de trading da Evemex."""

from __future__ import annotations

import http.cookiejar
import json
import socket
import threading
import time
import uuid
from collections.abc import Callable, Generator, Iterable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .exceptions import AuthenticationError, EvemexAPIError, RequestError
from .google_auth import GoogleAuthenticator, GoogleSession
from .models import Account, AccountMode, Candle, Direction, OperationResult

Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None, float], Any]


class EvemexClient:
    """Cliente de trading da API usada pela aplicação web da Evemex.

    A API não é oficialmente documentada. Todos os detalhes de protocolo ficam
    concentrados nesta classe para que mudanças futuras não contaminem as
    estratégias.
    """

    def __init__(
        self,
        email: str = "",
        password: str = "",
        *,
        base_url: str = "https://api.evemex.com",
        timeout: float = 15.0,
        transport: Transport | None = None,
    ) -> None:
        self.email = email.strip()
        self._password: str | None = password
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._token: str | None = None
        self._google_authenticator: GoogleAuthenticator | None = None
        self._accounts: list[Account] = []
        self._selected_account: Account | None = None
        self._server_offset = 0.0
        self._offset_lock = threading.Lock()
        cookie_jar = http.cookiejar.CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(cookie_jar))

    @property
    def connected(self) -> bool:
        return bool(self._token or any(True for _ in self._cookie_jar()))

    @classmethod
    def with_google(cls, *, base_url: str = "https://api.evemex.com", timeout: float = 15.0,
                    authenticator: GoogleAuthenticator | None = None, transport: Transport | None = None) -> "EvemexClient":
        client = cls(base_url=base_url, timeout=timeout, transport=transport)
        client._google_authenticator = authenticator or GoogleAuthenticator()
        return client

    def _cookie_jar(self) -> http.cookiejar.CookieJar:
        for handler in self._opener.handlers:
            if isinstance(handler, HTTPCookieProcessor):
                return handler.cookiejar
        raise RuntimeError("Cookie jar não disponível")

    def _set_google_session(self, session: GoogleSession) -> None:
        self._token = session.token
        jar = self._cookie_jar()
        jar.clear()
        for raw in session.cookies:
            domain = str(raw.get("domain") or ".evemex.com")
            path = str(raw.get("path") or "/")
            cookie = http.cookiejar.Cookie(0, str(raw["name"]), str(raw["value"]), None, False, domain,
                domain.startswith("."), domain.startswith("."), path, True, bool(raw.get("secure", True)),
                int(raw["expiry"]) if raw.get("expiry") else None, False, None, None, {"HttpOnly": raw.get("httpOnly")} if raw.get("httpOnly") else {}, False)
            jar.set_cookie(cookie)

    def validate_session(self) -> bool:
        try:
            response = self._request("GET", "/me")
            return isinstance(response, dict)
        except (AuthenticationError, EvemexAPIError, RequestError):
            return False

    @property
    def selected_account(self) -> Account | None:
        return self._selected_account

    def connect(self) -> bool:
        if self._google_authenticator is not None:
            self._token = None
            self._cookie_jar().clear()
            restored = self._google_authenticator.restore()
            if restored:
                self._set_google_session(restored)
                if self.validate_session():
                    return True
                self._google_authenticator.forget()
            session = self._google_authenticator.interactive_login()
            self._set_google_session(session)
            if not self.validate_session():
                raise AuthenticationError("Login Google concluído, mas a sessão Evemex não pôde ser validada")
            self._google_authenticator.store.save(session)
            return True
        if not self.email or not self._password:
            raise AuthenticationError("E-mail e senha são obrigatórios")
        response = self._request(
            "POST",
            "/auth/login",
            body={"email": self.email, "password": self._password},
            authenticated=False,
        )
        if not isinstance(response, dict):
            raise AuthenticationError("Resposta de autenticação inválida")
        if response.get("twoFactorRequired"):
            raise AuthenticationError(
                "A conta exige 2FA; o login automatizado com código ainda não foi informado",
                code="two_factor_required",
                data={"challengeId": response.get("challengeId")},
            )
        token = response.get("token")
        if response.get("ok") is False or not isinstance(token, str) or not token:
            raise AuthenticationError(
                str(response.get("message") or "Login recusado pela Evemex"),
                code=str(response.get("code") or "login_failed"),
            )
        self._token = token
        # Mantém a senha somente durante a vida deste cliente para permitir
        # renovar uma sessão expirada. close() ainda a descarta definitivamente.
        return True

    def close(self) -> None:
        """Descarta credenciais da sessão local sem invalidar outras sessões."""
        self._token = None
        self._cookie_jar().clear()
        self._password = None
        self._accounts.clear()
        self._selected_account = None

    def get_accounts(self, *, refresh: bool = True) -> list[Account]:
        if self._accounts and not refresh:
            return list(self._accounts)
        payload = self._request("GET", "/me")
        raw_accounts = payload.get("accounts", []) if isinstance(payload, dict) else []
        accounts: list[Account] = []
        for raw in raw_accounts:
            if isinstance(raw, dict):
                try:
                    accounts.append(Account.from_api(raw))
                except (TypeError, ValueError):
                    continue
        self._accounts = accounts
        return list(accounts)

    def select_account(self, mode: AccountMode | str) -> Account:
        normalized = str(mode).upper()
        if normalized not in {"DEMO", "REAL"}:
            raise ValueError("A conta deve ser DEMO ou REAL")
        for account in self.get_accounts(refresh=True):
            if account.mode == normalized:
                self._selected_account = account
                return account
        raise EvemexAPIError(f"Conta {normalized} não encontrada")

    def get_otc_assets(self, *, detailed: bool = True) -> list[dict[str, Any]]:
        catalog = self._request("GET", "/otc/assets")
        active_symbols = {
            str(symbol)
            for symbol in (catalog.get("assets", []) if isinstance(catalog, dict) else [])
        }
        if not detailed:
            return [{"symbol": symbol} for symbol in sorted(active_symbols)]
        details = self._request("GET", "/otc/assets/info")
        raw_assets = details.get("assets", []) if isinstance(details, dict) else []
        result = [
            dict(asset)
            for asset in raw_assets
            if isinstance(asset, dict) and str(asset.get("symbol")) in active_symbols
        ]
        return sorted(result, key=lambda item: str(item.get("symbol", "")))

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 500,
        *,
        from_ts: int | None = None,
        to_ts: int | None = None,
    ) -> list[Candle]:
        limit = max(1, min(int(limit), 500))
        if from_ts is None and to_ts is None:
            path = "/otc/candles/latest"
            query = {"symbol": symbol, "timeframe": timeframe, "limit": limit}
        else:
            if from_ts is None or to_ts is None:
                raise ValueError("from_ts e to_ts devem ser informados juntos")
            path = "/otc/candles/range"
            query = {
                "symbol": symbol,
                "timeframe": timeframe,
                "from": int(from_ts),
                "to": int(to_ts),
                "limit": limit,
            }
        payload = self._request("GET", path, query=query)
        raw_candles = payload.get("candles", []) if isinstance(payload, dict) else []
        candles = [
            Candle.from_api(raw, symbol=symbol, timeframe=timeframe)
            for raw in raw_candles
            if isinstance(raw, dict)
        ]
        return sorted({c.from_ts: c for c in candles}.values(), key=lambda c: c.from_ts)

    def get_candles_batch(
        self,
        symbols: Iterable[str],
        timeframe: str = "1m",
        limit: int = 4,
    ) -> dict[str, list[Candle]]:
        clean = list(dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip()))
        if not clean:
            return {}
        payload = self._request(
            "GET",
            "/otc/candles/latest/batch",
            query={"symbols": ",".join(clean), "timeframe": timeframe, "limit": limit},
        )
        raw_results = payload.get("results", {}) if isinstance(payload, dict) else {}
        normalized: dict[str, list[Candle]] = {}
        if isinstance(raw_results, dict):
            for symbol, value in raw_results.items():
                raw_candles = value.get("candles", []) if isinstance(value, dict) else value
                if not isinstance(raw_candles, list):
                    continue
                normalized[str(symbol)] = sorted(
                    (
                        Candle.from_api(item, symbol=str(symbol), timeframe=timeframe)
                        for item in raw_candles
                        if isinstance(item, dict)
                    ),
                    key=lambda candle: candle.from_ts,
                )
        return normalized

    def stream_candles(
        self,
        symbol: str,
        timeframe: str = "1m",
        *,
        stop_event: threading.Event | None = None,
        reconnect_attempts: int = 3,
        poll_interval: float = 1.0,
    ) -> Generator[Candle, None, None]:
        """Entrega candles via SSE e cai para polling caso o stream falhe."""
        stop = stop_event or threading.Event()
        attempts = 0
        while not stop.is_set() and attempts < max(0, reconnect_attempts):
            attempts += 1
            try:
                yielded = False
                for candle in self._stream_sse(symbol, timeframe, stop):
                    yielded = True
                    attempts = 0
                    yield candle
                if yielded:
                    continue
            except (EvemexAPIError, OSError, ValueError):
                if stop.wait(min(2**attempts, 8)):
                    return

        last_signature: tuple[int, float] | None = None
        while not stop.is_set():
            try:
                candles = self.get_candles(symbol, timeframe, 2)
                if candles:
                    candle = candles[-1]
                    signature = (candle.from_ts, candle.close)
                    if signature != last_signature:
                        last_signature = signature
                        yield candle
            except EvemexAPIError:
                pass
            stop.wait(max(0.2, poll_interval))

    def get_expirations(self, symbol: str) -> dict[str, Any]:
        demo = self._selected_account is not None and self._selected_account.mode == "DEMO"
        payload = self._request(
            "GET",
            "/ops/expirations",
            query={"symbol": symbol, "demo": "1" if demo else None},
        )
        if not isinstance(payload, dict):
            raise RequestError("Resposta inválida ao consultar vencimentos")
        server_ms = payload.get("serverTimeMs")
        if isinstance(server_ms, (int, float)):
            with self._offset_lock:
                self._server_offset = float(server_ms) / 1000.0 - time.time()
        return payload

    def server_time(self) -> float:
        with self._offset_lock:
            return time.time() + self._server_offset

    def select_expiration(self, symbol: str, timeframe_seconds: int) -> tuple[int, dict[str, Any]]:
        """Retorna o vencimento disponível para o timeframe solicitado."""
        if timeframe_seconds <= 0 or timeframe_seconds % 60:
            raise ValueError("O timeframe deve ser um múltiplo positivo de 60 segundos")
        minutes = timeframe_seconds // 60
        accepted_labels = {f"{minutes}M", f"M{minutes}"}
        payload = self.get_expirations(symbol)
        for slot in payload.get("slots", []):
            if isinstance(slot, dict) and str(slot.get("label", "")).upper() in accepted_labels:
                expiration = slot.get("expirationAtSec", slot.get("expiration_at"))
                if isinstance(expiration, (int, float)):
                    return int(expiration), payload
        raise EvemexAPIError(f"Vencimento de {minutes} minutos indisponível para {symbol}")

    def select_one_minute_expiration(self, symbol: str) -> tuple[int, dict[str, Any]]:
        """Compatibilidade para consumidores existentes do cliente."""
        return self.select_expiration(symbol, 60)

    def open_operation(
        self,
        symbol: str,
        amount: float,
        direction: Direction | str,
        expiration_at: int,
        *,
        expiration_tf_sec: int = 60,
        price_start_hint: float | None = None,
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        if self._selected_account is None:
            raise EvemexAPIError("Selecione uma conta antes de abrir operações")
        normalized_direction = str(direction).upper()
        if normalized_direction not in {"UP", "DOWN"}:
            raise ValueError("A direção deve ser UP ou DOWN")
        if amount <= 0:
            raise ValueError("O valor da operação deve ser maior que zero")
        if expiration_tf_sec <= 0 or expiration_tf_sec % 60:
            raise ValueError("O timeframe de expiração deve ser um múltiplo positivo de 60 segundos")
        request_id = client_request_id or f"req_{uuid.uuid4().hex}"
        body: dict[str, Any] = {
            "symbol": symbol,
            "timeframe": f"{expiration_tf_sec // 60}m",
            "amount": round(float(amount), 2),
            "trend": normalized_direction,
            "demo": self._selected_account.mode == "DEMO",
            "bonus": False,
            "expirationTfSec": expiration_tf_sec,
            "expirationMultiplier": 1,
            "expirationAtSec": int(expiration_at),
            "clientRequestId": request_id,
            "tabId": f"bot-{symbol.lower()}",
        }
        if price_start_hint is not None:
            body["priceStartHint"] = float(price_start_hint)
        payload = self._request("POST", "/ops/open_operation", body=body, timeout=30.0)
        if not isinstance(payload, dict):
            raise RequestError("Resposta inválida ao abrir operação")
        return payload

    def get_open_operations(self, *, limit: int = 200) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            "/ops/operations/open",
            query={"limit": limit, "accountKind": self._account_kind()},
        )
        return self._operation_items(payload)

    def get_operation_history(self, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            "/ops/operations/history",
            query={"limit": limit, "offset": offset, "accountKind": self._account_kind()},
        )
        return self._operation_items(payload)

    def wait_result(
        self,
        operation_id: str,
        *,
        timeout: float = 180.0,
        poll_interval: float = 1.0,
    ) -> OperationResult:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for item in self.get_operation_history(limit=200):
                parsed = self.parse_operation(item)
                if parsed.operation_id == str(operation_id):
                    return parsed
            time.sleep(max(0.2, poll_interval))
        raise RequestError(f"Tempo esgotado aguardando a operação {operation_id}", code="result_timeout")

    @staticmethod
    def parse_operation(item: dict[str, Any]) -> OperationResult:
        operation_id = item.get("operationId", item.get("operation_id", item.get("id", "")))
        profit = item.get("profit")
        return OperationResult(
            operation_id=str(operation_id),
            status=str(item.get("status", "closed")),
            result=str(item["result"]) if item.get("result") is not None else None,
            profit=float(profit) if isinstance(profit, (int, float)) else None,
            raw=dict(item),
        )

    def _account_kind(self) -> str:
        if self._selected_account is None:
            raise EvemexAPIError("Selecione uma conta antes de consultar operações")
        return self._selected_account.mode.lower()

    @staticmethod
    def _operation_items(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        items = payload.get("items", payload.get("operations", []))
        return [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def _stream_sse(
        self,
        symbol: str,
        timeframe: str,
        stop: threading.Event,
    ) -> Generator[Candle, None, None]:
        url = self._url(
            "/otc/stream",
            {"symbol": symbol, "timeframe": timeframe, "channels": "candles"},
        )
        headers = self._headers()
        headers["Accept"] = "text/event-stream"
        request = Request(url, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=max(30.0, self.timeout)) as response:
                data_lines: list[str] = []
                for raw_line in response:
                    if stop.is_set():
                        return
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif not line and data_lines:
                        payload = json.loads("\n".join(data_lines))
                        data_lines.clear()
                        raw = payload.get("candle", payload.get("data", payload))
                        if isinstance(raw, dict) and all(key in raw for key in ("open", "high", "low", "close")):
                            yield Candle.from_api(raw, symbol=symbol, timeframe=timeframe)
        except (HTTPError, URLError, socket.timeout) as exc:
            raise RequestError("Falha no stream de candles") from exc

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "evemex-trading-bot/0.1"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            clean = {key: value for key, value in query.items() if value is not None}
            if clean:
                url = f"{url}?{urlencode(clean)}"
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
        timeout: float | None = None,
    ) -> Any:
        if authenticated and not self.connected:
            raise AuthenticationError("Cliente não autenticado")
        url = self._url(path, query)
        headers = self._headers()
        payload_bytes: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
        effective_timeout = float(timeout or self.timeout)
        if self._transport is not None:
            return self._transport(method.upper(), url, headers, body, effective_timeout)
        request = Request(url, data=payload_bytes, headers=headers, method=method.upper())
        try:
            with self._opener.open(request, timeout=effective_timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                if not raw:
                    return {}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise RequestError("A API devolveu JSON inválido") from exc
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {}
            nested = data.get("error") if isinstance(data, dict) else None
            code = None
            message = None
            if isinstance(nested, dict):
                code = nested.get("code")
                message = nested.get("message")
            if isinstance(data, dict):
                code = code or data.get("code")
                message = message or data.get("message")
            error_cls = AuthenticationError if exc.code in {401, 403} else EvemexAPIError
            raise error_cls(
                str(message or f"Erro HTTP {exc.code}"),
                status=exc.code,
                code=str(code) if code else None,
                data=data,
            ) from exc
        except (URLError, socket.timeout, TimeoutError) as exc:
            raise RequestError(f"Falha de conexão com {self.base_url}") from exc
