from trading_bot.config import RiskConfig, StrategyConfig
from trading_bot.risk import DailyLossKillSwitch, compute_stop_and_target, size_position


def test_compute_stop_and_target():
    cfg = StrategyConfig(atr_stop_mult=2.0, atr_target_mult=3.0)
    stop, target = compute_stop_and_target(entry_price=100.0, atr=5.0, cfg=cfg)
    assert stop == 90.0
    assert target == 115.0


def test_stop_loss_never_goes_negative():
    cfg = StrategyConfig(atr_stop_mult=10.0, atr_target_mult=1.0)
    stop, _ = compute_stop_and_target(entry_price=10.0, atr=5.0, cfg=cfg)
    assert stop == 0.0


def test_size_position_risks_at_most_configured_pct():
    risk_cfg = RiskConfig(risk_per_trade_pct=1.0, min_order_quote=1.0)
    result = size_position(balance_quote=10_000.0, entry_price=100.0, stop_loss=95.0, risk_cfg=risk_cfg)
    assert result is not None
    max_loss = (100.0 - 95.0) * result.amount
    assert abs(max_loss - 100.0) < 1e-6  # 1% of 10,000


def test_size_position_rejects_when_below_minimum_notional():
    risk_cfg = RiskConfig(risk_per_trade_pct=0.01, min_order_quote=1000.0)
    result = size_position(balance_quote=10_000.0, entry_price=100.0, stop_loss=95.0, risk_cfg=risk_cfg)
    assert result is None


def test_size_position_rejects_invalid_stop_above_entry():
    risk_cfg = RiskConfig()
    result = size_position(balance_quote=10_000.0, entry_price=100.0, stop_loss=105.0, risk_cfg=risk_cfg)
    assert result is None


def test_daily_loss_kill_switch_triggers_past_threshold():
    risk_cfg = RiskConfig(max_daily_loss_pct=5.0)
    switch = DailyLossKillSwitch(risk_cfg)
    assert switch.update(current_equity=1000.0) is False
    assert switch.update(current_equity=960.0) is False  # 4% down
    assert switch.update(current_equity=940.0) is True  # 6% down, triggers
    assert switch.triggered is True


def test_daily_loss_kill_switch_resets_next_day(monkeypatch):
    risk_cfg = RiskConfig(max_daily_loss_pct=5.0)
    switch = DailyLossKillSwitch(risk_cfg)

    switch._day = "2024-01-01"
    switch._start_equity = 1000.0
    switch.triggered = True

    monkeypatch.setattr(switch, "_today", lambda: "2024-01-02")
    triggered = switch.update(current_equity=800.0)
    assert triggered is False
    assert switch._start_equity == 800.0


def test_daily_loss_kill_switch_persists_across_fresh_instances(tmp_path):
    state_path = str(tmp_path / "kill_switch.json")
    risk_cfg = RiskConfig(max_daily_loss_pct=5.0)

    first = DailyLossKillSwitch(risk_cfg, state_path=state_path)
    assert first.update(current_equity=1000.0) is False
    assert first.update(current_equity=940.0) is True  # 6% down, triggers

    # A brand new process (e.g. the next GitHub Actions run) must see the
    # same day/start_equity/triggered state instead of starting fresh.
    second = DailyLossKillSwitch(risk_cfg, state_path=state_path)
    assert second.triggered is True
    assert second._start_equity == 1000.0
    assert second._day == first._day


def test_daily_loss_kill_switch_without_state_path_stays_in_memory_only(tmp_path):
    risk_cfg = RiskConfig(max_daily_loss_pct=5.0)
    switch = DailyLossKillSwitch(risk_cfg)  # no state_path - existing in-memory behavior
    assert switch.state_path is None
    assert switch.update(current_equity=1000.0) is False  # doesn't raise trying to save
