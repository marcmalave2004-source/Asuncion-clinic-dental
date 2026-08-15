from trading_bot.portfolio import Position, PositionStore


def _position(symbol="AAPL", amount=1.0, entry=100.0, stop=90.0, target=115.0):
    return Position(symbol=symbol, amount=amount, entry_price=entry, stop_loss=stop, take_profit=target)


def test_exit_reason_stop_loss():
    pos = _position(stop=90.0, target=115.0)
    assert pos.exit_reason(current_price=89.0) == "stop_loss"


def test_exit_reason_take_profit():
    pos = _position(stop=90.0, target=115.0)
    assert pos.exit_reason(current_price=116.0) == "take_profit"


def test_exit_reason_none_when_price_between_stop_and_target():
    pos = _position(stop=90.0, target=115.0)
    assert pos.exit_reason(current_price=105.0) is None


def test_unrealized_pnl():
    pos = _position(amount=2.0, entry=100.0)
    assert pos.unrealized_pnl(current_price=110.0) == 20.0


def test_position_store_round_trips_multiple_symbols(tmp_path):
    store = PositionStore(path=str(tmp_path / "positions.json"))
    positions = {
        "AAPL": _position(symbol="AAPL", entry=200.0),
        "VOO": _position(symbol="VOO", entry=400.0),
    }

    store.save_all(positions)
    loaded = store.load_all()

    assert set(loaded.keys()) == {"AAPL", "VOO"}
    assert loaded["AAPL"].entry_price == 200.0
    assert loaded["VOO"].entry_price == 400.0


def test_position_store_load_all_returns_empty_dict_when_missing(tmp_path):
    store = PositionStore(path=str(tmp_path / "does_not_exist.json"))
    assert store.load_all() == {}


def test_position_store_save_all_empty_then_load(tmp_path):
    store = PositionStore(path=str(tmp_path / "positions.json"))
    store.save_all({})
    assert store.load_all() == {}
