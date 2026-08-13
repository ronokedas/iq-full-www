from __future__ import annotations

import os
import unittest

from evemexapi import EvemexClient


@unittest.skipUnless(os.environ.get("EVEMEX_INTEGRATION") == "1", "integração desativada")
class ReadOnlyIntegrationTests(unittest.TestCase):
    def test_login_accounts_assets_and_candles(self):
        email = os.environ["EVEMEX_EMAIL"]
        password = os.environ["EVEMEX_PASSWORD"]
        client = EvemexClient(email, password)
        try:
            self.assertTrue(client.connect())
            self.assertTrue(client.get_accounts())
            client.select_account("DEMO")
            assets = client.get_otc_assets()
            self.assertTrue(assets)
            candles = client.get_candles(assets[0]["symbol"], "1m", 5)
            self.assertTrue(candles)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()

