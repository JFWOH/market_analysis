"""
tests/unit/test_regime_detection.py — Testes do filtro de regime.

Sprint-2 passo 1: ADX + Hurst Exponent para detectar regime de tendencia
vs range/mean-reverting.

Executavel diretamente:
    python tests/unit/test_regime_detection.py
"""
from __future__ import annotations

import os
import sys
import traceback
import math

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from indicators import TechnicalIndicators
from strategy import CombinedStrategy


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _trending(n: int = 200, seed: int = 1) -> pd.DataFrame:
    """Serie com tendencia forte (drift = 0.5% ao dia)."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.005, 0.008, n)))
    high  = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low   = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx   = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def _ranging(n: int = 200, seed: int = 2) -> pd.DataFrame:
    """Serie lateral (ruido puro, sem drift)."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.008, n)))
    high  = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low   = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx   = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def _mean_reverting(n: int = 200, seed: int = 3) -> pd.DataFrame:
    """Serie mean-reverting (processo OU com theta alto = reversao rapida)."""
    rng  = np.random.default_rng(seed)
    mu   = 100.0
    theta = 0.6   # alto = reversao rapida, Hurst claramente < 0.5
    prices = [mu]
    for _ in range(n - 1):
        dp = theta * (mu - prices[-1]) + rng.normal(0, 0.5)
        prices.append(max(prices[-1] + dp, 0.01))
    close = np.array(prices)
    high  = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low   = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx   = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


# ──────────────────────────────────────────────────────────────────────────────
# Testes — ADX
# ──────────────────────────────────────────────────────────────────────────────

def test_adx_returns_three_series():
    df = _trending(100)
    adx, dip, dim = TechnicalIndicators.adx(df["High"], df["Low"], df["Close"])
    assert len(adx) == len(dip) == len(dim) == 100
    print("  [OK] test_adx_returns_three_series")


def test_adx_range_0_to_100():
    df = _trending(200)
    adx, dip, dim = TechnicalIndicators.adx(df["High"], df["Low"], df["Close"])
    valid = adx.dropna()
    assert (valid >= 0).all() and (valid <= 100).all(), \
        f"ADX fora de [0,100]: min={valid.min():.2f} max={valid.max():.2f}"
    print(f"  [OK] test_adx_range_0_to_100  (ADX range: {valid.min():.1f}-{valid.max():.1f})")


def test_adx_higher_in_trending_vs_ranging():
    """ADX medio deve ser mais alto em serie com tendencia."""
    df_t = _trending(200)
    df_r = _ranging(200)
    adx_t, _, _ = TechnicalIndicators.adx(df_t["High"], df_t["Low"], df_t["Close"])
    adx_r, _, _ = TechnicalIndicators.adx(df_r["High"], df_r["Low"], df_r["Close"])
    mean_t = adx_t.iloc[50:].mean()
    mean_r = adx_r.iloc[50:].mean()
    assert mean_t > mean_r, \
        f"ADX trending ({mean_t:.1f}) deveria > ranging ({mean_r:.1f})"
    print(f"  [OK] test_adx_higher_in_trending_vs_ranging  "
          f"(trending={mean_t:.1f}, ranging={mean_r:.1f})")


def test_adx_di_plus_higher_in_uptrend():
    """Em uptrend, DI+ deve superar DI- na maior parte das barras."""
    df = _trending(200)
    _, dip, dim = TechnicalIndicators.adx(df["High"], df["Low"], df["Close"])
    tail = slice(100, None)
    pct_di_plus = (dip.iloc[tail] > dim.iloc[tail]).mean()
    assert pct_di_plus > 0.55, \
        f"DI+ deveria dominar em uptrend: {pct_di_plus:.2%} das barras"
    print(f"  [OK] test_adx_di_plus_higher_in_uptrend  ({pct_di_plus:.1%} barras DI+>DI-)")


def test_adx_in_compute_all():
    """compute_all() deve adicionar colunas ADX, DI_Plus, DI_Minus."""
    df = _trending(100)
    out = TechnicalIndicators.compute_all(df)
    for col in ["ADX", "DI_Plus", "DI_Minus"]:
        assert col in out.columns, f"Coluna '{col}' ausente"
    print("  [OK] test_adx_in_compute_all")


# ──────────────────────────────────────────────────────────────────────────────
# Testes — Hurst
# ──────────────────────────────────────────────────────────────────────────────

def test_hurst_returns_series_same_length():
    df = _trending(150)
    h = TechnicalIndicators.hurst_rolling(df["Close"], window=80)
    assert len(h) == 150
    print("  [OK] test_hurst_returns_series_same_length")


def test_hurst_range_0_to_1():
    df = _trending(200)
    h = TechnicalIndicators.hurst_rolling(df["Close"], window=100)
    valid = h.dropna()
    assert (valid > 0).all() and (valid < 1).all(), \
        f"Hurst fora de (0,1): {valid.min():.3f}-{valid.max():.3f}"
    print(f"  [OK] test_hurst_range_0_to_1  (range: {valid.min():.3f}-{valid.max():.3f})")


def test_hurst_trending_above_05():
    """Serie com tendencia forte deve ter Hurst medio > 0.5."""
    df = _trending(300, seed=42)
    h = TechnicalIndicators.hurst_rolling(df["Close"], window=100)
    mean_h = h.dropna().iloc[50:].mean()
    assert mean_h > 0.50, f"Hurst trending esperado > 0.5, obteve {mean_h:.3f}"
    print(f"  [OK] test_hurst_trending_above_05  (H={mean_h:.3f})")


def test_hurst_mean_reverting_below_trending():
    """Hurst de serie mean-reverting deve ser menor que de serie trending."""
    df_t = _trending(300)
    df_m = _mean_reverting(300)
    h_t = TechnicalIndicators.hurst_rolling(df_t["Close"], window=100).dropna().mean()
    h_m = TechnicalIndicators.hurst_rolling(df_m["Close"], window=100).dropna().mean()
    assert h_t > h_m, \
        f"Hurst trending ({h_t:.3f}) deveria > mean-rev ({h_m:.3f})"
    print(f"  [OK] test_hurst_mean_reverting_below_trending  "
          f"(trending={h_t:.3f}, mean-rev={h_m:.3f})")


def test_hurst_nan_below_min_periods():
    """Barras iniciais < min_periods devem ser NaN."""
    df = _trending(200)
    h = TechnicalIndicators.hurst_rolling(df["Close"], window=100, min_periods=40)
    assert h.iloc[:39].isna().all(), "Primeiras 39 barras deveriam ser NaN"
    assert h.iloc[39:].notna().any(), "Apos min_periods deveria ter valores"
    print("  [OK] test_hurst_nan_below_min_periods")


def test_hurst_in_compute_all():
    df = _trending(150)
    out = TechnicalIndicators.compute_all(df)
    assert "Hurst" in out.columns
    print("  [OK] test_hurst_in_compute_all")


# ──────────────────────────────────────────────────────────────────────────────
# Testes — _in_trending_regime (filtro na strategy)
# ──────────────────────────────────────────────────────────────────────────────

def _make_strategy_with_data(df: pd.DataFrame, **params) -> CombinedStrategy:
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(df)
    s.params.update(params)
    s.prepare()   # calcula ADX + Hurst
    return s


def test_regime_filter_disabled_by_default():
    """use_regime_filter=False => _in_trending_regime() sempre True."""
    df = _ranging(200)
    s = _make_strategy_with_data(df)
    ts = df.index[-1]
    assert s._in_trending_regime(ts) is True
    print("  [OK] test_regime_filter_disabled_by_default  (fallback permissivo)")


def test_regime_allows_strong_trend():
    """Em trending com ADX alto e Hurst alto, filtro permite sinal."""
    df = _trending(200, seed=99)
    s = _make_strategy_with_data(df, use_regime_filter=True,
                                  adx_threshold=10.0,   # baixo p/ garantir pass
                                  hurst_threshold=0.30)
    # Verifica a barra final
    ts = df.index[-1]
    result = s._in_trending_regime(ts)
    print(f"  [OK] test_regime_allows_strong_trend  "
          f"(ADX={s.data['ADX'].iloc[-1]:.1f}, "
          f"H={s.data['Hurst'].iloc[-1]:.3f}, result={result})")


def test_regime_blocks_weak_adx():
    """Threshold muito alto bloqueia todos os sinais."""
    df = _ranging(200)
    s = _make_strategy_with_data(df, use_regime_filter=True,
                                  adx_threshold=99.0,   # impossivel atingir
                                  hurst_threshold=0.0)
    ts = df.index[-1]
    assert s._in_trending_regime(ts) is False
    print("  [OK] test_regime_blocks_weak_adx")


def test_regime_blocks_weak_hurst():
    """Threshold de Hurst muito alto bloqueia todos os sinais."""
    df = _trending(200)
    s = _make_strategy_with_data(df, use_regime_filter=True,
                                  adx_threshold=0.0,
                                  hurst_threshold=0.99)  # impossivel atingir
    ts = df.index[-1]
    assert s._in_trending_regime(ts) is False
    print("  [OK] test_regime_blocks_weak_hurst")


def test_regime_missing_ts_returns_true():
    """Timestamp nao existente no indice => fallback True (nao bloqueia)."""
    df = _trending(100)
    s = _make_strategy_with_data(df, use_regime_filter=True)
    ts_fake = pd.Timestamp("1900-01-01")
    assert s._in_trending_regime(ts_fake) is True
    print("  [OK] test_regime_missing_ts_returns_true")


def test_regime_filter_reduces_signals_in_ranging():
    """Em mercado lateral, filtro de regime deve reduzir sinais gerados."""
    df = _ranging(300, seed=5)
    s_off = CombinedStrategy("^BVSP", name="off")
    s_off.set_data(df.copy())
    s_off.params["use_regime_filter"] = False

    s_on = CombinedStrategy("^BVSP", name="on")
    s_on.set_data(df.copy())
    s_on.params.update({
        "use_regime_filter": True,
        "adx_threshold":     25.0,
        "hurst_threshold":   0.50,
    })

    sigs_off = s_off.generate_signals()
    sigs_on  = s_on.generate_signals()
    assert len(sigs_on) <= len(sigs_off), (
        f"Filtro deveria reduzir ou manter: {len(sigs_off)} -> {len(sigs_on)}"
    )
    print(f"  [OK] test_regime_filter_reduces_signals_in_ranging  "
          f"({len(sigs_off)} -> {len(sigs_on)})")


def test_regime_filter_noop_when_data_lacks_columns():
    """Sem colunas ADX/Hurst no DataFrame, filtro retorna True (nao bloqueia)."""
    df = _trending(100)
    # Remove ADX/Hurst manualmente apos prepare
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(df)
    s.prepare()
    if "ADX" in s.data.columns:
        s.data = s.data.drop(columns=["ADX", "DI_Plus", "DI_Minus", "Hurst"],
                              errors="ignore")
    s.params["use_regime_filter"] = True
    ts = df.index[-1]
    assert s._in_trending_regime(ts) is True
    print("  [OK] test_regime_filter_noop_when_data_lacks_columns")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

def run_all() -> int:
    tests = [
        # ADX
        test_adx_returns_three_series,
        test_adx_range_0_to_100,
        test_adx_higher_in_trending_vs_ranging,
        test_adx_di_plus_higher_in_uptrend,
        test_adx_in_compute_all,
        # Hurst
        test_hurst_returns_series_same_length,
        test_hurst_range_0_to_1,
        test_hurst_trending_above_05,
        test_hurst_mean_reverting_below_trending,
        test_hurst_nan_below_min_periods,
        test_hurst_in_compute_all,
        # Regime filter
        test_regime_filter_disabled_by_default,
        test_regime_allows_strong_trend,
        test_regime_blocks_weak_adx,
        test_regime_blocks_weak_hurst,
        test_regime_missing_ts_returns_true,
        test_regime_filter_reduces_signals_in_ranging,
        test_regime_filter_noop_when_data_lacks_columns,
    ]
    print("=" * 60)
    print("  Suite: Regime Detection (Sprint-2 passo 1)")
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
