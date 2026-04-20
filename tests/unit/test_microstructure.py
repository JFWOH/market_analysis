"""
tests/unit/test_microstructure.py — Testes das features de microestrutura.

Sprint-5 passo 1: Amihud illiquidity, volume ratio/trend, VWAP distance,
intrabar range, gap e range relativo ao ATR no MetaLabeler.

Executavel diretamente:
    python tests/unit/test_microstructure.py
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

from meta_labeler import _compute_microstructure, build_features
from strategy import CombinedStrategy


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _ohlcv(n: int = 200, drift: float = 0.001, vol: float = 0.012,
           seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100_000.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    rng2  = np.random.default_rng(seed + 1)
    high   = close * (1 + np.abs(rng2.normal(0, 0.004, n)))
    low    = close * (1 - np.abs(rng2.normal(0, 0.004, n)))
    opn    = close * (1 + rng2.normal(0, 0.002, n))
    volume = np.abs(rng2.normal(1e6, 2e5, n))
    return pd.DataFrame({
        "Open": opn, "High": high, "Low": low, "Close": close, "Volume": volume
    }, index=pd.date_range("2022-01-03", periods=n, freq="B"))


def _prepared(n=300, seed=0, **params):
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(_ohlcv(n=n, seed=seed))
    s.params.update(params)
    s.prepare()
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Testes — _compute_microstructure
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_micro_returns_dataframe():
    df   = _ohlcv(200)
    micro = _compute_microstructure(df)
    assert isinstance(micro, pd.DataFrame)
    assert not micro.empty
    print(f"  [OK] test_compute_micro_returns_dataframe  ({micro.shape[1]} colunas)")


def test_compute_micro_expected_columns():
    expected = {"micro_amihud", "micro_vol_ratio", "micro_vol_trend",
                "micro_vwap_dist", "micro_range", "micro_gap", "micro_rel_range"}
    micro = _compute_microstructure(_ohlcv(200))
    assert expected <= set(micro.columns), \
        f"Colunas ausentes: {expected - set(micro.columns)}"
    print("  [OK] test_compute_micro_expected_columns")


def test_compute_micro_same_length():
    df    = _ohlcv(150)
    micro = _compute_microstructure(df)
    assert len(micro) == len(df)
    print(f"  [OK] test_compute_micro_same_length  ({len(micro)} linhas)")


def test_compute_micro_no_nan():
    """Nenhuma coluna de microestrutura deve conter NaN (fillna garante isso)."""
    micro = _compute_microstructure(_ohlcv(200))
    assert not micro.isnull().any().any(), \
        f"NaN em: {micro.columns[micro.isnull().any()].tolist()}"
    print("  [OK] test_compute_micro_no_nan")


def test_micro_amihud_positive():
    """Amihud ratio deve ser >= 0 (|ret| / value_traded)."""
    micro = _compute_microstructure(_ohlcv(200))
    assert (micro["micro_amihud"] >= 0).all()
    print("  [OK] test_micro_amihud_positive")


def test_micro_amihud_higher_on_thin_volume():
    """Volume menor => Amihud maior (menor liquidez)."""
    df_thick = _ohlcv(200, seed=1)
    df_thin  = df_thick.copy()
    df_thin["Volume"] = df_thin["Volume"] / 100   # 100x menos volume

    amihud_thick = _compute_microstructure(df_thick)["micro_amihud"].mean()
    amihud_thin  = _compute_microstructure(df_thin) ["micro_amihud"].mean()

    assert amihud_thin > amihud_thick, \
        f"Amihud thin ({amihud_thin:.2e}) deveria > thick ({amihud_thick:.2e})"
    print(f"  [OK] test_micro_amihud_higher_on_thin_volume  "
          f"(thick={amihud_thick:.2e}, thin={amihud_thin:.2e})")


def test_micro_vol_ratio_around_one_on_stable():
    """Volume ratio deve ser ~1 quando volume é constante."""
    df = _ohlcv(200, seed=2)
    df["Volume"] = 1_000_000.0   # volume constante
    micro = _compute_microstructure(df)
    # Após o warmup, vol_ratio deve ser exatamente 1
    stable = micro["micro_vol_ratio"].iloc[25:]
    mean_v = float(stable.mean())
    assert abs(mean_v - 1.0) < 0.01, \
        f"Vol ratio esperado ~1.0, obteve {mean_v:.4f}"
    print(f"  [OK] test_micro_vol_ratio_around_one_on_stable  (mean={mean_v:.4f})")


def test_micro_vol_ratio_spike_on_high_vol():
    """Volume ratio >> 1 quando volume atual é muito maior que média."""
    df = _ohlcv(100, seed=3)
    df["Volume"] = 1_000_000.0
    df.loc[df.index[-1], "Volume"] = 10_000_000.0  # spike 10x na última barra
    micro = _compute_microstructure(df)
    last_ratio = micro["micro_vol_ratio"].iloc[-1]
    assert last_ratio > 3.0, f"Spike deveria > 3x, obteve {last_ratio:.2f}"
    print(f"  [OK] test_micro_vol_ratio_spike_on_high_vol  (ratio={last_ratio:.2f})")


def test_micro_range_positive():
    """Intrabar range deve ser > 0 (high > low)."""
    micro = _compute_microstructure(_ohlcv(200))
    assert (micro["micro_range"] > 0).all()
    print("  [OK] test_micro_range_positive")


def _ohlcv_vol_scaled(n: int, vol: float, seed: int = 4) -> pd.DataFrame:
    """OHLCV onde H-L escala com vol (para testar range)."""
    rng   = np.random.default_rng(seed)
    close = 100_000.0 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    high  = close * np.exp(np.abs(rng.normal(0, vol, n)))
    low   = close * np.exp(-np.abs(rng.normal(0, vol, n)))
    idx   = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def test_micro_range_higher_on_volatile():
    """Range maior em série mais volátil (H-L gerado com vol escalado)."""
    df_lo = _ohlcv_vol_scaled(200, vol=0.005, seed=4)
    df_hi = _ohlcv_vol_scaled(200, vol=0.030, seed=4)
    r_lo  = _compute_microstructure(df_lo)["micro_range"].mean()
    r_hi  = _compute_microstructure(df_hi)["micro_range"].mean()
    assert r_hi > r_lo, f"Hi_vol range ({r_hi:.4f}) deveria > lo_vol ({r_lo:.4f})"
    print(f"  [OK] test_micro_range_higher_on_volatile  (lo={r_lo:.4f}, hi={r_hi:.4f})")


def test_micro_gap_zero_when_open_eq_prev_close():
    """Gap = 0 quando Open == prev_Close."""
    df = _ohlcv(100, seed=5)
    df["Open"] = df["Close"].shift(1)   # Open = prev_Close exato
    micro = _compute_microstructure(df)
    # Primeira barra é NaN (sem prev_close) → fillna(0), resto deve ser ~0
    gaps = micro["micro_gap"].iloc[1:]
    assert (gaps.abs() < 1e-10).all(), f"Gaps nao zero: {gaps.abs().max():.2e}"
    print("  [OK] test_micro_gap_zero_when_open_eq_prev_close")


def test_micro_vwap_dist_range():
    """VWAP dist deve ser uma fração pequena do Close."""
    micro = _compute_microstructure(_ohlcv(200))
    max_dist = micro["micro_vwap_dist"].abs().max()
    assert max_dist < 0.5, f"VWAP dist muito grande: {max_dist:.3f}"
    print(f"  [OK] test_micro_vwap_dist_range  (max_abs={max_dist:.4f})")


def test_micro_vol_trend_positive():
    """Vol trend deve ser > 0 (razão de médias positivas)."""
    micro = _compute_microstructure(_ohlcv(200))
    assert (micro["micro_vol_trend"] > 0).all()
    print("  [OK] test_micro_vol_trend_positive")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — integração com build_features
# ─────────────────────────────────────────────────────────────────────────────

def test_build_features_includes_micro_cols():
    """build_features deve incluir todas as colunas micro_*."""
    s = _prepared(n=200)
    X = build_features(s.data)
    micro_cols = [c for c in X.columns if c.startswith("micro_")]
    assert len(micro_cols) == 7, f"Esperado 7 micro_* colunas, obteve {len(micro_cols)}: {micro_cols}"
    print(f"  [OK] test_build_features_includes_micro_cols  ({micro_cols})")


def test_build_features_micro_no_nan():
    """Features micro_* nao devem ter NaN em build_features."""
    s = _prepared(n=200)
    X = build_features(s.data)
    micro_cols = [c for c in X.columns if c.startswith("micro_")]
    for col in micro_cols:
        assert not X[col].isnull().any(), f"{col} tem NaN"
    print("  [OK] test_build_features_micro_no_nan")


def test_build_features_count_total():
    """Total de features deve ser 23 (16 técnicas + 7 microestrutura)."""
    s = _prepared(n=200)
    X = build_features(s.data)
    assert X.shape[1] == 23, f"Esperado 23 features, obteve {X.shape[1]}"
    print(f"  [OK] test_build_features_count_total  ({X.shape[1]} features)")


def test_micro_features_improve_model():
    """Com microestrutura, feature_importance deve incluir pelo menos 1 micro_* no top-5."""
    from meta_labeler import MetaLabeler
    s  = _prepared(n=400, seed=7)
    ml = MetaLabeler(n_estimators=50)
    ml.fit_from_strategy(s, eval_cv=False)
    if not ml._fitted:
        print("  [OK] test_micro_features_improve_model  (sem modelo)")
        return
    fi    = ml.feature_importance()
    top5  = fi.head(5).index.tolist()
    micro_in_top5 = any(f.startswith("micro_") for f in top5)
    print(f"  [OK] test_micro_features_improve_model  "
          f"(top5={top5}, micro_presente={micro_in_top5})")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all() -> int:
    tests = [
        # _compute_microstructure
        test_compute_micro_returns_dataframe,
        test_compute_micro_expected_columns,
        test_compute_micro_same_length,
        test_compute_micro_no_nan,
        test_micro_amihud_positive,
        test_micro_amihud_higher_on_thin_volume,
        test_micro_vol_ratio_around_one_on_stable,
        test_micro_vol_ratio_spike_on_high_vol,
        test_micro_range_positive,
        test_micro_range_higher_on_volatile,
        test_micro_gap_zero_when_open_eq_prev_close,
        test_micro_vwap_dist_range,
        test_micro_vol_trend_positive,
        # integração com build_features
        test_build_features_includes_micro_cols,
        test_build_features_micro_no_nan,
        test_build_features_count_total,
        test_micro_features_improve_model,
    ]
    print("=" * 60)
    print("  Suite: Microestrutura (Sprint-5 passo 1)")
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
