"""Exceções públicas do cliente Polarium Broker."""

from __future__ import annotations

from typing import Any


class PolariumAPIError(RuntimeError):
    """Erro devolvido pela API da Polarium Broker."""

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


class AuthenticationError(PolariumAPIError):
    """Credenciais inválidas, sessão expirada ou 2FA necessário."""


class RequestError(PolariumAPIError):
    """Falha de transporte, timeout ou resposta inválida."""
