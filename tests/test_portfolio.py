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


def test_peak_price_starts_at_entry_price():
    pos = _position(entry=100.0)
    assert pos.peak_price == 100.0


def test_update_peak_tracks_the_highest_price_seen():
    pos = _position(entry=100.0)
    pos.update_peak(105.0)
    pos.update_peak(103.0)  # a pullback should not lower the recorded peak
    pos.update_peak(108.0)
    assert pos.peak_price == 108.0


def test_trailing_stop_disabled_by_default():
    pos = _position(entry=100.0, stop=90.0, target=200.0)
    pos.update_peak(110.0)
    # Even a big pullback from the peak shouldn't exit without trailing_stop_pct set.
    assert pos.exit_reason(current_price=101.0) is None


def test_trailing_stop_triggers_after_pullback_from_peak_while_still_in_profit():
    pos = _position(entry=100.0, stop=90.0, target=200.0)
    pos.update_peak(110.0)
    # 2% below the 110 peak is 107.8, and 105 is still above the 100 entry.
    assert pos.exit_reason(current_price=105.0, trailing_stop_pct=2.0) == "trailing_stop"


def test_trailing_stop_does_not_trigger_before_reaching_the_pullback_threshold():
    pos = _position(entry=100.0, stop=90.0, target=200.0)
    pos.update_peak(110.0)
    assert pos.exit_reason(current_price=109.0, trailing_stop_pct=2.0) is None


def test_trailing_stop_never_fires_at_a_net_loss():
    pos = _position(entry=100.0, stop=90.0, target=200.0)
    pos.update_peak(101.0)  # barely above entry, so a 2% trail sits below entry
    assert pos.exit_reason(current_price=95.0, trailing_stop_pct=2.0) is None


def test_hard_stop_loss_takes_priority_over_trailing_stop():
    pos = _position(entry=100.0, stop=90.0, target=200.0)
    pos.update_peak(110.0)
    assert pos.exit_reason(current_price=89.0, trailing_stop_pct=2.0) == "stop_loss"


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
