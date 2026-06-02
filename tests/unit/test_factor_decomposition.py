# tests/unit/test_factor_decomposition.py — Sprint 20 (E3)
"""Testes determinísticos (sem rede) da decomposição fatorial.

Os testes #1 (identidade) e #2 (alpha conhecido) são a REDE DE SEGURANÇA: provam
que a regressão está matematicamente correta. Se eles passam, confia-se no resto
da inferência estatística. Fixtures usam RNG explícito (CLAUDE.md §2.6).
"""
from __future__ import annotations

import os
import sys
import traceback

import numpy as np
import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.factor_decomposition import (
    build_minimal_system_returns,
    fit_capm_local,
    fit_capm_plus_momentum,
    fit_vs_minimal_system,
    plot_qq,
    plot_regression_scatter,
    plot_residuals,
)

ANN = 252


# ── Fixtures determinísticas ────────────────────────────────────────────────

def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2015-01-01", periods=n, freq="D")


def _returns(seed: int, n: int, mu: float = 0.0, sigma: float = 0.01) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mu, sigma, n), index=_idx(n))


def _synth_ohlcv(seed: int, n: int = 500) -> pd.DataFrame:
    """OHLCV sintético com tendência suave — gera regimes (Hurst/ADX) variados."""
    rng = np.random.default_rng(seed)
    idx = _idx(n)
    ret = rng.normal(0.0004, 0.012, n)
    close = 100.0 * np.exp(np.cumsum(ret))
    intra = np.abs(rng.normal(0.0, 0.006, n))
    high = close * (1 + intra)
    low = close * (1 - intra)
    openp = np.concatenate(([close[0]], close[:-1]))
    return pd.DataFrame({
        "Open": openp,
        "High": np.maximum(high, np.maximum(openp, close)),
        "Low": np.minimum(low, np.minimum(openp, close)),
        "Close": close,
        "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=idx)


# ── #1 — Identidade (REDE DE SEGURANÇA) ─────────────────────────────────────

def test_identity_alpha0_beta1_r2_1():
    """system == market → alpha≈0, beta≈1, R²≈1."""
    mkt = _returns(0, 600)
    r = fit_capm_local(mkt.copy(), mkt)
    assert abs(r["alpha_annualized"]) < 1e-4
    assert abs(r["beta"] - 1.0) < 1e-6
    assert abs(r["r_squared"] - 1.0) < 1e-9
    print("  [OK] test_identity_alpha0_beta1_r2_1")


# ── #2 — Recupera alpha conhecido (REDE DE SEGURANÇA) ───────────────────────

def test_recovers_known_alpha():
    """system = alpha_known + ruído (independente do mercado) → recupera alpha_known."""
    n = 2000
    mkt = _returns(1, n)
    rng = np.random.default_rng(11)
    alpha_daily = 0.0005  # ~12.6% anual
    sys = pd.Series(alpha_daily + rng.normal(0.0, 0.001, n), index=_idx(n))
    r = fit_capm_local(sys, mkt)
    recovered_daily = r["alpha_annualized"] / (ANN * 100.0)
    assert abs(recovered_daily - alpha_daily) < 1e-4
    assert abs(r["beta"]) < 0.1            # sem dependência de mercado
    assert r["significant_alpha"] is True
    print(f"  [OK] test_recovers_known_alpha (alpha_ann={r['alpha_annualized']:.2f}%)")


# ── #3 — Recupera beta conhecido ────────────────────────────────────────────

def test_recovers_known_beta():
    """system = beta_known * market → recupera beta_known, alpha≈0."""
    n = 1000
    mkt = _returns(2, n)
    rng = np.random.default_rng(22)
    beta_known = 0.6
    sys = beta_known * mkt + pd.Series(rng.normal(0.0, 1e-5, n), index=_idx(n))
    r = fit_capm_local(sys, mkt)
    assert abs(r["beta"] - beta_known) < 1e-2
    assert abs(r["alpha_annualized"]) < 1.0
    assert r["r_squared"] > 0.99
    print(f"  [OK] test_recovers_known_beta (beta={r['beta']:.4f})")


# ── #4 — Retornos independentes → R²≈0, alpha não significativo ──────────────

def test_independent_returns_low_r2():
    """system independente do mercado → R²≈0, alpha não significativo."""
    n = 1000
    mkt = _returns(3, n)
    sys = _returns(33, n)  # série independente
    r = fit_capm_local(sys, mkt)
    assert r["r_squared"] < 0.05
    assert r["significant_alpha"] is False
    print(f"  [OK] test_independent_returns_low_r2 (R²={r['r_squared']:.4f})")


# ── #5 — Alpha estatisticamente significativo (1000 obs, 10% anual) ─────────

def test_significant_alpha_1000obs():
    """1000 obs, alpha 10% anual + sinal limpo → alpha_pvalue < 0.01."""
    n = 1000
    mkt = _returns(4, n)
    rng = np.random.default_rng(44)
    alpha_daily = 0.10 / ANN
    sys = pd.Series(alpha_daily + 0.3 * mkt.values + rng.normal(0.0, 0.002, n), index=_idx(n))
    r = fit_capm_local(sys, mkt)
    assert r["alpha_pvalue"] < 0.01
    assert r["significant_alpha"] is True
    print(f"  [OK] test_significant_alpha_1000obs (p={r['alpha_pvalue']:.4g})")


# ── #6 — Alpha não significativo (50 obs, 2% anual) ─────────────────────────

def test_nonsignificant_alpha_smallN():
    """50 obs, alpha 2% anual sob ruído alto → alpha_pvalue > 0.05."""
    n = 50
    mkt = _returns(5, n)
    rng = np.random.default_rng(55)
    alpha_daily = 0.02 / ANN
    sys = pd.Series(alpha_daily + rng.normal(0.0, 0.01, n), index=_idx(n))
    r = fit_capm_local(sys, mkt)
    assert r["alpha_pvalue"] > 0.05
    assert r["significant_alpha"] is False
    print(f"  [OK] test_nonsignificant_alpha_smallN (p={r['alpha_pvalue']:.4g})")


# ── #7 — Fator momentum significativo ───────────────────────────────────────

def test_momentum_factor_significant():
    """system construído para seguir momentum → beta_momentum significativo e positivo."""
    n = 800
    rng = np.random.default_rng(6)
    mkt_ret = pd.Series(rng.normal(0.0004, 0.01, n), index=_idx(n))
    prices = 100.0 * (1 + mkt_ret).cumprod()
    mom = prices.pct_change(252 - 21).shift(21)
    sys = pd.Series(0.5 * mom.fillna(0.0).values + rng.normal(0.0, 0.001, n), index=_idx(n))
    r = fit_capm_plus_momentum(sys, mkt_ret, prices)
    assert r["beta_momentum"] > 0
    assert r["beta_momentum_pvalue"] < 0.05
    assert "vif_market" in r and "vif_momentum" in r
    print(f"  [OK] test_momentum_factor_significant "
          f"(beta_mom={r['beta_momentum']:.3f}, p={r['beta_momentum_pvalue']:.4g})")


# ── #8 — Determinismo ───────────────────────────────────────────────────────

def test_determinism_two_runs_identical():
    """Duas execuções dos Modelos 1 e 2 → dicts idênticos."""
    n = 600
    mkt = _returns(7, n)
    prices = 100.0 * (1 + mkt).cumprod()
    sys = _returns(77, n)
    assert fit_capm_local(sys, mkt) == fit_capm_local(sys, mkt)
    assert fit_capm_plus_momentum(sys, mkt, prices) == fit_capm_plus_momentum(sys, mkt, prices)
    print("  [OK] test_determinism_two_runs_identical")


# ── #9 — Amostra insuficiente → ValueError ──────────────────────────────────

def test_too_few_obs_raises():
    """n_obs < 30 → ValueError explícito."""
    n = 20
    mkt = _returns(8, n)
    sys = _returns(88, n)
    with pytest.raises(ValueError):
        fit_capm_local(sys, mkt)
    print("  [OK] test_too_few_obs_raises")


# ── #10 — Construção do Sistema Mínimo + Modelo 3 determinísticos ────────────

def test_minimal_system_construction_deterministic():
    """Sistema Mínimo (build + fit_vs_minimal) é determinístico e bem-formado."""
    data = _synth_ohlcv(7, 500)
    r1, n1 = build_minimal_system_returns(data)
    r2, n2 = build_minimal_system_returns(data)
    pd.testing.assert_series_equal(r1, r2)
    assert n1 == n2
    assert n1 >= 1   # o fixture ativa o regime em ao menos uma barra

    sys = _returns(70, len(data)).set_axis(data.index)
    d1 = fit_vs_minimal_system(sys, data)
    d2 = fit_vs_minimal_system(sys, data)
    assert d1 == d2
    assert d1["model"] == "vs_minimal_system"
    assert d1["n_obs"] > 30
    assert d1["minimal_n_active_bars"] == n1
    print(f"  [OK] test_minimal_system_construction_deterministic "
          f"(n_active={n1}, n_obs={d1['n_obs']})")


# ── #11 — Sistema Mínimo é anti-lookahead (adição §2.2) ─────────────────────

def test_minimal_signal_no_lookahead():
    """returns_minimal em df[:k] == returns_minimal no df completo nas datas compartilhadas
    (sinal usa Hurst[i-1]/ADX[i-1], features causais via shift(1))."""
    data = _synth_ohlcv(8, 500)
    full, _ = build_minimal_system_returns(data)
    for k in (150, 250, 400):
        partial, _ = build_minimal_system_returns(data.iloc[:k])
        common = partial.index.intersection(full.index)
        assert len(common) > 30
        pd.testing.assert_series_equal(
            partial.loc[common], full.loc[common], check_exact=False, rtol=1e-9, atol=1e-12)
    print("  [OK] test_minimal_signal_no_lookahead")


# ── Smoke test das visualizações (E2) ───────────────────────────────────────

def test_viz_outputs_created():
    """As 3 visualizações geram PNGs legíveis (adição p/ cobertura do código de plotagem)."""
    import tempfile

    n = 300
    mkt = _returns(9, n)
    sys = 0.5 * mkt + _returns(99, n) * 0.5
    import statsmodels.api as sm
    res = sm.OLS(np.asarray(sys, float), sm.add_constant(np.asarray(mkt, float))).fit()
    with tempfile.TemporaryDirectory() as d:
        p1 = plot_regression_scatter(mkt, sys, os.path.join(d, "scatter.png"), title="t")
        p2 = plot_residuals(res.fittedvalues, res.resid, os.path.join(d, "resid.png"))
        p3 = plot_qq(res.resid, os.path.join(d, "qq.png"))
        for p in (p1, p2, p3):
            assert os.path.exists(p) and os.path.getsize(p) > 0
    print("  [OK] test_viz_outputs_created")


# ── Runner standalone ───────────────────────────────────────────────────────

_TESTS = [
    test_identity_alpha0_beta1_r2_1,
    test_recovers_known_alpha,
    test_recovers_known_beta,
    test_independent_returns_low_r2,
    test_significant_alpha_1000obs,
    test_nonsignificant_alpha_smallN,
    test_momentum_factor_significant,
    test_determinism_two_runs_identical,
    test_too_few_obs_raises,
    test_minimal_system_construction_deterministic,
    test_minimal_signal_no_lookahead,
    test_viz_outputs_created,
]


def run_all() -> bool:
    passed = failed = 0
    print(f"\n{'='*60}")
    print("  Suite: factor_decomposition — decomposição fatorial (Sprint 20)")
    print(f"{'='*60}")
    for fn in _TESTS:
        try:
            fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"  [FAIL] {fn.__name__}")
            traceback.print_exc()
    print(f"{'='*60}")
    print(f"  Resultado: {passed} passou(aram) / {failed} falhou(aram)")
    print(f"{'='*60}\n")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
