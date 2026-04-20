"""
tests/unit/test_meta_integration.py — Testes da integração Meta-Labeler na Strategy.

Sprint-4 passo 1: meta-labeler wired em CombinedStrategy via use_meta_labeler.
train_meta_labeler(), auto-train, filtro em generate_signals().

Executavel diretamente:
    python tests/unit/test_meta_integration.py
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


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _ohlcv(n: int = 300, drift: float = 0.001, vol: float = 0.012,
           seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100_000.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    rng2  = np.random.default_rng(seed + 1)
    return pd.DataFrame({
        "Open":   close,
        "High":   close * (1 + np.abs(rng2.normal(0, 0.004, n))),
        "Low":    close * (1 - np.abs(rng2.normal(0, 0.004, n))),
        "Close":  close,
        "Volume": np.full(n, 1e6),
    }, index=pd.date_range("2022-01-03", periods=n, freq="B"))


def _make(seed: int = 0, n: int = 300, **params) -> CombinedStrategy:
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(_ohlcv(n=n, seed=seed))
    s.params.update(params)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Testes — DEFAULT_PARAMS
# ─────────────────────────────────────────────────────────────────────────────

def test_meta_params_in_defaults():
    """Todos os params do meta-labeler devem estar em DEFAULT_PARAMS."""
    defaults = CombinedStrategy.DEFAULT_PARAMS
    required = {"use_meta_labeler", "meta_min_prob", "meta_pt", "meta_sl",
                "meta_max_holding", "meta_n_estimators", "meta_auto_train"}
    missing = required - set(defaults.keys())
    assert not missing, f"Params ausentes: {missing}"
    assert defaults["use_meta_labeler"] is False, "Default deve ser False (opt-in)"
    print("  [OK] test_meta_params_in_defaults")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — train_meta_labeler()
# ─────────────────────────────────────────────────────────────────────────────

def test_train_meta_labeler_returns_bool():
    s = _make(seed=1, n=400)
    result = s.train_meta_labeler()
    assert isinstance(result, bool)
    print(f"  [OK] test_train_meta_labeler_returns_bool  (result={result})")


def test_train_meta_labeler_sets_instance():
    """Após train, _meta_labeler deve ser instância MetaLabeler."""
    s = _make(seed=2, n=400)
    s.train_meta_labeler()
    from meta_labeler import MetaLabeler
    assert isinstance(s._meta_labeler, MetaLabeler)
    print("  [OK] test_train_meta_labeler_sets_instance")


def test_train_meta_labeler_idempotent():
    """Segunda chamada não re-treina (sem force=True)."""
    s = _make(seed=3, n=400)
    s.train_meta_labeler()
    ml_first = id(s._meta_labeler)
    s.train_meta_labeler()   # segunda chamada — deve ser no-op
    assert id(s._meta_labeler) == ml_first, "Instância foi substituída sem force"
    print("  [OK] test_train_meta_labeler_idempotent")


def test_train_meta_labeler_force_retrains():
    """force=True deve substituir o modelo anterior."""
    s = _make(seed=4, n=400)
    s.train_meta_labeler()
    ml_first = id(s._meta_labeler)
    s.train_meta_labeler(force=True)
    assert id(s._meta_labeler) != ml_first, "force=True deveria recriar o modelo"
    print("  [OK] test_train_meta_labeler_force_retrains")


def test_train_meta_labeler_without_data():
    """Sem data carregado deve retornar False sem crashar."""
    s = CombinedStrategy("^BVSP")
    result = s.train_meta_labeler()
    assert result is False
    print("  [OK] test_train_meta_labeler_without_data")


def test_train_meta_labeler_calls_prepare():
    """train_meta_labeler() deve funcionar mesmo antes de prepare() ter sido chamado."""
    s = _make(seed=5, n=400)
    assert not s._prepared
    s.train_meta_labeler()
    # Se chegou aqui sem excecao, prepare() foi chamado internamente
    print("  [OK] test_train_meta_labeler_calls_prepare")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — generate_signals() com meta-labeler
# ─────────────────────────────────────────────────────────────────────────────

def test_meta_off_by_default():
    """use_meta_labeler=False (default): _meta_labeler não é instanciado."""
    s = _make(seed=6, n=300)
    s.generate_signals()
    assert s._meta_labeler is None, "Sem use_meta_labeler, modelo não deve ser criado"
    print("  [OK] test_meta_off_by_default")


def test_meta_on_auto_trains():
    """use_meta_labeler=True + meta_auto_train=True: treina na primeira chamada."""
    s = _make(seed=7, n=400, use_meta_labeler=True, meta_n_estimators=20)
    s.generate_signals()
    assert s._meta_labeler is not None
    assert s._meta_labeler._fitted
    print(f"  [OK] test_meta_on_auto_trains  (fitted={s._meta_labeler._fitted})")


def test_meta_on_reduces_signals():
    """Meta-labeler ON deve produzir <= sinais que OFF."""
    df = _ohlcv(n=400, seed=8)
    s_off = _make(seed=8, n=400, use_meta_labeler=False)
    s_on  = _make(seed=8, n=400, use_meta_labeler=True,
                  meta_n_estimators=20, meta_min_prob=0.55)
    n_off = len(s_off.generate_signals())
    n_on  = len(s_on.generate_signals())
    assert n_on <= n_off, f"meta ON ({n_on}) deveria <= meta OFF ({n_off})"
    print(f"  [OK] test_meta_on_reduces_signals  ({n_off} -> {n_on})")


def test_meta_higher_threshold_fewer_signals():
    """Threshold mais alto => menos sinais aceitos."""
    df = _ohlcv(n=500, seed=9)
    s_lo = CombinedStrategy("^BVSP")
    s_lo.set_data(df.copy())
    s_lo.params.update(use_meta_labeler=True, meta_min_prob=0.30, meta_n_estimators=20)

    s_hi = CombinedStrategy("^BVSP")
    s_hi.set_data(df.copy())
    s_hi.params.update(use_meta_labeler=True, meta_min_prob=0.80, meta_n_estimators=20)

    n_lo = len(s_lo.generate_signals())
    n_hi = len(s_hi.generate_signals())
    assert n_lo >= n_hi, f"threshold maior deveria dar menos sinais: lo={n_lo}, hi={n_hi}"
    print(f"  [OK] test_meta_higher_threshold_fewer_signals  (lo={n_lo}, hi={n_hi})")


def test_meta_no_recursion():
    """Chamadas aninhadas não devem causar recursão infinita."""
    s = _make(seed=10, n=400, use_meta_labeler=True, meta_n_estimators=10)
    try:
        sigs = s.generate_signals()
        # segunda chamada (usa modelo já treinado)
        sigs2 = s.generate_signals()
    except RecursionError:
        assert False, "Recursão infinita detectada!"
    print(f"  [OK] test_meta_no_recursion  ({len(sigs)} / {len(sigs2)} sinais)")


def test_meta_auto_train_false_no_model():
    """meta_auto_train=False: modelo não treinado, sinais passam sem filtro."""
    s = _make(seed=11, n=300, use_meta_labeler=True, meta_auto_train=False)
    sigs = s.generate_signals()
    assert s._meta_labeler is None, "Com auto_train=False, modelo não deve ser criado"
    # Sinais devem ser os mesmos que sem meta (passthrough)
    s2 = _make(seed=11, n=300, use_meta_labeler=False)
    sigs2 = s2.generate_signals()
    assert len(sigs) == len(sigs2), \
        f"Passthrough falhou: meta_off={len(sigs2)}, auto_train_false={len(sigs)}"
    print(f"  [OK] test_meta_auto_train_false_no_model  ({len(sigs)} sinais)")


def test_meta_signals_preserve_structure():
    """Sinais após filtro devem manter estrutura original (campos obrigatórios)."""
    s = _make(seed=12, n=400, use_meta_labeler=True, meta_n_estimators=20,
              meta_min_prob=0.0)   # aceita todos
    sigs = s.generate_signals()
    required = {"data", "tipo", "preco", "stop_loss", "preco_alvo", "estrategia", "forca"}
    for sig in sigs:
        missing = required - set(sig.keys())
        assert not missing, f"Campos ausentes: {missing}"
    print(f"  [OK] test_meta_signals_preserve_structure  ({len(sigs)} sinais)")


def test_meta_with_ensemble():
    """Meta-labeler deve funcionar em conjunto com o ensemble."""
    s = _make(seed=13, n=400,
              use_meta_labeler=True, meta_n_estimators=20,
              use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True)
    sigs = s.generate_signals()
    assert isinstance(sigs, list)
    print(f"  [OK] test_meta_with_ensemble  ({len(sigs)} sinais)")


def test_meta_with_regime_and_vol():
    """Sprint-2+3+4: regime + vol targeting + ensemble + meta-labeler juntos."""
    s = _make(seed=14, n=500,
              use_meta_labeler=True, meta_n_estimators=20,
              use_regime_filter=True, adx_threshold=20.0,
              use_vol_targeting=True, vol_target_annual=0.15,
              use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True)
    sigs = s.generate_signals()
    assert isinstance(sigs, list)
    print(f"  [OK] test_meta_with_regime_and_vol  ({len(sigs)} sinais)")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all() -> int:
    tests = [
        # DEFAULT_PARAMS
        test_meta_params_in_defaults,
        # train_meta_labeler
        test_train_meta_labeler_returns_bool,
        test_train_meta_labeler_sets_instance,
        test_train_meta_labeler_idempotent,
        test_train_meta_labeler_force_retrains,
        test_train_meta_labeler_without_data,
        test_train_meta_labeler_calls_prepare,
        # generate_signals com meta
        test_meta_off_by_default,
        test_meta_on_auto_trains,
        test_meta_on_reduces_signals,
        test_meta_higher_threshold_fewer_signals,
        test_meta_no_recursion,
        test_meta_auto_train_false_no_model,
        test_meta_signals_preserve_structure,
        test_meta_with_ensemble,
        test_meta_with_regime_and_vol,
    ]
    print("=" * 60)
    print("  Suite: Meta-Labeler Integration (Sprint-4 passo 1)")
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
