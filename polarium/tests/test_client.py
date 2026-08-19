from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from polariumapi import AuthenticationError, PolariumClient
from polariumapi import client as client_module
from polariumapi.secure_store import SessionStore


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_email_login_does_not_create_driver(monkeypatch, tmp_path: Path):
    client = PolariumClient("user@example.com", "secret")
    client._opener.open = lambda request, timeout: _Response({"ssid": "ssid-test", "token": "token-test"})
    monkeypatch.setattr(client, "_validate_websocket_session", lambda: None)
    monkeypatch.setattr(client, "save_session", lambda: None)
    monkeypatch.setattr(client, "_get_driver", lambda: pytest.fail("Edge não deve ser criado no login por senha"))
    assert client.connect() is True
    assert client._password is None


def test_invalid_credentials_are_reported(monkeypatch):
    client = PolariumClient("user@example.com", "wrong")

    class ErrorResponse:
        code = 401

        def read(self):
            return b'{"code":"invalid_credentials","message":"credenciais invalidas"}'

    from urllib.error import HTTPError
    def fail(*args, **kwargs):
        raise HTTPError("https://example.invalid", 401, "Unauthorized", {}, None)

    # O teste cobre o caminho de erro sem acessar a rede.
    monkeypatch.setattr(client._opener, "open", fail)
    with pytest.raises(AuthenticationError):
        client.connect()


def test_legacy_plaintext_session_is_not_loaded(tmp_path: Path):
    path = tmp_path / "session.dpapi"
    store = SessionStore(path)
    if os.name != "nt":
        pytest.skip("DPAPI somente no Windows")
    store.save({"email": "a@b.com", "ssid": "abc"})
    assert store.load() == {"email": "a@b.com", "ssid": "abc"}
    path.write_text('{"email":"a@b.com","password":"secret"}', encoding="utf-8")
    assert store.load() is None


def test_open_operation_rejects_synthetic_success(monkeypatch):
    client = PolariumClient()
    client._ssid = "ssid"
    client._selected_account = client_module.Account("demo", 99, "DEMO", 100.0)
    client._active_ids["eurusdotc"] = 123

    class FakeWS:
        def open_option(self, **kwargs):
            return {"name": "option", "msg": {"message": "rejected"}}

    client._ws = FakeWS()
    with pytest.raises(Exception):
        client.open_operation("eurusd_otc", 2, "UP", 9_999_999_999)
