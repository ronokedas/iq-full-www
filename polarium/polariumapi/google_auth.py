"""Login Google interativo no Edge e armazenamento protegido pelo Windows para Polarium Broker."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import ctypes
import socket
import tempfile
import threading
from ctypes import wintypes
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from .exceptions import AuthenticationError

SERVICE_NAME = "polarium-trading-bot"
SERVICE_USER = "google-session"
LOGIN_URL = "https://trade.polariumbroker.com/traderoom"
PROFILE_DIRECTORY_NAME = "edge-google-login-polarium"
SESSION_FILE_NAME = "google-session-polarium.dpapi"
CAPTURED_TOKEN_KEY = "__polarium_google_callback_token"
BROWSER_SIGNIN_DIALOG_PREFIXES = (
    "edge://sync-confirmation-dialog/",
    "edge://signin-internals/",
    "chrome://sync-confirmation/",
)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect_with_windows_dpapi(data: bytes) -> bytes:
    """Protege dados de qualquer tamanho para o usuário atual do Windows."""
    if os.name != "nt":
        raise OSError("DPAPI está disponível somente no Windows")
    buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    protected = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "Polarium Google session", None, None, None, 0x01, ctypes.byref(protected)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(protected.pbData)


def _unprotect_with_windows_dpapi(data: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI está disponível somente no Windows")
    buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    plain = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(plain)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(plain.pbData, plain.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(plain.pbData)


@dataclass(frozen=True, slots=True)
class GoogleSession:
    token: str
    cookies: list[dict[str, Any]]
    created_at: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GoogleSession":
        return cls(
            token=str(payload["token"]),
            cookies=list(payload.get("cookies") or []),
            created_at=int(payload.get("created_at") or time.time()),
        )


class SessionStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or (Path.home() / ".polarium")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / SESSION_FILE_NAME

    def save(self, session: GoogleSession) -> None:
        raw = json.dumps(session.to_dict()).encode("utf-8")
        protected = _protect_with_windows_dpapi(raw)
        self.path.write_bytes(protected)

    def load(self) -> GoogleSession | None:
        if not self.path.exists():
            return None
        try:
            protected = self.path.read_bytes()
            raw = _unprotect_with_windows_dpapi(protected)
            return GoogleSession.from_dict(json.loads(raw.decode("utf-8")))
        except Exception:
            return None

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class GoogleAuthenticator:
    def __init__(self, login_url: str = LOGIN_URL, store: SessionStore | None = None) -> None:
        self.login_url = login_url
        self.store = store or SessionStore()

    def restore(self) -> GoogleSession | None:
        return self.store.load()

    def forget(self) -> None:
        self.store.clear()

    def interactive_login(self) -> GoogleSession:
        session = self.restore()
        if session:
            return session
        raise AuthenticationError("Sessão Google não salva. Faça o login manualmente via formulário.")
