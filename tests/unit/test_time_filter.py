"""
tests/unit/test_time_filter.py — Testes do filtro de horário intraday.

Sprint-1 passo 4: bloqueia sinais em janelas de baixa liquidez (abertura,
fechamento, almoço). No-op em dados diários.

Executável diretamente:
    python tests/unit/test_time_filter.py
"""
from __future__ import annotations

import os
import sys
import traceback

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from strategy import CombinedStrategy


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _intraday_1h(n_days: int = 5) -> pd.DataFrame:
    """Gera DataFrame 1h cobrindo pregão B3 (10:00–17:00) em n_days dias úteis."""
    rows = []
    idx  = []
    price = 100_000.0
    dates = pd.bdate_range("2024-01-02", periods=n_days)
    rng = np.random.default_rng(7)
    for d in dates:
        for h in range(10, 18):   # 10:00, 11:00, ..., 17:00
            ts = pd.Timestamp(d) + pd.Timedelta(hours=h)
            price *= float(np.exp(rng.normal(0, 0.003)))
            high = price * 1.003
            low  = price * 0.997
            rows.append((price, high, low, price, 1_000_000.0))
            idx.append(ts)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx),
                        columns=["Open", "High", "Low", "Close", "Volume"])


def _daily(n: int = 50) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    rng = np.random.default_rng(3)
    closes = 100_000 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return pd.DataFrame({
        "Open":   closes,
        "High":   closes * 1.01,
        "Low":    closes * 0.99,
        "Close":  closes,
        "Volume": np.full(n, 1_000_000.0),
    }, index=idx)


def _make_strategy(df: pd.DataFrame, **params) -> CombinedStrategy:
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(df)
    s.params.update(params)
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Testes — detecção de granularidade
# ──────────────────────────────────────────────────────────────────────────────

def test_is_intraday_true_for_hourly():
    s = _make_strategy(_intraday_1h(3))
    assert s._is_intraday() is True
    print("  [OK] test_is_intraday_true_for_hourly")


def test_is_intraday_false_for_daily():
    s = _make_strategy(_daily(30))
    assert s._is_intraday() is False
    print("  [OK] test_is_intraday_false_for_daily")


def test_is_intraday_false_for_empty():
    s = CombinedStrategy("^BVSP")
    # sem data
    assert s._is_intraday() is False
    print("  [OK] test_is_intraday_false_for_empty")


# ──────────────────────────────────────────────────────────────────────────────
# Testes — _in_trading_window
# ──────────────────────────────────────────────────────────────────────────────

def test_window_blocks_before_start():
    s = _make_strategy(_intraday_1h(1))
    ts = pd.Timestamp("2024-01-02 10:00")   # antes de 10:15
    assert s._in_trading_window(ts) is False
    print("  [OK] test_window_blocks_before_start")


def test_window_allows_inside():
    s = _make_strategy(_intraday_1h(1))
    ts = pd.Timestamp("2024-01-02 11:00")
    assert s._in_trading_window(ts) is True
    print("  [OK] test_window_allows_inside")


def test_window_blocks_after_end():
    s = _make_strategy(_intraday_1h(1))
    ts = pd.Timestamp("2024-01-02 17:00")   # depois de 16:45
    assert s._in_trading_window(ts) is False
    print("  [OK] test_window_blocks_after_end")


def test_window_boundary_inclusive_at_start():
    s = _make_strategy(_intraday_1h(1))
    ts = pd.Timestamp("2024-01-02 10:15")
    assert s._in_trading_window(ts) is True
    print("  [OK] test_window_boundary_inclusive_at_start")


def test_window_boundary_inclusive_at_end():
    s = _make_strategy(_intraday_1h(1))
    ts = pd.Timestamp("2024-01-02 16:45")
    assert s._in_trading_window(ts) is True
    print("  [OK] test_window_boundary_inclusive_at_end")


def test_window_lunch_skip_blocks_noon():
    s = _make_strategy(_intraday_1h(1), time_filter_skip_lunch=True)
    ts = pd.Timestamp("2024-01-02 12:30")
    assert s._in_trading_window(ts) is False
    print("  [OK] test_window_lunch_skip_blocks_noon")


def test_window_lunch_skip_allows_before_and_after():
    s = _make_strategy(_intraday_1h(1), time_filter_skip_lunch=True)
    assert s._in_trading_window(pd.Timestamp("2024-01-02 11:59")) is True
    assert s._in_trading_window(pd.Timestamp("2024-01-02 14:00")) is True
    print("  [OK] test_window_lunch_skip_allows_before_and_after")


def test_window_lunch_not_skipped_by_default():
    s = _make_strategy(_intraday_1h(1))   # skip_lunch=False default
    assert s._in_trading_window(pd.Timestamp("2024-01-02 12:30")) is True
    print("  [OK] test_window_lunch_not_skipped_by_default")


def test_window_custom_hours():
    s = _make_strategy(_intraday_1h(1),
                        time_filter_start_hour=9, time_filter_start_minute=0,
                        time_filter_end_hour=18, time_filter_end_minute=0)
    assert s._in_trading_window(pd.Timestamp("2024-01-02 09:30")) is True
    assert s._in_trading_window(pd.Timestamp("2024-01-02 18:30")) is False
    print("  [OK] test_window_custom_hours")


# ──────────────────────────────────────────────────────────────────────────────
# Testes — integração com generate_signals
# ──────────────────────────────────────────────────────────────────────────────

def test_filter_disabled_by_default_is_noop():
    """Sem use_time_filter, nada muda (retrocompatibilidade)."""
    df = _intraday_1h(3)
    s_off = _make_strategy(df.copy())
    s_on  = _make_strategy(df.copy(), use_time_filter=False)
    # mesmos sinais
    sigs_off = s_off.generate_signals()
    sigs_on  = s_on.generate_signals()
    assert len(sigs_off) == len(sigs_on)
    print("  [OK] test_filter_disabled_by_default_is_noop")


def test_filter_no_op_on_daily_data():
    """Em dados diários, o filtro NUNCA bloqueia — mesmo com use_time_filter=True."""
    df = _daily(50)
    s_no  = _make_strategy(df.copy(), use_time_filter=False)
    s_yes = _make_strategy(df.copy(), use_time_filter=True)
    sigs_no  = s_no.generate_signals()
    sigs_yes = s_yes.generate_signals()
    assert len(sigs_no) == len(sigs_yes), (
        f"Filtro diário deveria ser no-op: {len(sigs_no)} vs {len(sigs_yes)}"
    )
    print("  [OK] test_filter_no_op_on_daily_data")


def test_filter_blocks_opening_signals_intraday():
    """Com filtro ligado em intraday, nenhum sinal gerado às 10:00 passa."""
    df = _intraday_1h(5)
    s = _make_strategy(df, use_time_filter=True,
                       time_filter_start_hour=10, time_filter_start_minute=15,
                       time_filter_end_hour=16, time_filter_end_minute=45)
    sigs = s.generate_signals()
    for sig in sigs:
        ts = sig["data"]
        assert not (ts.hour == 10 and ts.minute < 15), (
            f"Sinal às {ts} não deveria passar"
        )
        assert not (ts.hour == 17), f"Sinal às {ts} não deveria passar"
    print(f"  [OK] test_filter_blocks_opening_signals_intraday  ({len(sigs)} sinais restantes)")


def test_filter_reduces_signal_count_intraday():
    """Com filtro, contagem de sinais deve ser <= sem filtro."""
    df = _intraday_1h(5)
    s_off = _make_strategy(df.copy(), use_time_filter=False)
    s_on  = _make_strategy(df.copy(), use_time_filter=True,
                           time_filter_start_hour=11, time_filter_start_minute=0,
                           time_filter_end_hour=15, time_filter_end_minute=0,
                           time_filter_skip_lunch=True)
    sigs_off = s_off.generate_signals()
    sigs_on  = s_on.generate_signals()
    assert len(sigs_on) <= len(sigs_off), (
        f"Filtro deveria reduzir ou manter: {len(sigs_off)} -> {len(sigs_on)}"
    )
    print(f"  [OK] test_filter_reduces_signal_count_intraday  "
          f"({len(sigs_off)} -> {len(sigs_on)})")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

def run_all() -> int:
    tests = [
        test_is_intraday_true_for_hourly,
        test_is_intraday_false_for_daily,
        test_is_intraday_false_for_empty,
        test_window_blocks_before_start,
        test_window_allows_inside,
        test_window_blocks_after_end,
        test_window_boundary_inclusive_at_start,
        test_window_boundary_inclusive_at_end,
        test_window_lunch_skip_blocks_noon,
        test_window_lunch_skip_allows_before_and_after,
        test_window_lunch_not_skipped_by_default,
        test_window_custom_hours,
        test_filter_disabled_by_default_is_noop,
        test_filter_no_op_on_daily_data,
        test_filter_blocks_opening_signals_intraday,
        test_filter_reduces_signal_count_intraday,
    ]
    print("=" * 60)
    print("  Suite: Filtro de Horario Intraday (Sprint-1 passo 4)")
    print("=" * 60)
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception:
            failed += 1
            print(f"  [FAIL] {fn.__name__}")
            traceback.print_exc()
    passed = len(tests) - failed
    print("=" * 60)
    print(f"  Resultado: {passed} passou(aram) / {failed} falhou(aram)")
    print("=" * 60)
    return failed


if __name__ == "__main__":
    sys.exit(run_all())
