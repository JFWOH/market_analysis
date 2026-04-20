"""
tests/unit/test_dsr_cooldown.py

Testes das otimizações Sprint-1 passos 1 e 2:
    • Deflated Sharpe Ratio (Bailey & López de Prado 2014)
    • Signal Cooldown (silêncio pós-saída contra overtrading)

Executável diretamente:
    python tests/unit/test_dsr_cooldown.py
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

from backtester import Backtester


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

class _MockStrategy:
    """Strategy mínima com sinais pré-programados para testar o backtester."""

    def __init__(self, data: pd.DataFrame, signals: list[dict], name: str = "mock"):
        self.data    = data
        self.name    = name
        self.ticker  = "MOCK"
        self.params  = {
            "max_position_pct": 0.5,
            "max_risk_pct":     0.02,
            "use_trailing_stop": False,
        }
        self._signals = signals

    def prepare(self) -> None:
        # Garante ATR (necessário para backtester)
        if "ATR" not in self.data.columns:
            tr = (self.data["High"] - self.data["Low"]).abs()
            self.data["ATR"] = tr.rolling(5).mean().bfill()

    def generate_signals(self) -> list[dict]:
        return self._signals


def _make_price_series(n: int = 60, start: float = 100.0, step: float = 0.5) -> pd.DataFrame:
    """OHLCV determinístico: preço sobe linearmente para garantir TP alcançável."""
    dates  = pd.date_range("2024-01-01", periods=n, freq="D")
    closes = np.arange(start, start + n * step, step)[:n]
    df = pd.DataFrame({
        "Open":   closes - 0.1,
        "High":   closes + 0.5,
        "Low":    closes - 0.5,
        "Close":  closes,
        "Volume": 1_000_000,
    }, index=dates)
    df.index.name = "Date"
    return df


# ══════════════════════════════════════════════════════════════════════════════
# DSR
# ══════════════════════════════════════════════════════════════════════════════

def test_dsr_returns_probability_in_unit_interval():
    """DSR deve retornar valor entre 0 e 1."""
    dsr = Backtester.deflated_sharpe_ratio(
        sharpe_obs=0.1, n_obs=252, n_trials=10, skew=0.0, kurt=3.0
    )
    assert 0.0 <= dsr <= 1.0, f"DSR fora de [0,1]: {dsr}"
    print("  [OK] test_dsr_returns_probability_in_unit_interval")


def test_dsr_high_sharpe_single_trial_is_confident():
    """Sharpe alto com N=1 trial → DSR deve ser alto (≥ 0.95)."""
    dsr = Backtester.deflated_sharpe_ratio(
        sharpe_obs=0.3,     # forte por período → ~4.7 anualizado em 252
        n_obs=252,
        n_trials=1,
        skew=0.0,
        kurt=3.0,
    )
    assert dsr >= 0.95, f"Esperado DSR >= 0.95, obteve {dsr:.4f}"
    print("  [OK] test_dsr_high_sharpe_single_trial_is_confident")


def test_dsr_same_sharpe_many_trials_is_deflated():
    """Mesmo Sharpe com muitos trials → DSR deve cair significativamente."""
    sr = 0.15
    dsr_1     = Backtester.deflated_sharpe_ratio(sharpe_obs=sr, n_obs=252, n_trials=1)
    dsr_1000  = Backtester.deflated_sharpe_ratio(sharpe_obs=sr, n_obs=252, n_trials=1000)
    assert dsr_1 > dsr_1000, (
        f"DSR com 1 trial ({dsr_1:.3f}) deveria ser > DSR com 1000 ({dsr_1000:.3f})"
    )
    # Deflação deve ser expressiva
    assert (dsr_1 - dsr_1000) > 0.10, (
        f"Deflação insuficiente: {dsr_1:.3f} -> {dsr_1000:.3f}"
    )
    print("  [OK] test_dsr_same_sharpe_many_trials_is_deflated")


def test_dsr_low_sharpe_always_rejected():
    """Sharpe zero ou negativo → DSR deve ficar < 0.5."""
    dsr_zero = Backtester.deflated_sharpe_ratio(sharpe_obs=0.0, n_obs=252, n_trials=100)
    dsr_neg  = Backtester.deflated_sharpe_ratio(sharpe_obs=-0.05, n_obs=252, n_trials=100)
    assert dsr_zero < 0.5, f"Sharpe=0 deveria dar DSR<0.5, obteve {dsr_zero:.3f}"
    assert dsr_neg  < 0.5, f"Sharpe<0 deveria dar DSR<0.5, obteve {dsr_neg:.3f}"
    print("  [OK] test_dsr_low_sharpe_always_rejected")


def test_dsr_monotonic_in_sharpe():
    """DSR deve crescer monotonicamente com o Sharpe observado."""
    dsrs = [
        Backtester.deflated_sharpe_ratio(sharpe_obs=sr, n_obs=252, n_trials=50)
        for sr in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25]
    ]
    for i in range(len(dsrs) - 1):
        assert dsrs[i] <= dsrs[i + 1] + 1e-6, (
            f"DSR não monotônico: posição {i}: {dsrs[i]:.3f} > {dsrs[i+1]:.3f}"
        )
    print("  [OK] test_dsr_monotonic_in_sharpe")


def test_dsr_extreme_inputs_safe():
    """Inputs extremos (n_obs pequeno, n_trials enorme) não devem quebrar."""
    # n_obs < 4 → retorna 0
    assert Backtester.deflated_sharpe_ratio(0.3, n_obs=3, n_trials=1) == 0.0
    # n_trials muito alto
    v = Backtester.deflated_sharpe_ratio(0.1, n_obs=100, n_trials=100_000)
    assert 0.0 <= v <= 1.0
    # Skew/kurt extremos
    v2 = Backtester.deflated_sharpe_ratio(0.1, n_obs=100, n_trials=10, skew=-3.0, kurt=15.0)
    assert 0.0 <= v2 <= 1.0
    print("  [OK] test_dsr_extreme_inputs_safe")


def test_dsr_kurt_penalty():
    """Kurt alto (fat tails) → DSR deve cair vs kurt normal."""
    dsr_normal = Backtester.deflated_sharpe_ratio(
        sharpe_obs=0.15, n_obs=252, n_trials=10, skew=0.0, kurt=3.0
    )
    dsr_fat    = Backtester.deflated_sharpe_ratio(
        sharpe_obs=0.15, n_obs=252, n_trials=10, skew=0.0, kurt=10.0
    )
    assert dsr_fat < dsr_normal, (
        f"Kurt alto deveria reduzir DSR: normal={dsr_normal:.3f} fat={dsr_fat:.3f}"
    )
    print("  [OK] test_dsr_kurt_penalty")


# ══════════════════════════════════════════════════════════════════════════════
# Cooldown
# ══════════════════════════════════════════════════════════════════════════════

def test_cooldown_zero_allows_all_signals():
    """Com cooldown=0, comportamento deve ser idêntico ao antigo."""
    df = _make_price_series(n=40, start=100, step=0.5)
    # Dois sinais de compra em barras próximas
    signals = [
        {
            "data": df.index[5],  "tipo": "Compra", "preco": 100.0,
            "stop_loss": 98.0, "preco_alvo": 105.0,
            "estrategia": "test", "forca": 8,
        },
        {
            "data": df.index[15], "tipo": "Compra", "preco": 105.0,
            "stop_loss": 103.0, "preco_alvo": 110.0,
            "estrategia": "test", "forca": 8,
        },
    ]
    strat = _MockStrategy(df, signals)
    bt = Backtester(strat, initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0,
                    cooldown_bars=0)
    m = bt.run()
    assert m.get("signals_skipped_cooldown", -1) == 0
    assert m["trade_count"] >= 1
    print("  [OK] test_cooldown_zero_allows_all_signals")


def test_cooldown_blocks_signals_within_window():
    """Cooldown grande deve bloquear o 2o sinal se disparar logo após saída."""
    df = _make_price_series(n=40, start=100, step=0.5)
    # Sinal 1: entra em bar 5, alvo baixo para fechar rápido
    # Sinal 2: dispara em bar 8, dentro do cooldown=10
    signals = [
        {
            "data": df.index[5], "tipo": "Compra", "preco": 100.0,
            "stop_loss": 98.0, "preco_alvo": 102.0,  # alvo próximo, fecha cedo
            "estrategia": "test", "forca": 8,
        },
        {
            "data": df.index[8], "tipo": "Compra", "preco": 104.0,
            "stop_loss": 102.0, "preco_alvo": 110.0,
            "estrategia": "test", "forca": 8,
        },
    ]
    strat = _MockStrategy(df, signals)
    bt = Backtester(strat, initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0,
                    cooldown_bars=10)
    m = bt.run()
    assert m.get("signals_skipped_cooldown", 0) >= 1, (
        f"Esperado ≥1 sinal bloqueado pelo cooldown, obteve "
        f"{m.get('signals_skipped_cooldown')}"
    )
    print("  [OK] test_cooldown_blocks_signals_within_window")


def test_cooldown_allows_signals_after_window():
    """Sinal bem depois do cooldown deve ser aceito."""
    df = _make_price_series(n=60, start=100, step=0.5)
    signals = [
        {
            "data": df.index[3], "tipo": "Compra", "preco": 100.0,
            "stop_loss": 98.0, "preco_alvo": 101.5,
            "estrategia": "test", "forca": 8,
        },
        {
            "data": df.index[30], "tipo": "Compra", "preco": 115.0,
            "stop_loss": 113.0, "preco_alvo": 120.0,
            "estrategia": "test", "forca": 8,
        },
    ]
    strat = _MockStrategy(df, signals)
    bt = Backtester(strat, initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0,
                    cooldown_bars=5)
    m = bt.run()
    assert m["trade_count"] == 2, f"Esperado 2 trades, obteve {m['trade_count']}"
    assert m.get("signals_skipped_cooldown", 0) == 0
    print("  [OK] test_cooldown_allows_signals_after_window")


def test_cooldown_config_default():
    """Sem especificar cooldown_bars, deve usar config.SIGNAL_COOLDOWN_BARS."""
    import config as _cfg
    original = getattr(_cfg, "SIGNAL_COOLDOWN_BARS", 0)
    _cfg.SIGNAL_COOLDOWN_BARS = 7

    df = _make_price_series(n=20)
    strat = _MockStrategy(df, [])
    bt = Backtester(strat, initial_capital=100_000.0)
    assert bt.cooldown_bars == 7, (
        f"Esperado cooldown=7 vindo de config, obteve {bt.cooldown_bars}"
    )

    _cfg.SIGNAL_COOLDOWN_BARS = original
    print("  [OK] test_cooldown_config_default")


def test_cooldown_reported_in_metrics():
    """Métricas devem incluir cooldown_bars e signals_skipped_cooldown."""
    df = _make_price_series(n=30)
    strat = _MockStrategy(df, [])
    bt = Backtester(strat, initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0,
                    cooldown_bars=5)
    m = bt.run()
    # Sem trades: métricas dos sinais ainda devem estar presentes
    assert "cooldown_bars" in m
    assert m["cooldown_bars"] == 5
    assert "signals_skipped_cooldown" in m
    print("  [OK] test_cooldown_reported_in_metrics")


def test_cooldown_reduces_trade_count():
    """Cooldown alto deve reduzir nº de trades vs cooldown=0 com mesma série."""
    df = _make_price_series(n=80, start=100, step=0.3)
    # 4 sinais próximos no tempo (sempre após fechamento do anterior)
    signals = []
    for i in [3, 8, 13, 18]:
        signals.append({
            "data": df.index[i], "tipo": "Compra",
            "preco": float(df["Close"].iloc[i]),
            "stop_loss": float(df["Close"].iloc[i]) - 1.0,
            "preco_alvo": float(df["Close"].iloc[i]) + 0.5,  # alvo bem próximo
            "estrategia": "test", "forca": 8,
        })

    strat_no = _MockStrategy(df.copy(), signals)
    bt_no = Backtester(strat_no, initial_capital=100_000.0,
                        commission_per_trade=0.0, slippage_pct=0.0,
                        cooldown_bars=0)
    m_no = bt_no.run()

    strat_cd = _MockStrategy(df.copy(), signals)
    bt_cd = Backtester(strat_cd, initial_capital=100_000.0,
                        commission_per_trade=0.0, slippage_pct=0.0,
                        cooldown_bars=10)
    m_cd = bt_cd.run()

    assert m_cd["trade_count"] <= m_no["trade_count"], (
        f"Cooldown deveria reduzir trades: sem={m_no['trade_count']} "
        f"com={m_cd['trade_count']}"
    )
    print(f"  [OK] test_cooldown_reduces_trade_count  "
          f"(sem={m_no['trade_count']}, com={m_cd['trade_count']})")


# ══════════════════════════════════════════════════════════════════════════════
# Integração — DSR nas métricas do backtest
# ══════════════════════════════════════════════════════════════════════════════

def test_backtest_metrics_include_dsr_inputs():
    """O resultado do backtest deve expor os campos necessários para o DSR."""
    df = _make_price_series(n=40, start=100, step=0.5)
    signals = [{
        "data": df.index[3], "tipo": "Compra", "preco": 100.0,
        "stop_loss": 98.0, "preco_alvo": 110.0,
        "estrategia": "test", "forca": 8,
    }]
    strat = _MockStrategy(df, signals)
    bt = Backtester(strat, initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0,
                    cooldown_bars=0)
    m = bt.run()

    for field in ("sharpe_per_period", "return_skew", "return_kurt", "n_return_obs"):
        assert field in m, f"Campo '{field}' ausente nas métricas"
    assert m["n_return_obs"] > 0
    print("  [OK] test_backtest_metrics_include_dsr_inputs")


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

TESTS = [
    test_dsr_returns_probability_in_unit_interval,
    test_dsr_high_sharpe_single_trial_is_confident,
    test_dsr_same_sharpe_many_trials_is_deflated,
    test_dsr_low_sharpe_always_rejected,
    test_dsr_monotonic_in_sharpe,
    test_dsr_extreme_inputs_safe,
    test_dsr_kurt_penalty,
    test_cooldown_zero_allows_all_signals,
    test_cooldown_blocks_signals_within_window,
    test_cooldown_allows_signals_after_window,
    test_cooldown_config_default,
    test_cooldown_reported_in_metrics,
    test_cooldown_reduces_trade_count,
    test_backtest_metrics_include_dsr_inputs,
]


def run_all() -> int:
    print("\n" + "=" * 60)
    print("  Suite: DSR + Cooldown  (Sprint-1 passos 1 e 2)")
    print("=" * 60)

    passed = failed = 0
    for fn in TESTS:
        try:
            fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"  [FAIL] {fn.__name__}")
            traceback.print_exc()

    total = passed + failed
    print("=" * 60)
    print(f"  Resultado: {passed} passou(aram) / {failed} falhou(aram)")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
