"""Armazenamento local protegido para sessões Polarium no Windows."""

from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect(raw: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI está disponível somente no Windows")
    source_buf = ctypes.create_string_buffer(raw)
    source = _Blob(len(raw), ctypes.cast(source_buf, ctypes.POINTER(ctypes.c_byte)))
    target = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), "Polarium session", None, None, None, 0x01, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _unprotect(raw: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI está disponível somente no Windows")
    source_buf = ctypes.create_string_buffer(raw)
    source = _Blob(len(raw), ctypes.cast(source_buf, ctypes.POINTER(ctypes.c_byte)))
    target = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


class SessionStore:
    """Persiste somente dados de sessão, nunca senha."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, payload: dict[str, Any]) -> None:
        safe = {key: value for key, value in payload.items() if key != "password"}
        encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(_protect(encoded))
        temporary.replace(self.path)

    def load(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(_unprotect(self.path.read_bytes()).decode("utf-8"))
            return payload if isinstance(payload, dict) and "password" not in payload else None
        except Exception:
            return None

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

