from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from evemexapi import AuthenticationError, EvemexClient, GoogleSession


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict | None]] = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        path = urlparse(url).path
        if path == "/auth/login":
            if body["password"] == "bad":
                return {"ok": False, "code": "invalid", "message": "inválido"}
            return {"ok": True, "token": "token-de-teste-comprido"}
        if path == "/me":
            return {
                "accounts": [
                    {"accountId": "d", "tradeId": 1, "type": "DEMO", "balance": 10000},
                    {"accountId": "r", "tradeId": 2, "type": "REAL", "balance": 50},
                ]
            }
        if path == "/otc/assets":
            return {"assets": ["EURUSD_otc"], "timeframes": ["1m"]}
        if path == "/otc/assets/info":
            return {"assets": [{"symbol": "EURUSD_otc", "name": "EURUSD"}]}
        if path == "/otc/candles/latest":
            return {
                "candles": [
                    {"symbol": "EURUSD_otc", "from": 60, "to": 120, "open": 1, "high": 2, "low": 1, "close": 2}
                ]
            }
        if path == "/otc/candles/latest/batch":
            return {
                "results": {
                    "EURUSD_otc": {
                        "candles": [
                            {"from": 60, "to": 120, "open": 1, "high": 2, "low": 1, "close": 2}
                        ]
                    }
                }
            }
        if path == "/ops/expirations":
            return {
                "serverTimeMs": 119000,
                "slots": [
                    {"label": "1M", "expirationAtSec": 180},
                    {"label": "5M", "expirationAtSec": 420},
                ],
            }
        if path == "/ops/open_operation":
            return {"result": {"id": "op-1"}}
        if path == "/ops/operations/history":
            return {"items": [{"id": "op-1", "status": "closed", "result": "WIN", "profit": 1.98}]}
        if path == "/ops/operations/open":
            return {"items": []}
        raise AssertionError(f"Endpoint inesperado: {path}")


class ClientTests(unittest.TestCase):
    class GoogleAuthFake:
        def __init__(self, restored=None, interactive=None):
            self.restored, self.interactive, self.saved, self.forgotten = restored, interactive, [], False

        def restore(self): return self.restored
        def interactive_login(self):
            if self.interactive is None: raise AssertionError("não deveria abrir o Edge")
            return self.interactive
        def forget(self): self.forgotten = True
        @property
        def store(self): return self
        def save(self, session): self.saved.append(session)

    def setUp(self):
        self.transport = FakeTransport()
        self.client = EvemexClient("user@example.com", "secret", transport=self.transport)
        self.client.connect()

    def test_auth_and_account_selection(self):
        account = self.client.select_account("DEMO")
        self.assertEqual(account.balance, 10000)
        self.assertEqual(account.mode, "DEMO")
        me_call = next(call for call in self.transport.calls if urlparse(call[1]).path == "/me")
        self.assertEqual(me_call[2]["Authorization"], "Bearer token-de-teste-comprido")

    def test_failed_login_does_not_connect(self):
        client = EvemexClient("user@example.com", "bad", transport=self.transport)
        with self.assertRaises(AuthenticationError):
            client.connect()
        self.assertFalse(client.connected)

    def test_session_can_be_reconnected_before_close(self):
        self.client._token = None
        self.assertTrue(self.client.connect())
        login_calls = [call for call in self.transport.calls if urlparse(call[1]).path == "/auth/login"]
        self.assertEqual(len(login_calls), 2)

        self.client.close()
        with self.assertRaises(AuthenticationError):
            self.client.connect()

    def test_google_restores_token_session_and_validates_me(self):
        session = GoogleSession(token="token-google-comprido-demais")
        auth = self.GoogleAuthFake(restored=session)
        client = EvemexClient.with_google(authenticator=auth, transport=self.transport)
        self.assertTrue(client.connect())
        self.assertTrue(client.connected)
        self.assertFalse(auth.saved)
        me_call = next(call for call in self.transport.calls if urlparse(call[1]).path == "/me")
        self.assertEqual(me_call[2]["Authorization"], "Bearer token-google-comprido-demais")

    def test_google_restores_cookie_session_and_validates_me(self):
        session = GoogleSession(cookies=({"name": "evemex_session", "value": "cookie-secreto", "domain": ".evemex.com", "path": "/", "secure": True},))
        client = EvemexClient.with_google(authenticator=self.GoogleAuthFake(restored=session), transport=self.transport)
        self.assertTrue(client.connect())
        self.assertTrue(client.connected)
        self.assertEqual([(cookie.name, cookie.value) for cookie in client._cookie_jar()], [("evemex_session", "cookie-secreto")])

    def test_google_invalid_saved_session_reopens_and_saves_new_session(self):
        old, fresh = GoogleSession(token="token-antigo-comprido-demais"), GoogleSession(token="token-novo-comprido-demais")
        auth = self.GoogleAuthFake(restored=old, interactive=fresh)
        calls = {"me": 0}
        def transport(method, url, headers, body, timeout):
            if urlparse(url).path == "/me":
                calls["me"] += 1
                if calls["me"] == 1: raise AuthenticationError("expirada", status=401)
                return {"accounts": []}
            raise AssertionError(url)
        client = EvemexClient.with_google(authenticator=auth, transport=transport)
        self.assertTrue(client.connect())
        self.assertTrue(auth.forgotten)
        self.assertEqual(auth.saved, [fresh])

    def test_assets_candles_and_batch_are_normalized(self):
        self.assertEqual(self.client.get_otc_assets()[0]["symbol"], "EURUSD_otc")
        candle = self.client.get_candles("EURUSD_otc", limit=1)[0]
        self.assertEqual(candle.from_ts, 60)
        batch = self.client.get_candles_batch(["EURUSD_otc"])
        self.assertEqual(batch["EURUSD_otc"][0].symbol, "EURUSD_otc")

    def test_expiration_and_open_payload(self):
        self.client.select_account("DEMO")
        expiration, _ = self.client.select_one_minute_expiration("EURUSD_otc")
        response = self.client.open_operation(
            "EURUSD_otc", 2.0, "DOWN", expiration, client_request_id="req-fixed"
        )
        self.assertEqual(response["result"]["id"], "op-1")
        open_call = next(call for call in self.transport.calls if urlparse(call[1]).path == "/ops/open_operation")
        body = open_call[3]
        self.assertTrue(body["demo"])
        self.assertEqual(body["trend"], "DOWN")
        self.assertEqual(body["expirationAtSec"], 180)
        self.assertEqual(body["clientRequestId"], "req-fixed")

    def test_five_minute_expiration_and_open_payload(self):
        self.client.select_account("DEMO")
        expiration, _ = self.client.select_expiration("EURUSD_otc", 300)
        self.assertEqual(expiration, 420)
        self.client.open_operation("EURUSD_otc", 2.0, "UP", expiration, expiration_tf_sec=300)
        open_call = next(call for call in self.transport.calls if urlparse(call[1]).path == "/ops/open_operation")
        self.assertEqual(open_call[3]["timeframe"], "5m")
        self.assertEqual(open_call[3]["expirationTfSec"], 300)

    def test_real_open_payload_is_not_demo(self):
        self.client.select_account("REAL")
        self.client.open_operation("EURUSD_otc", 2.0, "UP", 180)
        open_call = next(call for call in self.transport.calls if urlparse(call[1]).path == "/ops/open_operation")
        self.assertFalse(open_call[3]["demo"])

    def test_history_uses_selected_account(self):
        self.client.select_account("REAL")
        result = self.client.wait_result("op-1", timeout=1)
        self.assertEqual(result.result, "WIN")
        history_call = next(call for call in self.transport.calls if urlparse(call[1]).path == "/ops/operations/history")
        self.assertEqual(parse_qs(urlparse(history_call[1]).query)["accountKind"], ["real"])


if __name__ == "__main__":
    unittest.main()
