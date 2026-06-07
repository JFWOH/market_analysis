# tests/unit/test_walkforward_honest.py — Sprint 21 (E4)
"""Testes determinísticos (sem rede) do walk-forward honesto.

Os testes #1 (AR(1)/sinal real → degradação≈0) e #2 (ruído puro → degradação alta) são a
REDE DE SEGURANÇA METODOLÓGICA: provam que o walk-forward MEDE overfitting de verdade
(distingue sinal de ruído), não artefato. Usam o *seam* ``evaluator`` para modelar os dois
regimes de forma determinística. O caminho real (``_eval_combo``) é coberto por um smoke
test com OHLCV sintético. Fixtures usam ``np.random.default_rng(seed)`` (CLAUDE.md §2.6).
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

from backtester import Backtester
from walkforward_honest import (
    ANNUALIZATION,
    WalkForwardFold,
    _param_key,
    _selection_metric,
    compute_degradation,
    generate_folds,
    optimize_window,
    param_stability_score,
    walk_forward_with_reopt,
)

# ── Fixtures / helpers ──────────────────────────────────────────────────────

def _idx_df(n: int) -> pd.DataFrame:
    """DataFrame com DatetimeIndex (conteúdo irrelevante p/ evaluator mockado)."""
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": np.linspace(100.0, 200.0, n)}, index=idx)


def _synth_ohlcv(seed: int, n: int = 160) -> pd.DataFrame:
    """OHLCV sintético determinístico (p/ o caminho real via _eval_combo)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    ret = rng.normal(0.0005, 0.012, n)
    close = 100.0 * np.exp(np.cumsum(ret))
    intra = np.abs(rng.normal(0.0, 0.006, n))
    high = close * (1 + intra)
    low = close * (1 - intra)
    openp = np.concatenate(([close[0]], close[:-1]))
    return pd.DataFrame({
        "Open": openp, "High": np.maximum(high, np.maximum(openp, close)),
        "Low": np.minimum(low, np.minimum(openp, close)), "Close": close,
        "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=idx)


def _fake_metrics(sharpe: float, n_obs: int = 300, pf: float = 1.5,
                  trades: int = 20, ret: float = 0.1) -> dict:
    """Métricas sintéticas com os campos que o módulo consome (inclui DSR inputs)."""
    return {
        "sharpe_ratio": sharpe,
        "sharpe_per_period": sharpe / np.sqrt(ANNUALIZATION),
        "n_return_obs": n_obs, "return_skew": 0.0, "return_kurt": 3.0,
        "profit_factor": pf, "trade_count": trades, "return_pct": ret,
        "max_drawdown": 5.0, "win_rate": 0.55,
    }


def _wseed(d: pd.DataFrame, val: float) -> int:
    """Seed determinístico por (janela, valor de param) — independente entre IS e OOS."""
    a = int(d.index[0].value) & 0xFFFFFFFF
    b = int(d.index[-1].value) & 0xFFFFFFFF
    c = round(val * 1000)
    return (a ^ (b * 2654435761) ^ (c * 40503)) & 0xFFFFFFFF


def _mkfold(fid: int, topk: list[dict]) -> WalkForwardFold:
    t = pd.Timestamp("2020-01-01")
    return WalkForwardFold(fid, t, t, t, t, best_params=topk[0],
                           is_metrics={}, oos_metrics={}, top_k_params=topk)


_SMALL_WIN = {"is_window_bars": 40, "oos_window_bars": 20, "embargo_bars": 5}


# ── #1 ⭐ REDE DE SEGURANÇA — sinal real → degradação ≈ 0 ────────────────────

def test_ar1_meanreverting_low_degradation():
    """Sinal estável (ótimo em adx=25, idêntico IS/OOS) → degradação≈0, stability=1.0."""
    data = _idx_df(200)
    space = {"adx_threshold": [20.0, 25.0, 30.0]}

    def stable_eval(d, params, ticker, base, cap):
        return _fake_metrics(2.0 - 0.2 * abs(params["adx_threshold"] - 25.0))

    res = walk_forward_with_reopt(
        data, space, n_folds=3, optimizer="grid",
        metric_to_optimize="sharpe_dsr", evaluator=stable_eval, **_SMALL_WIN)

    assert all(f.best_params["adx_threshold"] == 25.0 for f in res.folds)
    assert abs(res.degradation_pct) < 1.0
    assert res.param_stability_score == 1.0
    deg = compute_degradation(res.is_sharpe_mean, res.oos_sharpe_mean)
    assert deg["interpretation"] == "robusto"
    assert deg["is_significant"] is False
    print(f"  [OK] test_ar1_meanreverting_low_degradation (deg={res.degradation_pct:.3f}%)")


# ── #2 ⭐ REDE DE SEGURANÇA — ruído puro → degradação alta ───────────────────

def test_pure_random_high_degradation():
    """Ruído puro: IS seleciona o maior acaso, OOS é sorteio independente → degradação alta."""
    data = _idx_df(400)
    space = {"adx_threshold": [10.0, 15.0, 20.0, 25.0, 30.0]}

    def noise_eval(d, params, ticker, base, cap):
        rng = np.random.default_rng(_wseed(d, params["adx_threshold"]))
        return _fake_metrics(float(rng.normal(0.0, 1.0)), pf=1.0)

    res = walk_forward_with_reopt(
        data, space, n_folds=4, optimizer="grid",
        metric_to_optimize="sharpe", evaluator=noise_eval, **_SMALL_WIN)

    assert res.is_sharpe_mean > 0          # IS-best (máx de sorteios) é positivo
    assert res.degradation_pct < -20.0     # OOS bem pior (rel = (oos-is)/is*100)
    deg = compute_degradation(res.is_sharpe_mean, res.oos_sharpe_mean)
    assert deg["is_significant"] is True
    assert deg["interpretation"] != "robusto"
    assert res.param_stability_score < 1.0
    print(f"  [OK] test_pure_random_high_degradation "
          f"(IS={res.is_sharpe_mean:.3f}, OOS={res.oos_sharpe_mean:.3f}, "
          f"deg={res.degradation_pct:.1f}%)")


# ── #3 — embargo respeitado ──────────────────────────────────────────────────

def test_embargo_respected():
    """OOS começa em is_end+embargo: nenhuma barra OOS dentro de IS+embargo."""
    folds = generate_folds(2000, n_folds=5, is_window_bars=504,
                           oos_window_bars=252, embargo_bars=20, anchored=True)
    for _is_s, is_e, oos_s, oos_e in folds:
        assert oos_s - is_e == 20
        assert oos_s >= is_e + 20
        assert oos_s < oos_e
    print("  [OK] test_embargo_respected")


# ── #4 — anchored mantém is_start fixo; sliding desliza ──────────────────────

def test_anchored_keeps_is_start_fixed():
    """anchored=True → is_start=0 em todos; is_end expande. sliding → is_start desliza."""
    anc = generate_folds(2000, 5, 504, 252, 20, anchored=True)
    assert all(f[0] == 0 for f in anc)
    assert anc[0][1] < anc[1][1] < anc[2][1]      # IS expande
    sli = generate_folds(2000, 5, 504, 252, 20, anchored=False)
    assert sli[0][0] == 0 and sli[1][0] == 252     # IS desliza por oos_window
    print("  [OK] test_anchored_keeps_is_start_fixed")


# ── #5 — grid pequeno varrido exaustivamente ─────────────────────────────────

def test_small_grid_exhaustive():
    """Grid de 4 combos → 4 avaliações distintas; top_k retorna os 4."""
    data = _idx_df(120)
    space = {"adx_threshold": [20.0, 25.0], "atr_stop_multiplier": [1.0, 2.0]}
    calls: list = []

    def counting_eval(d, params, ticker, base, cap):
        calls.append(_param_key(params))
        return _fake_metrics(1.0 + params["adx_threshold"] * 0.001)

    best, m, topk = optimize_window(
        data, space, optimizer="grid", metric_to_optimize="sharpe",
        evaluator=counting_eval, top_k=4)
    assert len(set(calls)) == 4
    assert len(topk) == 4
    assert isinstance(best, dict) and "sharpe_ratio" in m
    print(f"  [OK] test_small_grid_exhaustive ({len(set(calls))} combos)")


# ── #6 — determinismo (mesma seed → resultado idêntico) — caminho Optuna ─────

def test_determinism_same_seed():
    """Optuna com mesma seed → WalkForwardResult idêntico (cobre o caminho Optuna)."""
    data = _idx_df(300)
    space = {"adx_threshold": [20.0, 25.0, 30.0], "atr_stop_multiplier": [1.0, 1.5, 2.0]}

    def eval_fn(d, params, ticker, base, cap):
        s = 2.0 - 0.1 * abs(params["adx_threshold"] - 25.0) \
            - 0.1 * abs(params["atr_stop_multiplier"] - 1.5)
        return _fake_metrics(s)

    kw = {"n_folds": 3, "optimizer": "optuna", "n_trials_optuna": 12,
          "metric_to_optimize": "sharpe", "evaluator": eval_fn, "seed": 123, **_SMALL_WIN}
    r1 = walk_forward_with_reopt(data, space, **kw)
    r2 = walk_forward_with_reopt(data, space, **kw)
    assert r1.to_dict() == r2.to_dict()
    print("  [OK] test_determinism_same_seed")


# ── #7 — dados insuficientes → ValueError ────────────────────────────────────

def test_insufficient_data_raises():
    """n_bars insuficiente para n_folds → ValueError (em generate_folds e no WF)."""
    with pytest.raises(ValueError):
        generate_folds(100, n_folds=5, is_window_bars=504,
                       oos_window_bars=252, embargo_bars=20)
    data = _idx_df(80)
    with pytest.raises(ValueError):
        walk_forward_with_reopt(
            data, {"adx_threshold": [25.0]}, n_folds=5, is_window_bars=504,
            oos_window_bars=252, embargo_bars=20,
            evaluator=lambda *a, **k: _fake_metrics(1.0))
    print("  [OK] test_insufficient_data_raises")


# ── #8 — stability = 1.0 quando top-K idêntico ───────────────────────────────

def test_stability_score_1_when_same_best():
    """Todos os folds com mesmo top-K → Jaccard médio = 1.0."""
    topk = [{"a": 1}, {"a": 2}]
    folds = [_mkfold(i, [dict(p) for p in topk]) for i in range(3)]
    assert param_stability_score(folds, top_k=2) == 1.0
    print("  [OK] test_stability_score_1_when_same_best")


# ── #9 — stability = 0.0 quando top-K disjunto ───────────────────────────────

def test_stability_score_0_when_disjoint():
    """Folds com top-K disjuntos → Jaccard médio = 0.0."""
    f0 = _mkfold(0, [{"a": 1}])
    f1 = _mkfold(1, [{"a": 2}])
    assert param_stability_score([f0, f1], top_k=1) == 0.0
    print("  [OK] test_stability_score_0_when_disjoint")


# ── #10 — DSR penaliza múltiplas hipóteses ───────────────────────────────────

def test_dsr_penalizes_many_trials():
    """Mais trials → DSR menor (deflação de múltiplos testes), via Backtester e _selection_metric."""
    common = {"sharpe_obs": 0.15, "n_obs": 300, "skew": 0.0, "kurt": 3.0}
    dsr_few = Backtester.deflated_sharpe_ratio(n_trials=1, **common)
    dsr_many = Backtester.deflated_sharpe_ratio(n_trials=1000, **common)
    assert dsr_many < dsr_few
    m = _fake_metrics(2.0)
    assert _selection_metric(m, "sharpe_dsr", 1000) < _selection_metric(m, "sharpe_dsr", 1)
    print(f"  [OK] test_dsr_penalizes_many_trials (DSR: {dsr_few:.4f} -> {dsr_many:.4f})")


# ── Extras de cobertura (não contam como E4) ─────────────────────────────────

def test_compute_degradation_bands():
    """Mapeia as 4 faixas de interpretação + caveat is_nao_positivo."""
    assert compute_degradation(2.0, 1.9)["interpretation"] == "robusto"          # 5%
    assert compute_degradation(2.0, 1.4)["interpretation"] == "moderado overfitting"   # 30%
    assert compute_degradation(2.0, 0.8)["interpretation"] == "severo overfitting"     # 60%
    assert compute_degradation(2.0, 0.1)["interpretation"] == \
        "estrategia essencialmente artefato de fitting"                          # 95%
    assert compute_degradation(-0.5, -0.2)["interpretation"] == "is_nao_positivo"
    d = compute_degradation(2.0, 1.0)
    assert abs(d["absolute_degradation"] - (-1.0)) < 1e-9
    assert abs(d["relative_degradation_pct"] - (-50.0)) < 1e-9
    print("  [OK] test_compute_degradation_bands")


def test_to_dataframe_and_dict_smoke():
    """to_dataframe (1 linha/fold) e to_dict (serializável) bem-formados."""
    data = _idx_df(200)
    res = walk_forward_with_reopt(
        data, {"adx_threshold": [20.0, 25.0]}, n_folds=3, optimizer="grid",
        metric_to_optimize="sharpe",
        evaluator=lambda d, p, t, b, c: _fake_metrics(1.5), **_SMALL_WIN)
    df = res.to_dataframe()
    assert len(df) == 3 and "oos_sharpe" in df.columns
    d = res.to_dict()
    import json
    json.dumps(d)   # não levanta → serializável
    assert d["n_folds"] == 3
    print("  [OK] test_to_dataframe_and_dict_smoke")


def test_optimize_window_error_branches():
    """API pública: optimizer desconhecido e janela sem combo válido → ValueError."""
    data = _idx_df(60)
    space = {"adx_threshold": [20.0, 25.0]}
    with pytest.raises(ValueError):
        optimize_window(data, space, optimizer="bogus", evaluator=lambda *a, **k: _fake_metrics(1.0))
    # Todos os combos inválidos (evaluator None) → nenhum combo válido.
    with pytest.raises(ValueError):
        optimize_window(data, space, optimizer="grid",
                        evaluator=lambda *a, **k: None)
    # min_trades filtra combos com poucos trades.
    with pytest.raises(ValueError):
        optimize_window(data, space, optimizer="grid", min_trades=999,
                        metric_to_optimize="sharpe",
                        evaluator=lambda d, p, t, b, c: _fake_metrics(1.0, trades=1))
    print("  [OK] test_optimize_window_error_branches")


def test_default_evaluator_real_path():
    """Caminho REAL (optimizer._eval_combo + Backtester) roda em OHLCV sintético."""
    data = _synth_ohlcv(7, 160)
    space = {"atr_stop_multiplier": [1.0, 2.0]}
    base = {"use_regime_filter": True, "adx_threshold": 25.0, "hurst_threshold": 0.50}
    best, metrics, _topk = optimize_window(
        data, space, ticker="TEST", base_params=base, optimizer="grid",
        metric_to_optimize="sharpe", min_trades=0, top_k=2)
    assert isinstance(best, dict) and "atr_stop_multiplier" in best
    assert "sharpe_ratio" in metrics
    print("  [OK] test_default_evaluator_real_path")


# ── Runner standalone ────────────────────────────────────────────────────────

_TESTS = [
    test_ar1_meanreverting_low_degradation,
    test_pure_random_high_degradation,
    test_embargo_respected,
    test_anchored_keeps_is_start_fixed,
    test_small_grid_exhaustive,
    test_determinism_same_seed,
    test_insufficient_data_raises,
    test_stability_score_1_when_same_best,
    test_stability_score_0_when_disjoint,
    test_dsr_penalizes_many_trials,
    test_compute_degradation_bands,
    test_to_dataframe_and_dict_smoke,
    test_optimize_window_error_branches,
    test_default_evaluator_real_path,
]


def run_all() -> bool:
    passed = failed = 0
    print(f"\n{'='*60}")
    print("  Suite: walkforward_honest — walk-forward honesto (Sprint 21)")
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
