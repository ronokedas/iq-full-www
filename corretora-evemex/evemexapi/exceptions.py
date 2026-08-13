"""Exceções públicas do cliente Evemex."""

from __future__ import annotations

from typing import Any


class EvemexAPIError(RuntimeError):
    """Erro devolvido pela API da Evemex."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.data = data


class AuthenticationError(EvemexAPIError):
    """Credenciais inválidas, sessão expirada ou 2FA necessário."""


class RequestError(EvemexAPIError):
    """Falha de transporte, timeout ou resposta inválida."""

