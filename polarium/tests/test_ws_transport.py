from __future__ import annotations

import json

from polariumapi.ws_transport import PolariumWebSocket


class FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    def send(self, raw):
        self.sent.append(json.loads(raw))

    def recv(self):
        return json.dumps(self.messages.pop(0))

    def settimeout(self, value):
        return None

    def close(self):
        return None


def test_authentication_requires_positive_confirmation(monkeypatch):
    fake = FakeSocket([{"name": "authenticated", "msg": True}])
    monkeypatch.setattr("polariumapi.ws_transport.websocket.create_connection", lambda *a, **k: fake)
    transport = PolariumWebSocket("ssid")
    transport.connect()
    assert fake.sent[0]["name"] == "authenticate"


def test_order_contains_real_trade_parameters(monkeypatch):
    fake = FakeSocket([{"name": "option", "request_id": "req-1", "msg": {"id": 777}}])
    transport = PolariumWebSocket("ssid")
    transport.socket = fake
    response = transport.open_option(balance_id=42, active_id=2270, amount=2.5,
                                     direction="DOWN", expiration_at=1_900_000_000,
                                     request_id="req-1")
    message = fake.sent[0]
    body = message["msg"]["body"]
    assert response["msg"]["id"] == 777
    assert body == {
        "user_balance_id": 42,
        "active_id": 2270,
        "option_type_id": 3,
        "direction": "put",
        "expired": 1_900_000_000,
        "price": 2.5,
    }

