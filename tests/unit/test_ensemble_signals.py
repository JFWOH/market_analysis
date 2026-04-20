"""
tests/unit/test_ensemble_signals.py — Testes do Ensemble de Sinais.

Sprint-2 passo 3: EMA crossover + Breakout N-barras combinados ao
gerador de price action existente para aumentar frequencia de sinais
qualificados sem degradar qualidade.

Executavel diretamente:
    python tests/unit/test_ensemble_signals.py
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

def _uptrend(n: int = 150, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100_000.0 * np.exp(np.cumsum(rng.normal(0.005, 0.010, n)))
    high  = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low   = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx   = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def _downtrend(n: int = 150, seed: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100_000.0 * np.exp(np.cumsum(rng.normal(-0.005, 0.010, n)))
    high  = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low   = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx   = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def _ranging(n: int = 150, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100_000.0 + np.cumsum(rng.normal(0, 500, n))
    close = np.abs(close)
    high  = close + np.abs(rng.normal(0, 200, n))
    low   = close - np.abs(rng.normal(0, 200, n))
    idx   = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def _down_then_up(n: int = 300, seed: int = 1) -> pd.DataFrame:
    """Downtrend seguido de uptrend — garante golden cross (EMA_8 cruzar acima EMA_55)."""
    rng  = np.random.default_rng(seed)
    half = n // 2
    down = 100_000.0 * np.exp(np.cumsum(rng.normal(-0.008, 0.010, half)))
    up   = down[-1]  * np.exp(np.cumsum(rng.normal(+0.008, 0.010, half)))
    close = np.concatenate([down, up])
    high  = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low   = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx   = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def _up_then_down(n: int = 300, seed: int = 2) -> pd.DataFrame:
    """Uptrend seguido de downtrend — garante death cross (EMA_8 cruzar abaixo EMA_55)."""
    rng  = np.random.default_rng(seed)
    half = n // 2
    up   = 100_000.0 * np.exp(np.cumsum(rng.normal(+0.008, 0.010, half)))
    down = up[-1]    * np.exp(np.cumsum(rng.normal(-0.008, 0.010, half)))
    close = np.concatenate([up, down])
    high  = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low   = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx   = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def _make_strategy(df: pd.DataFrame, **params) -> CombinedStrategy:
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(df)
    s.params.update(params)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Testes — EMA Crossover
# ─────────────────────────────────────────────────────────────────────────────

def test_ema_cross_returns_list():
    s = _make_strategy(_uptrend(100))
    s.prepare()
    sigs = s._ema_crossover_signals()
    assert isinstance(sigs, list)
    print(f"  [OK] test_ema_cross_returns_list  ({len(sigs)} sinais)")


def test_ema_cross_signal_structure():
    """Cada sinal deve ter os campos obrigatorios."""
    s = _make_strategy(_uptrend(150))
    s.prepare()
    sigs = s._ema_crossover_signals()
    required = {"data", "tipo", "preco", "stop_loss", "preco_alvo",
                "estrategia", "forca"}
    for sig in sigs:
        assert required <= set(sig.keys()), f"Campos ausentes: {required - set(sig.keys())}"
        assert sig["estrategia"] == "EMA_Cross"
        assert sig["tipo"] in ("Compra", "Venda")
    print(f"  [OK] test_ema_cross_signal_structure  ({len(sigs)} sinais)")


def test_ema_cross_long_in_uptrend():
    """Serie down->up gera golden cross: deve haver pelo menos um sinal de Compra."""
    s = _make_strategy(_down_then_up(300, seed=1))
    s.prepare()
    sigs = s._ema_crossover_signals()
    buys = [sg for sg in sigs if sg["tipo"] == "Compra"]
    assert len(buys) >= 1, f"Esperado >=1 Compra (golden cross), obteve {len(buys)}"
    print(f"  [OK] test_ema_cross_long_in_uptrend  ({len(buys)} Compras)")


def test_ema_cross_short_in_downtrend():
    """Serie up->down gera death cross: deve haver pelo menos um sinal de Venda."""
    s = _make_strategy(_up_then_down(300, seed=2))
    s.prepare()
    sigs = s._ema_crossover_signals()
    sells = [sg for sg in sigs if sg["tipo"] == "Venda"]
    assert len(sells) >= 1, f"Esperado >=1 Venda (death cross), obteve {len(sells)}"
    print(f"  [OK] test_ema_cross_short_in_downtrend  ({len(sells)} Vendas)")


def test_ema_cross_stop_and_target_consistent():
    """Stop/alvo devem ser do lado correto em relação ao preço."""
    s = _make_strategy(_uptrend(150))
    s.prepare()
    for sig in s._ema_crossover_signals():
        if sig["tipo"] == "Compra":
            assert sig["stop_loss"] < sig["preco"], \
                f"Long: stop {sig['stop_loss']:.0f} deveria < preco {sig['preco']:.0f}"
            assert sig["preco_alvo"] > sig["preco"], \
                f"Long: alvo {sig['preco_alvo']:.0f} deveria > preco {sig['preco']:.0f}"
        else:
            assert sig["stop_loss"] > sig["preco"]
            assert sig["preco_alvo"] < sig["preco"]
    print("  [OK] test_ema_cross_stop_and_target_consistent")


def test_ema_cross_respects_allow_long_false():
    s = _make_strategy(_uptrend(150), allow_long=False)
    s.prepare()
    sigs = s._ema_crossover_signals()
    assert all(sg["tipo"] == "Venda" for sg in sigs)
    print(f"  [OK] test_ema_cross_respects_allow_long_false  ({len(sigs)} sinais)")


def test_ema_cross_strength_configurable():
    s = _make_strategy(_uptrend(150), ensemble_signal_strength=9)
    s.prepare()
    sigs = s._ema_crossover_signals()
    assert all(sg["forca"] == 9 for sg in sigs)
    print("  [OK] test_ema_cross_strength_configurable")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — Breakout
# ─────────────────────────────────────────────────────────────────────────────

def test_breakout_returns_list():
    s = _make_strategy(_uptrend(150))
    s.prepare()
    sigs = s._breakout_signals()
    assert isinstance(sigs, list)
    print(f"  [OK] test_breakout_returns_list  ({len(sigs)} sinais)")


def test_breakout_signal_structure():
    s = _make_strategy(_uptrend(150))
    s.prepare()
    sigs = s._breakout_signals()
    required = {"data", "tipo", "preco", "stop_loss", "preco_alvo",
                "estrategia", "forca"}
    for sig in sigs:
        assert required <= set(sig.keys())
        assert sig["estrategia"] == "Breakout"
    print(f"  [OK] test_breakout_signal_structure  ({len(sigs)} sinais)")


def test_breakout_long_in_uptrend():
    s = _make_strategy(_uptrend(200, seed=42))
    s.prepare()
    sigs = s._breakout_signals()
    buys = [sg for sg in sigs if sg["tipo"] == "Compra"]
    assert len(buys) >= 1, f"Uptrend deveria gerar >=1 breakout compra"
    print(f"  [OK] test_breakout_long_in_uptrend  ({len(buys)} Compras)")


def test_breakout_short_in_downtrend():
    s = _make_strategy(_downtrend(200, seed=43))
    s.prepare()
    sigs = s._breakout_signals()
    sells = [sg for sg in sigs if sg["tipo"] == "Venda"]
    assert len(sells) >= 1
    print(f"  [OK] test_breakout_short_in_downtrend  ({len(sells)} Vendas)")


def test_breakout_window_affects_count():
    """Janela menor -> mais breakouts (nivel de resistencia mais baixo)."""
    s_small = _make_strategy(_uptrend(200, seed=5), ensemble_breakout_window=5)
    s_large = _make_strategy(_uptrend(200, seed=5), ensemble_breakout_window=40)
    s_small.prepare(); s_large.prepare()
    n_small = len(s_small._breakout_signals())
    n_large = len(s_large._breakout_signals())
    assert n_small >= n_large, \
        f"Janela menor deveria gerar mais sinais: {n_small} vs {n_large}"
    print(f"  [OK] test_breakout_window_affects_count  (w5={n_small}, w40={n_large})")


def test_breakout_stop_target_side():
    s = _make_strategy(_uptrend(200))
    s.prepare()
    for sig in s._breakout_signals():
        if sig["tipo"] == "Compra":
            assert sig["stop_loss"] < sig["preco"]
            assert sig["preco_alvo"] > sig["preco"]
        else:
            assert sig["stop_loss"] > sig["preco"]
            assert sig["preco_alvo"] < sig["preco"]
    print("  [OK] test_breakout_stop_target_side")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — Ensemble integrado com generate_signals
# ─────────────────────────────────────────────────────────────────────────────

def test_ensemble_disabled_by_default():
    """use_ensemble=False (default) => mesmo resultado que sem ensemble."""
    df = _uptrend(150)
    s_off = _make_strategy(df.copy(), use_ensemble=False)
    s_def = _make_strategy(df.copy())  # default False
    sigs_off = s_off.generate_signals()
    sigs_def = s_def.generate_signals()
    assert len(sigs_off) == len(sigs_def)
    print(f"  [OK] test_ensemble_disabled_by_default  ({len(sigs_off)} sinais)")


def test_ensemble_increases_signal_count():
    """Ensemble ON deve gerar igual ou mais sinais que OFF."""
    df = _uptrend(200, seed=99)
    s_off = _make_strategy(df.copy(), use_ensemble=False)
    s_on  = _make_strategy(df.copy(), use_ensemble=True,
                            ensemble_ema_cross=True, ensemble_breakout=True)
    n_off = len(s_off.generate_signals())
    n_on  = len(s_on.generate_signals())
    assert n_on >= n_off, f"Ensemble ON ({n_on}) deveria >= OFF ({n_off})"
    print(f"  [OK] test_ensemble_increases_signal_count  ({n_off} -> {n_on})")


def test_ensemble_only_ema_cross():
    """ensemble_breakout=False => so EMA cross adicionado."""
    df = _uptrend(200)
    s_all = _make_strategy(df.copy(), use_ensemble=True,
                            ensemble_ema_cross=True, ensemble_breakout=True)
    s_ema = _make_strategy(df.copy(), use_ensemble=True,
                            ensemble_ema_cross=True, ensemble_breakout=False)
    sigs_all = s_all.generate_signals()
    sigs_ema = s_ema.generate_signals()
    # Apenas EMA cross deve ter menos ou igual ao combinado
    assert len(sigs_ema) <= len(sigs_all), \
        f"So EMA ({len(sigs_ema)}) deveria <= todos ({len(sigs_all)})"
    print(f"  [OK] test_ensemble_only_ema_cross  (ema={len(sigs_ema)}, all={len(sigs_all)})")


def test_ensemble_respects_dedup():
    """Nenhum par (data, tipo) duplicado na saida final."""
    df = _uptrend(200)
    s = _make_strategy(df, use_ensemble=True,
                        ensemble_ema_cross=True, ensemble_breakout=True)
    sigs = s.generate_signals()
    keys = [(sg["data"], sg["tipo"]) for sg in sigs]
    assert len(keys) == len(set(keys)), "Sinais duplicados encontrados apos dedup"
    print(f"  [OK] test_ensemble_respects_dedup  ({len(sigs)} sinais unicos)")


def test_ensemble_with_regime_filter():
    """Ensemble + regime filter: sinais devem passar pelos dois filtros."""
    df = _uptrend(300, seed=7)
    s_nofilter = _make_strategy(df.copy(), use_ensemble=True,
                                 use_regime_filter=False)
    s_filtered = _make_strategy(df.copy(), use_ensemble=True,
                                 use_regime_filter=True,
                                 adx_threshold=25.0, hurst_threshold=0.50)
    n_nf = len(s_nofilter.generate_signals())
    n_f  = len(s_filtered.generate_signals())
    assert n_f <= n_nf, \
        f"Com regime filter ({n_f}) deveria <= sem ({n_nf})"
    print(f"  [OK] test_ensemble_with_regime_filter  ({n_nf} -> {n_f})")


def test_ensemble_strategies_labeled():
    """Todos os sinais do ensemble devem ter estrategia identificada."""
    df = _uptrend(200)
    s = _make_strategy(df, use_ensemble=True,
                        ensemble_ema_cross=True, ensemble_breakout=True)
    for sig in s.generate_signals():
        assert sig.get("estrategia"), f"Sinal sem estrategia: {sig}"
        assert sig["estrategia"] in (
            "EMA_Cross", "Breakout",
            "preco_acao", "sentimento",   # existentes
            "engolfo_alta", "engolfo_baixa", "martelo", "estrela_cadente",
            "doji", "inside_bar",         # price action patterns
        ) or len(sig["estrategia"]) > 0   # qualquer string nao-vazia
    print("  [OK] test_ensemble_strategies_labeled")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all() -> int:
    tests = [
        # EMA crossover
        test_ema_cross_returns_list,
        test_ema_cross_signal_structure,
        test_ema_cross_long_in_uptrend,
        test_ema_cross_short_in_downtrend,
        test_ema_cross_stop_and_target_consistent,
        test_ema_cross_respects_allow_long_false,
        test_ema_cross_strength_configurable,
        # Breakout
        test_breakout_returns_list,
        test_breakout_signal_structure,
        test_breakout_long_in_uptrend,
        test_breakout_short_in_downtrend,
        test_breakout_window_affects_count,
        test_breakout_stop_target_side,
        # Ensemble integrado
        test_ensemble_disabled_by_default,
        test_ensemble_increases_signal_count,
        test_ensemble_only_ema_cross,
        test_ensemble_respects_dedup,
        test_ensemble_with_regime_filter,
        test_ensemble_strategies_labeled,
    ]
    print("=" * 60)
    print("  Suite: Ensemble de Sinais (Sprint-2 passo 3)")
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
