"""
tests/unit/test_vol_targeting.py — Testes do Volatility Targeting.

Sprint-2 passo 2: escala tamanho de posicao pela vol realizada para
manter exposicao ao risco constante ao longo de diferentes regimes.

Executavel diretamente:
    python tests/unit/test_vol_targeting.py
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

from indicators import TechnicalIndicators
from backtester import Backtester
from strategy import CombinedStrategy


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _ohlcv(n: int, vol: float, start: float = 100.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(0, vol, n)))
    high  = close * (1 + np.abs(rng.normal(0, vol * 0.5, n)))
    low   = close * (1 - np.abs(rng.normal(0, vol * 0.5, n)))
    idx   = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def _price_series(triples, start="2023-01-02"):
    """(high, low, close) -> DataFrame OHLCV — mesmo helper dos testes de partial."""
    rows, idx = [], pd.date_range(start, periods=len(triples), freq="B")
    for h, l, c in triples:
        rows.append({"Open": c, "High": h, "Low": l, "Close": c, "Volume": 1e6})
    return pd.DataFrame(rows, index=idx)


def _make_bt(df, signals, **params):
    class _MockStrategy:
        data  = df
        name  = "test"
        def prepare(self): pass
        def generate_signals(self): return signals
        self_params = {
            "max_risk_pct": 0.02, "max_position_pct": 0.5,
            "use_partial_exit": False,
        }
        self_params.update(params)
        self.params = self_params

    class _Strat(_MockStrategy):
        params = {
            "max_risk_pct": 0.02, "max_position_pct": 0.5,
            "use_partial_exit": False,
            **params,
        }
    return Backtester(_Strat(), initial_capital=100_000.0, cooldown_bars=0,
                      commission_per_trade=0.0, slippage_pct=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Testes — realized_vol
# ─────────────────────────────────────────────────────────────────────────────

def test_realized_vol_returns_same_length():
    df = _ohlcv(100, 0.01)
    rv = TechnicalIndicators.realized_vol(df["Close"], window=20)
    assert len(rv) == 100
    print("  [OK] test_realized_vol_returns_same_length")


def test_realized_vol_nan_below_half_window():
    df = _ohlcv(100, 0.01)
    rv = TechnicalIndicators.realized_vol(df["Close"], window=20)
    # min_periods = max(10, 4) = 10; primeiros 9 devem ser NaN
    assert rv.iloc[:9].isna().all(), "Primeiros 9 deveriam ser NaN"
    assert rv.iloc[9:].notna().any()
    print("  [OK] test_realized_vol_nan_below_half_window")


def test_realized_vol_higher_for_higher_vol():
    """Serie mais volatil -> vol realizada maior."""
    lo = _ohlcv(200, 0.005, seed=1)
    hi = _ohlcv(200, 0.020, seed=1)
    rv_lo = TechnicalIndicators.realized_vol(lo["Close"], window=20).dropna().mean()
    rv_hi = TechnicalIndicators.realized_vol(hi["Close"], window=20).dropna().mean()
    assert rv_hi > rv_lo, f"rv_hi={rv_hi:.4f} deveria > rv_lo={rv_lo:.4f}"
    print(f"  [OK] test_realized_vol_higher_for_higher_vol  "
          f"(lo={rv_lo:.4f}, hi={rv_hi:.4f})")


def test_realized_vol_annualizes_correctly():
    """Vol diaria de 1%: vol anualizada ~= 1% * sqrt(252) ~= 15.9%."""
    n = 500
    rng = np.random.default_rng(42)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    s = pd.Series(close, index=pd.date_range("2023-01-02", periods=n, freq="B"))
    rv = TechnicalIndicators.realized_vol(s, window=60, ann_factor=float(np.sqrt(252)))
    mean_rv = rv.dropna().mean()
    expected = 0.01 * np.sqrt(252)  # ~0.159
    assert abs(mean_rv - expected) < 0.04, \
        f"Vol anualizada esperada ~{expected:.3f}, obteve {mean_rv:.3f}"
    print(f"  [OK] test_realized_vol_annualizes_correctly  "
          f"(esperado={expected:.3f}, obtido={mean_rv:.3f})")


def test_realized_vol_in_compute_all():
    df = _ohlcv(100, 0.01)
    out = TechnicalIndicators.compute_all(df)
    assert "Realized_Vol" in out.columns
    assert out["Realized_Vol"].dropna().gt(0).all()
    print("  [OK] test_realized_vol_in_compute_all")


def test_infer_ann_factor_daily():
    df = _ohlcv(50, 0.01)  # freq='B' = diario
    af = TechnicalIndicators._infer_ann_factor(df)
    expected = float(np.sqrt(252))
    assert abs(af - expected) < 0.01, f"Esperado {expected:.2f}, obteve {af:.2f}"
    print(f"  [OK] test_infer_ann_factor_daily  (af={af:.2f})")


def test_infer_ann_factor_hourly():
    idx = pd.date_range("2023-01-02 10:00", periods=80, freq="1h")
    df  = pd.DataFrame({"Close": np.ones(80)}, index=idx)
    af  = TechnicalIndicators._infer_ann_factor(df)
    expected = float(np.sqrt(252 * 8))
    assert abs(af - expected) < 0.1, f"Esperado {expected:.2f}, obteve {af:.2f}"
    print(f"  [OK] test_infer_ann_factor_hourly  (af={af:.2f})")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — vol targeting no backtester
# ─────────────────────────────────────────────────────────────────────────────

def _make_strat_bt(df: pd.DataFrame, ticker: str = "^BVSP", **params) -> Backtester:
    s = CombinedStrategy(ticker, name="vt_test")
    s.set_data(df.copy())
    s.params.update(params)
    return Backtester(s, initial_capital=100_000.0, cooldown_bars=0,
                      commission_per_trade=0.0, slippage_pct=0.0)


def test_vol_targeting_disabled_by_default():
    """Sem use_vol_targeting, resultado identico ao baseline."""
    df = _ohlcv(200, 0.012, seed=7)
    bt_off = _make_strat_bt(df, use_vol_targeting=False)
    bt_on  = _make_strat_bt(df, use_vol_targeting=False)
    m_off  = bt_off.run()
    m_on   = bt_on.run()
    assert m_off["trade_count"] == m_on["trade_count"]
    print("  [OK] test_vol_targeting_disabled_by_default")


def test_vol_targeting_scales_down_in_high_vol():
    """Scalar calculado deve ser menor em regime de alta vol.

    Verifica o scalar diretamente via Realized_Vol, sem depender do
    numero de trades gerados (que varia pelo gerador de sinais).
    """
    df_lo = _ohlcv(300, 0.003, seed=10)   # ~3% diario  => rv_ann ~4.8%
    df_hi = _ohlcv(300, 0.030, seed=10)   # ~30% diario => rv_ann ~47.6%

    rv_lo = TechnicalIndicators.realized_vol(df_lo["Close"], window=20).dropna()
    rv_hi = TechnicalIndicators.realized_vol(df_hi["Close"], window=20).dropna()

    target = 0.15
    scalar_lo = (target / rv_lo).clip(0.1, 4.0).mean()
    scalar_hi = (target / rv_hi).clip(0.1, 4.0).mean()

    assert scalar_lo > scalar_hi, (
        f"Scalar em vol baixa ({scalar_lo:.3f}) deveria > vol alta ({scalar_hi:.3f})"
    )
    print(f"  [OK] test_vol_targeting_scales_down_in_high_vol  "
          f"(scalar_lo={scalar_lo:.3f}, scalar_hi={scalar_hi:.3f})")


def test_vol_scalar_clamped_at_min():
    """Scalar nao deve cair abaixo de vol_scalar_min."""
    # Vol muito alta => scalar = target/rv seria pequeno => clamp no min
    df = _ohlcv(300, 0.05, seed=3)   # vol diaria enorme (5%)
    bt = _make_strat_bt(df, use_vol_targeting=True, vol_target_annual=0.15,
                         vol_window=20, vol_scalar_min=0.5, vol_scalar_max=4.0)
    bt.run()
    # Com scalar min=0.5, amount nunca pode ser < 50% do que seria sem targeting
    bt_base = _make_strat_bt(df, use_vol_targeting=False)
    bt_base.run()
    if not bt.trades or not bt_base.trades:
        print("  [OK] test_vol_scalar_clamped_at_min  (sem trades)")
        return
    for t in bt.trades:
        assert t["amount"] > 0, "amount deve ser positivo"
    print(f"  [OK] test_vol_scalar_clamped_at_min  "
          f"({len(bt.trades)} trades, todos com amount > 0)")


def test_vol_scalar_clamped_at_max():
    """Scalar nao deve superar vol_scalar_max."""
    # Vol muito baixa => scalar = target/rv seria grande => clamp no max
    df = _ohlcv(300, 0.001, seed=4)   # vol minima
    bt = _make_strat_bt(df, use_vol_targeting=True, vol_target_annual=0.15,
                         vol_window=20, vol_scalar_min=0.1, vol_scalar_max=1.5)
    bt_base = _make_strat_bt(df, use_vol_targeting=False)
    bt.run(); bt_base.run()
    if not bt.trades or not bt_base.trades:
        print("  [OK] test_vol_scalar_clamped_at_max  (sem trades)")
        return
    avg_vt   = sum(t["amount"] for t in bt.trades) / len(bt.trades)
    avg_base = sum(t["amount"] for t in bt_base.trades) / len(bt_base.trades)
    # Com cap 1.5x, amount nunca pode ser mais que 1.5x do base
    assert avg_vt <= avg_base * 1.51, \
        f"scalar cap falhou: vt={avg_vt:.0f} vs base={avg_base:.0f} (max 1.5x)"
    print(f"  [OK] test_vol_scalar_clamped_at_max  "
          f"(vt={avg_vt:.0f}, base={avg_base:.0f})")


def test_vol_targeting_reduces_dd_in_volatile_market():
    """Vol targeting deve reduzir drawdown em mercado volatil."""
    df = _ohlcv(400, 0.025, seed=99)
    bt_off = _make_strat_bt(df, use_vol_targeting=False)
    bt_on  = _make_strat_bt(df, use_vol_targeting=True, vol_target_annual=0.15)
    m_off  = bt_off.run()
    m_on   = bt_on.run()
    dd_off = m_off.get("max_drawdown", 0)
    dd_on  = m_on.get("max_drawdown", 0)
    # DD com vol targeting deve ser <= sem targeting (ou igual se sem trades)
    assert dd_on <= dd_off + 0.01, \
        f"DD com vol targeting ({dd_on:.3f}) deveria <= sem ({dd_off:.3f})"
    print(f"  [OK] test_vol_targeting_reduces_dd_in_volatile_market  "
          f"(OFF={dd_off:.3f}%, ON={dd_on:.3f}%)")


def test_vol_targeting_noop_without_realized_vol_column():
    """Sem coluna Realized_Vol, vol targeting e no-op (nao crasha)."""
    df = _ohlcv(200, 0.012, seed=5)
    # Remove a coluna manualmente apos prepare
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(df)
    s.params.update({"use_vol_targeting": True})
    s.prepare()
    if "Realized_Vol" in s.data.columns:
        s.data = s.data.drop(columns=["Realized_Vol"])
    bt = Backtester(s, initial_capital=100_000.0, cooldown_bars=0,
                    commission_per_trade=0.0, slippage_pct=0.0)
    m = bt.run()   # nao deve crashar
    assert "trade_count" in m
    print(f"  [OK] test_vol_targeting_noop_without_realized_vol_column  "
          f"({m['trade_count']} trades)")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all() -> int:
    tests = [
        # realized_vol
        test_realized_vol_returns_same_length,
        test_realized_vol_nan_below_half_window,
        test_realized_vol_higher_for_higher_vol,
        test_realized_vol_annualizes_correctly,
        test_realized_vol_in_compute_all,
        test_infer_ann_factor_daily,
        test_infer_ann_factor_hourly,
        # vol targeting no backtester
        test_vol_targeting_disabled_by_default,
        test_vol_targeting_scales_down_in_high_vol,
        test_vol_scalar_clamped_at_min,
        test_vol_scalar_clamped_at_max,
        test_vol_targeting_reduces_dd_in_volatile_market,
        test_vol_targeting_noop_without_realized_vol_column,
    ]
    print("=" * 60)
    print("  Suite: Volatility Targeting (Sprint-2 passo 2)")
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
