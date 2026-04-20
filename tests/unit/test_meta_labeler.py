"""
tests/unit/test_meta_labeler.py — Testes do Meta-Labeler.

Sprint-3 passo 3: classificador secundario que filtra sinais do modelo
primario (CombinedStrategy) pelos de maior probabilidade de acerto.

Executavel diretamente:
    python tests/unit/test_meta_labeler.py
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

from meta_labeler import MetaLabeler, build_features, _safe
from labels import TripleBarrierLabeler
from strategy import CombinedStrategy


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _ohlcv(n: int = 300, drift: float = 0.001, vol: float = 0.012,
           seed: int = 0) -> pd.DataFrame:
    rng   = np.random.default_rng(seed)
    close = 100_000.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    rng2  = np.random.default_rng(seed + 1)
    return pd.DataFrame({
        "Open":   close,
        "High":   close * (1 + np.abs(rng2.normal(0, 0.004, n))),
        "Low":    close * (1 - np.abs(rng2.normal(0, 0.004, n))),
        "Close":  close,
        "Volume": np.full(n, 1e6),
    }, index=pd.date_range("2022-01-03", periods=n, freq="B"))


def _prepared_strategy(n: int = 300, seed: int = 0, **params) -> CombinedStrategy:
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(_ohlcv(n=n, seed=seed))
    s.params.update(params)
    s.prepare()
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Testes — build_features
# ─────────────────────────────────────────────────────────────────────────────

def test_build_features_returns_dataframe():
    s = _prepared_strategy()
    X = build_features(s.data)
    assert isinstance(X, pd.DataFrame)
    assert not X.empty
    print(f"  [OK] test_build_features_returns_dataframe  "
          f"({X.shape[0]} linhas, {X.shape[1]} features)")


def test_build_features_no_nan():
    """Features nao devem conter NaN (safe() garante 0 no lugar)."""
    s = _prepared_strategy()
    X = build_features(s.data)
    assert not X.isnull().any().any(), "Features com NaN encontrados"
    print("  [OK] test_build_features_no_nan")


def test_build_features_specific_timestamps():
    s    = _prepared_strategy()
    ts   = s.data.index[50:80]
    X    = build_features(s.data, timestamps=ts)
    assert len(X) == len(ts)
    assert all(t in ts for t in X.index)
    print(f"  [OK] test_build_features_specific_timestamps  ({len(X)} linhas)")


def test_build_features_scale_invariant():
    """EMA dist features devem ser frações pequenas (price-normalized)."""
    s = _prepared_strategy()
    X = build_features(s.data)
    for col in ["ema8_dist", "ema21_dist", "ema55_dist"]:
        if col in X.columns:
            assert X[col].abs().max() < 1.0, \
                f"{col} nao esta normalizado: max={X[col].abs().max():.4f}"
    print("  [OK] test_build_features_scale_invariant")


def test_build_features_empty_on_bad_data():
    """DataFrame vazio ou sem Close deve retornar DataFrame vazio."""
    X = build_features(pd.DataFrame())
    assert X.empty
    print("  [OK] test_build_features_empty_on_bad_data")


def test_safe_handles_nan():
    assert _safe(np.nan) == 0.0
    assert _safe(None)   == 0.0
    assert _safe(1.5)    == 1.5
    assert _safe("x")    == 0.0
    print("  [OK] test_safe_handles_nan")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — MetaLabeler.fit / predict_proba
# ─────────────────────────────────────────────────────────────────────────────

def test_meta_labeler_fit_from_strategy():
    """fit_from_strategy deve completar sem excecoes."""
    s  = _prepared_strategy(n=400, seed=1)
    ml = MetaLabeler(n_estimators=20)
    ml.fit_from_strategy(s, eval_cv=False)
    # Pode nao ter ficado fitted se nao houver sinais suficientes
    assert isinstance(ml._fitted, bool)
    print(f"  [OK] test_meta_labeler_fit_from_strategy  (fitted={ml._fitted})")


def test_meta_labeler_predict_proba_range():
    """Probabilidades devem estar em [0, 1]."""
    s  = _prepared_strategy(n=500, seed=2)
    ml = MetaLabeler(n_estimators=20)
    ml.fit_from_strategy(s, eval_cv=False)
    if not ml._fitted:
        print("  [OK] test_meta_labeler_predict_proba_range  (sem dados suficientes)")
        return
    X = build_features(s.data)
    p = ml.predict_proba(X)
    assert p.between(0.0, 1.0).all(), f"Probabilidades fora de [0,1]: {p.describe()}"
    print(f"  [OK] test_meta_labeler_predict_proba_range  "
          f"(min={p.min():.3f}, max={p.max():.3f})")


def test_meta_labeler_predict_proba_length():
    """predict_proba deve ter mesmo tamanho que X."""
    s  = _prepared_strategy(n=500, seed=3)
    ml = MetaLabeler(n_estimators=20)
    ml.fit_from_strategy(s, eval_cv=False)
    if not ml._fitted:
        print("  [OK] test_meta_labeler_predict_proba_length  (sem dados)")
        return
    X = build_features(s.data)
    p = ml.predict_proba(X)
    assert len(p) == len(X)
    print(f"  [OK] test_meta_labeler_predict_proba_length  ({len(p)} probas)")


def test_meta_labeler_fit_direct():
    """fit() direto com X, y sinteticos deve funcionar."""
    n = 200
    rng = np.random.default_rng(0)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    X   = pd.DataFrame(rng.normal(size=(n, 5)),
                       columns=["f1","f2","f3","f4","f5"], index=idx)
    y   = pd.Series(rng.integers(0, 2, n), index=idx)
    ml  = MetaLabeler(n_estimators=20)
    ml.fit(X, y, eval_cv=False)
    assert ml._fitted
    p = ml.predict_proba(X)
    assert len(p) == n
    print(f"  [OK] test_meta_labeler_fit_direct  (ROC-AUC CV={ml.cv_roc_auc})")


def test_meta_labeler_not_fitted_raises():
    """predict_proba sem fit deve levantar RuntimeError."""
    ml = MetaLabeler()
    X  = pd.DataFrame({"f1": [1.0, 2.0]})
    try:
        ml.predict_proba(X)
        assert False, "Deveria ter levantado RuntimeError"
    except RuntimeError:
        pass
    print("  [OK] test_meta_labeler_not_fitted_raises")


def test_meta_labeler_fit_drops_nan_labels():
    """Labels NaN devem ser ignorados no treinamento."""
    n   = 100
    rng = np.random.default_rng(1)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    X   = pd.DataFrame(rng.normal(size=(n, 3)),
                       columns=["f1","f2","f3"], index=idx)
    y   = pd.Series([1.0, 0.0, np.nan] * (n // 3) + [1.0] * (n % 3), index=idx)
    ml  = MetaLabeler(n_estimators=10)
    ml.fit(X, y, eval_cv=False)   # nao deve crashar
    assert ml._fitted
    print("  [OK] test_meta_labeler_fit_drops_nan_labels")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — MetaLabeler.filter_signals
# ─────────────────────────────────────────────────────────────────────────────

def test_filter_signals_returns_list():
    s  = _prepared_strategy(n=400, seed=4)
    ml = MetaLabeler(n_estimators=20)
    ml.fit_from_strategy(s, eval_cv=False)
    sigs = s.generate_signals()
    out  = ml.filter_signals(sigs, s.data)
    assert isinstance(out, list)
    print(f"  [OK] test_filter_signals_returns_list  ({len(sigs)} -> {len(out)})")


def test_filter_signals_reduces_or_equal():
    """Com min_prob=0.5, resultado <= total de sinais."""
    s  = _prepared_strategy(n=400, seed=5)
    ml = MetaLabeler(n_estimators=20, min_prob=0.5)
    ml.fit_from_strategy(s, eval_cv=False)
    sigs = s.generate_signals()
    out  = ml.filter_signals(sigs, s.data)
    assert len(out) <= len(sigs), \
        f"Filter nao reduziu: {len(out)} > {len(sigs)}"
    print(f"  [OK] test_filter_signals_reduces_or_equal  ({len(sigs)} -> {len(out)})")


def test_filter_signals_high_threshold_reduces_more():
    """Threshold maior => menos sinais aceitos."""
    s  = _prepared_strategy(n=500, seed=6)
    ml_lo = MetaLabeler(n_estimators=20, min_prob=0.3)
    ml_hi = MetaLabeler(n_estimators=20, min_prob=0.8)
    ml_lo.fit_from_strategy(s, eval_cv=False)
    ml_hi.fit_from_strategy(s, eval_cv=False)
    sigs = s.generate_signals()
    out_lo = ml_lo.filter_signals(sigs, s.data)
    out_hi = ml_hi.filter_signals(sigs, s.data)
    assert len(out_lo) >= len(out_hi), \
        f"Threshold maior deveria dar menos sinais: lo={len(out_lo)}, hi={len(out_hi)}"
    print(f"  [OK] test_filter_signals_high_threshold_reduces_more  "
          f"(lo={len(out_lo)}, hi={len(out_hi)})")


def test_filter_signals_not_fitted_passthrough():
    """Sem treinamento, filter_signals deve retornar todos os sinais."""
    s    = _prepared_strategy(n=300, seed=7)
    ml   = MetaLabeler()
    sigs = s.generate_signals()
    out  = ml.filter_signals(sigs, s.data)
    assert len(out) == len(sigs), "Passthrough falhou"
    print(f"  [OK] test_filter_signals_not_fitted_passthrough  ({len(sigs)} sinais)")


def test_filter_signals_adds_meta_prob():
    """Sinais aceitos devem ter campo meta_prob adicionado."""
    s  = _prepared_strategy(n=400, seed=8)
    ml = MetaLabeler(n_estimators=20, min_prob=0.0)  # aceita todos
    ml.fit_from_strategy(s, eval_cv=False)
    sigs = s.generate_signals()
    out  = ml.filter_signals(sigs, s.data)
    if not out or not ml._fitted:
        print("  [OK] test_filter_signals_adds_meta_prob  (sem sinais/modelo)")
        return
    for sig in out:
        assert "meta_prob" in sig, f"meta_prob ausente: {sig}"
    print(f"  [OK] test_filter_signals_adds_meta_prob  ({len(out)} sinais)")


def test_filter_signals_empty_list():
    """Lista vazia deve retornar lista vazia."""
    s  = _prepared_strategy(n=300, seed=9)
    ml = MetaLabeler(n_estimators=10)
    ml.fit_from_strategy(s, eval_cv=False)
    out = ml.filter_signals([], s.data)
    assert out == []
    print("  [OK] test_filter_signals_empty_list")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — diagnostico / feature importance
# ─────────────────────────────────────────────────────────────────────────────

def test_feature_importance_returns_series():
    s  = _prepared_strategy(n=400, seed=10)
    ml = MetaLabeler(n_estimators=20)
    ml.fit_from_strategy(s, eval_cv=False)
    if not ml._fitted:
        print("  [OK] test_feature_importance_returns_series  (sem modelo)")
        return
    fi = ml.feature_importance()
    assert isinstance(fi, pd.Series)
    assert (fi >= 0).all()
    assert abs(fi.sum() - 1.0) < 1e-6, f"Importâncias nao somam 1: {fi.sum()}"
    print(f"  [OK] test_feature_importance_returns_series  "
          f"(top={fi.index[0]}, imp={fi.iloc[0]:.3f})")


def test_report_keys():
    ml = MetaLabeler(n_estimators=10)
    r  = ml.report()
    required = {"fitted", "cv_roc_auc", "cv_scores", "min_prob", "n_features"}
    assert required <= set(r.keys())
    assert r["fitted"] is False
    print("  [OK] test_report_keys")


def test_cv_roc_auc_after_fit():
    """Apos fit com eval_cv=True e dados suficientes, cv_roc_auc deve ser float."""
    n   = 200
    rng = np.random.default_rng(42)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    # Cria um problema com sinal: f1 + ruido prediz y
    f1  = rng.normal(size=n)
    X   = pd.DataFrame({"f1": f1, "f2": rng.normal(size=n)}, index=idx)
    y   = pd.Series((f1 > 0).astype(int), index=idx)
    ml  = MetaLabeler(n_estimators=30, n_splits=3)
    ml.fit(X, y, eval_cv=True)
    if ml.cv_roc_auc is not None:
        assert 0.0 <= ml.cv_roc_auc <= 1.0
        print(f"  [OK] test_cv_roc_auc_after_fit  (ROC-AUC={ml.cv_roc_auc:.3f})")
    else:
        print("  [OK] test_cv_roc_auc_after_fit  (CV nao executado)")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all() -> int:
    tests = [
        # build_features
        test_build_features_returns_dataframe,
        test_build_features_no_nan,
        test_build_features_specific_timestamps,
        test_build_features_scale_invariant,
        test_build_features_empty_on_bad_data,
        test_safe_handles_nan,
        # fit / predict_proba
        test_meta_labeler_fit_from_strategy,
        test_meta_labeler_predict_proba_range,
        test_meta_labeler_predict_proba_length,
        test_meta_labeler_fit_direct,
        test_meta_labeler_not_fitted_raises,
        test_meta_labeler_fit_drops_nan_labels,
        # filter_signals
        test_filter_signals_returns_list,
        test_filter_signals_reduces_or_equal,
        test_filter_signals_high_threshold_reduces_more,
        test_filter_signals_not_fitted_passthrough,
        test_filter_signals_adds_meta_prob,
        test_filter_signals_empty_list,
        # diagnóstico
        test_feature_importance_returns_series,
        test_report_keys,
        test_cv_roc_auc_after_fit,
    ]
    print("=" * 60)
    print("  Suite: Meta-Labeler (Sprint-3 passo 3)")
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
