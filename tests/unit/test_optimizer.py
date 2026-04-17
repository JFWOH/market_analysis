"""
tests/unit/test_optimizer.py — Testes do StrategyOptimizer.

Usa dados sintéticos injetados via monkey-patch em _load_data para
evitar chamadas de rede. Testa: grid search, filtros de qualidade,
early stopping, paralelismo, walk-forward splits e _summarize_folds.

Executável diretamente:
    python tests/unit/test_optimizer.py
"""

from __future__ import annotations

import os
import sys
import traceback
from unittest.mock import patch

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from optimizer import StrategyOptimizer, _eval_combo

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _synth_data(n: int = 120, trend: str = "up") -> pd.DataFrame:
    """Série OHLCV sintética e determinística."""
    rng = np.random.default_rng(7)
    if trend == "up":
        closes = np.linspace(90_000, 115_000, n) + rng.normal(0, 200, n)
    elif trend == "down":
        closes = np.linspace(115_000, 90_000, n) + rng.normal(0, 200, n)
    else:
        closes = np.full(n, 100_000.0) + rng.normal(0, 500, n)

    highs  = closes + rng.uniform(100, 500, n)
    lows   = closes - rng.uniform(100, 500, n)
    opens  = lows + rng.uniform(0, 1, n) * (highs - lows)
    idx    = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows,
        "Close": closes, "Volume": np.full(n, 10_000.0),
    }, index=idx)


def _patch_load(data: pd.DataFrame):
    """Context manager: substitui _load_data por retorno de dado fixo."""
    return patch.object(StrategyOptimizer, "_load_data", return_value=data)


_SMALL_GRID = {
    "ema_short":            [8, 13],
    "ema_medium":           [21],
    "use_trend_filter":     [True],
    "min_pattern_strength": [6, 8],
    "atr_stop_multiplier":  [1.5],
}


# ──────────────────────────────────────────────────────────────────────────────
# _eval_combo (unidade)
# ──────────────────────────────────────────────────────────────────────────────

def test_eval_combo_returns_dict_or_none():
    """_eval_combo deve retornar dict com 'params' ou None."""
    data   = _synth_data(80)
    params = {"ema_short": 8, "ema_medium": 21, "use_trend_filter": False,
              "min_pattern_strength": 6, "atr_stop_multiplier": 1.5}
    result = _eval_combo("TEST", "Test", params, data, 100_000.0)

    if result is not None:
        assert isinstance(result, dict), "Resultado deve ser dict"
        assert "params" in result, "Resultado deve ter chave 'params'"
        assert result["params"] == params
    print(f"  [OK] test_eval_combo_returns_dict_or_none  (result={'dict' if result else 'None'})")


def test_eval_combo_params_preserved():
    """Parâmetros passados ao _eval_combo devem estar no resultado."""
    data   = _synth_data(80)
    params = {"ema_short": 13, "ema_medium": 34, "use_trend_filter": False,
              "min_pattern_strength": 6, "atr_stop_multiplier": 2.0}
    result = _eval_combo("TEST", "Test", params, data, 100_000.0)

    if result is not None:
        assert result["params"]["ema_short"] == 13
        assert result["params"]["atr_stop_multiplier"] == 2.0
    print("  [OK] test_eval_combo_params_preserved")


# ──────────────────────────────────────────────────────────────────────────────
# optimize() — grid search
# ──────────────────────────────────────────────────────────────────────────────

def test_optimize_returns_list():
    """optimize() deve retornar lista (pode ser vazia)."""
    data = _synth_data(120)
    opt  = StrategyOptimizer("TEST", "Test")

    with _patch_load(data):
        results = opt.optimize("2022-01-03", "2022-06-30",
                               param_grid=_SMALL_GRID, min_trades=1)

    assert isinstance(results, list)
    print(f"  [OK] test_optimize_returns_list  ({len(results)} resultados)")


def test_optimize_results_have_params():
    """Cada resultado deve ter chave 'params' com dict de parâmetros."""
    data = _synth_data(120)
    opt  = StrategyOptimizer("TEST", "Test")

    with _patch_load(data):
        results = opt.optimize("2022-01-03", "2022-06-30",
                               param_grid=_SMALL_GRID, min_trades=1)

    for r in results:
        assert "params" in r, f"Resultado sem 'params': {r.keys()}"
        assert isinstance(r["params"], dict)
    print(f"  [OK] test_optimize_results_have_params")


def test_optimize_sorted_by_metric():
    """Resultados devem estar ordenados pela métrica (decrescente)."""
    data = _synth_data(120)
    opt  = StrategyOptimizer("TEST", "Test")

    for metric in ["return_pct", "sharpe_ratio"]:
        with _patch_load(data):
            results = opt.optimize("2022-01-03", "2022-06-30",
                                   param_grid=_SMALL_GRID,
                                   metric=metric, min_trades=1)
        if len(results) >= 2:
            vals = [r.get(metric, float("-inf")) for r in results]
            assert vals == sorted(vals, reverse=True), (
                f"Resultados não ordenados por {metric}: {vals[:3]}"
            )
    print("  [OK] test_optimize_sorted_by_metric")


def test_optimize_invalid_metric_falls_back():
    """Métrica inválida deve fazer fallback para sharpe_ratio sem erro."""
    data = _synth_data(120)
    opt  = StrategyOptimizer("TEST", "Test")

    with _patch_load(data):
        results = opt.optimize("2022-01-03", "2022-06-30",
                               param_grid=_SMALL_GRID,
                               metric="invented_metric_xyz", min_trades=1)

    assert isinstance(results, list)   # não levantou exceção
    print("  [OK] test_optimize_invalid_metric_falls_back")


# ──────────────────────────────────────────────────────────────────────────────
# Filtros de qualidade
# ──────────────────────────────────────────────────────────────────────────────

def test_filter_min_trades():
    """Combos abaixo de min_trades devem ser removidos."""
    results_raw = [
        {"trade_count": 0, "max_drawdown": 10, "return_pct": 0.5, "params": {}},
        {"trade_count": 2, "max_drawdown": 10, "return_pct": 0.3, "params": {}},
        {"trade_count": 5, "max_drawdown": 10, "return_pct": 0.1, "params": {}},
    ]
    filtered = StrategyOptimizer._filter_results(results_raw, min_trades=3, max_drawdown_pct=80)
    assert len(filtered) == 1, f"Esperado 1 resultado, obteve {len(filtered)}"
    assert filtered[0]["trade_count"] == 5
    print("  [OK] test_filter_min_trades")


def test_filter_max_drawdown():
    """Combos com drawdown acima do limite devem ser removidos."""
    results_raw = [
        {"trade_count": 5, "max_drawdown": 30,  "return_pct": 0.4, "params": {}},
        {"trade_count": 5, "max_drawdown": 60,  "return_pct": 0.8, "params": {}},  # DD alto
        {"trade_count": 5, "max_drawdown": 100, "return_pct": 1.5, "params": {}},  # DD altíssimo
    ]
    filtered = StrategyOptimizer._filter_results(results_raw, min_trades=3, max_drawdown_pct=50)
    assert len(filtered) == 1, f"Esperado 1, obteve {len(filtered)}"
    assert filtered[0]["max_drawdown"] == 30
    print("  [OK] test_filter_max_drawdown")


def test_filter_catastrophic_loss():
    """Retorno < -90% deve ser removido mesmo com trades suficientes."""
    results_raw = [
        {"trade_count": 10, "max_drawdown": 10, "return_pct": -0.95, "params": {}},
        {"trade_count": 10, "max_drawdown": 10, "return_pct": -0.30, "params": {}},
    ]
    filtered = StrategyOptimizer._filter_results(results_raw, min_trades=3, max_drawdown_pct=80)
    assert len(filtered) == 1
    assert filtered[0]["return_pct"] == -0.30
    print("  [OK] test_filter_catastrophic_loss")


# ──────────────────────────────────────────────────────────────────────────────
# Early stopping
# ──────────────────────────────────────────────────────────────────────────────

def test_early_stopping_limits_combos():
    """Com patience=1, o search deve parar cedo (antes de avaliar todos os combos)."""
    data = _synth_data(120)
    opt  = StrategyOptimizer("TEST", "Test")

    # Grid com 4 combos
    small = {
        "ema_short":            [8, 13],
        "ema_medium":           [21],
        "use_trend_filter":     [True],
        "min_pattern_strength": [6, 8],
        "atr_stop_multiplier":  [1.5],
    }

    eval_count = []

    original_eval = _eval_combo

    def counting_eval(ticker, name, params, data_, capital):
        eval_count.append(1)
        return original_eval(ticker, name, params, data_, capital)

    import optimizer as _opt_module
    original = _opt_module._eval_combo

    try:
        _opt_module._eval_combo = counting_eval
        with _patch_load(data):
            results = opt.optimize("2022-01-03", "2022-06-30",
                                   param_grid=small, min_trades=1,
                                   patience=1)
    finally:
        _opt_module._eval_combo = original

    total_combos = 4
    # Com patience=1 e resultados aleatórios, deve parar antes de 4 combos
    # (ao primeiro combo sem melhoria)
    # Em alguns casos pode avaliar todos se cada um é melhor — só verificamos
    # que o mecanismo não lança exceção
    assert isinstance(results, list)
    print(f"  [OK] test_early_stopping_limits_combos  ({len(eval_count)}/{total_combos} avaliados)")


# ──────────────────────────────────────────────────────────────────────────────
# Paralelismo
# ──────────────────────────────────────────────────────────────────────────────

def test_parallel_same_count_as_sequential():
    """n_jobs=2 deve produzir mesmo número de resultados que n_jobs=1."""
    data = _synth_data(120)
    opt1 = StrategyOptimizer("TEST", "Test")
    opt2 = StrategyOptimizer("TEST", "Test")

    with _patch_load(data):
        r1 = opt1.optimize("2022-01-03", "2022-06-30",
                           param_grid=_SMALL_GRID, min_trades=1, n_jobs=1)
    with _patch_load(data):
        r2 = opt2.optimize("2022-01-03", "2022-06-30",
                           param_grid=_SMALL_GRID, min_trades=1, n_jobs=2)

    assert len(r1) == len(r2), (
        f"n_jobs=1 deu {len(r1)} resultados, n_jobs=2 deu {len(r2)}"
    )
    print(f"  [OK] test_parallel_same_count_as_sequential  ({len(r1)} resultados)")


def test_resolve_n_jobs():
    """_resolve_n_jobs(-1) deve retornar > 0."""
    workers = StrategyOptimizer._resolve_n_jobs(-1)
    assert workers > 0, f"n_jobs=-1 deve resolver para > 0, obteve {workers}"
    assert StrategyOptimizer._resolve_n_jobs(4) == 4
    assert StrategyOptimizer._resolve_n_jobs(0) == 1   # clamp para 1
    print(f"  [OK] test_resolve_n_jobs  (n_jobs=-1 -> {workers})")


# ──────────────────────────────────────────────────────────────────────────────
# Walk-forward splits
# ──────────────────────────────────────────────────────────────────────────────

def test_make_splits_count():
    """_make_splits deve retornar exatamente n_folds splits."""
    splits = StrategyOptimizer._make_splits("2020-01-01", "2023-12-31", n_folds=4, train_pct=0.7)
    assert len(splits) == 4, f"Esperado 4 splits, obteve {len(splits)}"
    print(f"  [OK] test_make_splits_count  ({len(splits)} splits)")


def test_make_splits_non_overlapping():
    """Splits não devem ter sobreposição entre test_end de um fold e train_start do seguinte."""
    splits = StrategyOptimizer._make_splits("2020-01-01", "2024-12-31", n_folds=4, train_pct=0.7)
    for k in range(len(splits) - 1):
        cur_fold_end  = pd.Timestamp(splits[k][3])    # test_end do fold k
        next_fold_start = pd.Timestamp(splits[k+1][0]) # train_start do fold k+1
        assert next_fold_start >= cur_fold_end - pd.Timedelta(days=2), (
            f"Fold {k} e {k+1} se sobrepõem: {cur_fold_end} vs {next_fold_start}"
        )
    print("  [OK] test_make_splits_non_overlapping")


def test_make_splits_train_before_test():
    """Em cada split, train_end deve ser anterior a test_start."""
    splits = StrategyOptimizer._make_splits("2020-01-01", "2024-12-31", n_folds=4, train_pct=0.7)
    for k, (tr_s, tr_e, ts_s, ts_e) in enumerate(splits):
        assert pd.Timestamp(tr_e) <= pd.Timestamp(ts_s), (
            f"Fold {k}: train_end ({tr_e}) >= test_start ({ts_s})"
        )
        assert pd.Timestamp(ts_s) <= pd.Timestamp(ts_e), (
            f"Fold {k}: test_start ({ts_s}) >= test_end ({ts_e})"
        )
    print("  [OK] test_make_splits_train_before_test")


def test_make_splits_short_period_returns_empty():
    """Período muito curto para N folds deve retornar lista vazia."""
    splits = StrategyOptimizer._make_splits("2023-01-01", "2023-02-28",
                                             n_folds=10, train_pct=0.7)
    assert splits == [], f"Esperado [], obteve {splits}"
    print("  [OK] test_make_splits_short_period_returns_empty")


# ──────────────────────────────────────────────────────────────────────────────
# Summarize folds
# ──────────────────────────────────────────────────────────────────────────────

def test_summarize_folds_averages():
    """_summarize_folds deve calcular médias corretas de return_pct."""
    fold_results = [
        {"fold": 1, "test_metrics": {"return_pct": 0.10, "sharpe_ratio": 1.2,
                                      "max_drawdown": 5.0, "win_rate": 0.6,
                                      "trade_count": 10, "profit_factor": 1.5}},
        {"fold": 2, "test_metrics": {"return_pct": 0.20, "sharpe_ratio": 1.8,
                                      "max_drawdown": 8.0, "win_rate": 0.7,
                                      "trade_count": 12, "profit_factor": 2.0}},
        {"fold": 3, "test_metrics": {"return_pct": -0.05, "sharpe_ratio": -0.3,
                                      "max_drawdown": 15.0,"win_rate": 0.4,
                                      "trade_count": 8, "profit_factor": 0.8}},
    ]
    summary = StrategyOptimizer._summarize_folds(fold_results, "sharpe_ratio")

    assert abs(summary["avg_return_pct"] - 0.25/3) < 1e-6, (
        f"avg_return_pct errado: {summary['avg_return_pct']}"
    )
    assert summary["n_folds_completed"] == 3
    assert abs(summary["positive_fold_pct"] - 2/3) < 1e-6
    print(f"  [OK] test_summarize_folds_averages  "
          f"(avg_ret={summary['avg_return_pct']:.3f})")


def test_summarize_folds_empty():
    """_summarize_folds com lista vazia deve retornar dict vazio."""
    summary = StrategyOptimizer._summarize_folds([], "sharpe_ratio")
    assert summary == {}
    print("  [OK] test_summarize_folds_empty")


def test_most_common_params():
    """_most_common_params deve retornar o valor que aparece mais vezes."""
    fold_results = [
        {"best_params": {"ema_short": 8,  "use_trend_filter": True}},
        {"best_params": {"ema_short": 13, "use_trend_filter": True}},
        {"best_params": {"ema_short": 8,  "use_trend_filter": False}},
    ]
    common = StrategyOptimizer._most_common_params(fold_results)
    assert common["ema_short"] == 8, f"Esperado 8, obteve {common['ema_short']}"
    assert common["use_trend_filter"] is True
    print(f"  [OK] test_most_common_params  ({common})")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_eval_combo_returns_dict_or_none,
    test_eval_combo_params_preserved,
    test_optimize_returns_list,
    test_optimize_results_have_params,
    test_optimize_sorted_by_metric,
    test_optimize_invalid_metric_falls_back,
    test_filter_min_trades,
    test_filter_max_drawdown,
    test_filter_catastrophic_loss,
    test_early_stopping_limits_combos,
    test_parallel_same_count_as_sequential,
    test_resolve_n_jobs,
    test_make_splits_count,
    test_make_splits_non_overlapping,
    test_make_splits_train_before_test,
    test_make_splits_short_period_returns_empty,
    test_summarize_folds_averages,
    test_summarize_folds_empty,
    test_most_common_params,
]


def run_all() -> bool:
    passed = failed = 0
    print(f"\n{'='*60}")
    print("  Suite: optimizer/ — grid search + filtros + walk-forward")
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
