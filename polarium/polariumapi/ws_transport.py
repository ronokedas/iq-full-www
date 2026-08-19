"""Transporte WebSocket direto do Traderoom Polarium."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import websocket

from .exceptions import AuthenticationError, PolariumAPIError, RequestError

WS_URL = "wss://ws.trade.polariumbroker.com:443/echo/websocket"


class PolariumWebSocket:
    def __init__(self, ssid: str, *, url: str = WS_URL, timeout: float = 15.0) -> None:
        self.ssid = ssid
        self.url = url
        self.timeout = timeout
        self.socket: websocket.WebSocket | None = None
        self._counter = 0

    def _id(self) -> str:
        self._counter += 1
        return f"polarium-{self._counter}-{uuid.uuid4().hex[:6]}"

    def connect(self) -> None:
        if not self.ssid:
            raise AuthenticationError("SSID da sessão Polarium ausente")
        self.socket = websocket.create_connection(self.url, timeout=self.timeout, origin="https://trade.polariumbroker.com")
        request_id = self._id()
        self.send({"name": "authenticate", "request_id": request_id, "msg": {
            "ssid": self.ssid, "protocol": 3, "session_id": "", "client_session_id": "",
        }})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            message = self.recv(timeout=max(0.1, deadline - time.monotonic()))
            if message.get("name") == "authenticated":
                if message.get("msg") is not True:
                    raise AuthenticationError("Sessão Polarium rejeitada pelo WebSocket")
                return
            if message.get("name") == "error":
                raise AuthenticationError(str(message.get("msg") or "Falha na autenticação WebSocket"))
        raise AuthenticationError("Tempo esgotado aguardando autenticação WebSocket")

    def send(self, payload: dict[str, Any]) -> None:
        if self.socket is None:
            raise PolariumAPIError("WebSocket Polarium não conectado")
        self.socket.send(json.dumps(payload, separators=(",", ":")))

    def recv(self, *, timeout: float | None = None) -> dict[str, Any]:
        if self.socket is None:
            raise PolariumAPIError("WebSocket Polarium não conectado")
        self.socket.settimeout(timeout or self.timeout)
        try:
            raw = self.socket.recv()
        except Exception as exc:
            raise RequestError(f"Falha ao receber mensagem do WebSocket: {exc}") from exc
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RequestError("Resposta WebSocket inválida") from exc
        return data if isinstance(data, dict) else {"name": "invalid", "msg": data}

    def request(self, name: str, *, version: str = "1.0", body: dict[str, Any] | None = None,
                timeout: float | None = None) -> dict[str, Any]:
        request_id = self._id()
        self.send({"name": "sendMessage", "request_id": request_id, "msg": {
            "name": name, "version": version, "body": body or {},
        }})
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            response = self.recv(timeout=max(0.1, deadline - time.monotonic()))
            if str(response.get("request_id")) != request_id:
                continue
            if response.get("name") == "result":
                if isinstance(response.get("msg"), dict) and response["msg"].get("success") is False:
                    raise RequestError(str(response["msg"].get("message") or "Requisição Polarium rejeitada"))
                # O Traderoom envia primeiro um ACK e depois o payload com o mesmo request_id.
                continue
            return response
        raise RequestError(f"Tempo esgotado aguardando resposta para {name}")

    def open_option(self, *, balance_id: int, active_id: int, amount: float, direction: str,
                    expiration_at: int, option_type_id: int = 3, request_id: str | None = None) -> dict[str, Any]:
        direction_map = {"UP": "call", "DOWN": "put", "CALL": "call", "PUT": "put"}
        normalized = direction_map.get(str(direction).upper())
        if normalized is None:
            raise ValueError("Direção deve ser UP/DOWN ou CALL/PUT")
        rid = request_id or self._id()
        self.send({"name": "sendMessage", "request_id": rid, "msg": {
            "name": "binary-options.open-option", "version": "1.0", "body": {
                "user_balance_id": int(balance_id), "active_id": int(active_id),
                "option_type_id": int(option_type_id), "direction": normalized,
                "expired": int(expiration_at), "price": round(float(amount), 2),
            },
        }})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            response = self.recv(timeout=max(0.1, deadline - time.monotonic()))
            if str(response.get("request_id")) == rid and response.get("name") == "result":
                result = response.get("msg")
                if isinstance(result, dict) and result.get("success") is False:
                    raise RequestError(str(result.get("message") or "Ordem rejeitada"))
                continue
            if str(response.get("request_id")) != rid and response.get("name") not in {"option", "error"}:
                continue
            if response.get("name") == "error":
                raise RequestError(str(response.get("msg") or "Ordem rejeitada"))
            msg = response.get("msg")
            if isinstance(msg, dict) and any(key in msg for key in ("id", "option_id", "message", "error")):
                if msg.get("message") or msg.get("error"):
                    raise RequestError(str(msg.get("message") or msg.get("error")))
                return response
        raise RequestError("Tempo esgotado aguardando confirmação da ordem")

    def close(self) -> None:
        if self.socket is not None:
            try:
                self.socket.close()
            finally:
                self.socket = None
