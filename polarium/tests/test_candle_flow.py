from unified_ai_bot import PairManager


def candle(ts: int) -> dict:
    return {"from": ts, "open": 1, "high": 2, "low": 0, "close": 1}


def test_signal_trigger_happens_only_when_previous_candle_closes():
    manager = PairManager("eurusd_otc", 76)
    assert manager.update_candle(candle(100)) is False
    assert manager.update_candle(candle(101)) is True
    assert manager.update_candle(candle(101)) is False
    assert len(manager.buffer) == 1
