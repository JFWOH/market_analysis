"""
tests/unit/test_cost_sensitivity.py — Sprint 19 (E4).

Testa o núcleo de sensibilidade a custos (scripts/cost_sensitivity.py):
`cost_sensitivity_sweep`, `find_breakeven_slippage` e as visualizações.

Determinístico e SEM rede: usa o seam `strategy_factory` para injetar uma
MockStrategy com sinais controlados (blocos de 4 barras; um pico por trade decide
win/loss). Stops simétricos (mesma distância) → sizing igual entre win e loss, de
modo que o Profit Factor responde de forma limpa ao slippage adverso.

Executável diretamente:
    python tests/unit/test_cost_sensitivity.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.cost_sensitivity import (
    cost_sensitivity_sweep,
    find_breakeven_slippage,
    plot_degradation_curve,
    plot_pf_heatmap,
    plot_sharpe_heatmap,
)

_P = 100_000.0


class _MockStrategy:
    """Estratégia mínima: sinais fixos, sem rede."""

    def __init__(self, data, signals, params=None):
        self.data = data
        self._signals = signals
        self.params = params or {"max_position_pct": 0.5, "max_risk_pct": 0.01}
        self.name = "MOCK"

    def prepare(self):
        pass

    def generate_signals(self):
        return list(self._signals)


def _series(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    arr = np.array(closes, dtype=float)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open": arr * 0.999, "High": arr * 1.005, "Low": arr * 0.995,
        "Close": arr, "Volume": np.full(n, 10_000.0), "ATR": arr * 0.02,
    }, index=idx)


def _build(specs):
    """specs: lista de tuplas (kind, stop_m[, target_m]) com kind in {"win","loss"}.

    `stop_m` é a distância do stop (define o sizing, igual entre win/loss quando
    igual). `target_m` (default = stop_m) é a margem do alvo do winner.

    win  → pico para CIMA atinge alvo a +target_m; stop a -stop_m NÃO é tocado
           porque a barra do pico tem Low elevado → sizing usa stop_m.
    loss → pico para BAIXO toca o stop a -stop_m; alvo distante não é tocado.
    Retorna (data, strategy_factory).
    """
    closes = [_P, _P]            # padding (barras 0,1)
    meta = []                   # (entry_bar, stop_off, target_off)
    for spec in specs:
        kind, stop_m = spec[0], spec[1]
        target_m = spec[2] if len(spec) > 2 else stop_m
        entry_bar = len(closes)
        stop_off = _P * stop_m
        if kind == "win":
            spike = _P * (1.0 + target_m + 0.01)   # sobe além do alvo
            target_off = _P * target_m
        else:
            spike = _P * (1.0 - stop_m - 0.01)     # desce além do stop
            target_off = _P * 0.03                 # alvo distante (não tocado)
        closes += [_P, spike, _P, _P]       # entrada, pico(saída), settle, settle
        meta.append((entry_bar, stop_off, target_off))
    closes += [_P, _P]

    data = _series(closes)
    signals = []
    for entry_bar, stop_off, target_off in meta:
        pp = float(data["Close"].iloc[entry_bar])
        signals.append({
            "data": data.index[entry_bar], "tipo": "Compra", "preco": pp,
            "stop_loss": pp - stop_off, "preco_alvo": pp + target_off,
            "estrategia": "mock",
        })

    def factory(d):
        return _MockStrategy(d, signals)

    return data, factory


# ──────────────────────────────────────────────────────────────────────────────
# 1. Estratégia perdedora → breakeven NaN
# ──────────────────────────────────────────────────────────────────────────────

def test_losing_strategy_breakeven_nan():
    """Só perdas (PF=0 mesmo no slip mínimo) → breakeven_slippage é NaN."""
    data, factory = _build([("loss", 0.006)] * 3)
    res = find_breakeven_slippage({}, data, commission=0.001,
                                  strategy_factory=factory)
    assert np.isnan(res["breakeven_slippage"])
    assert res["converged"] is False
    print("  [OK] test_losing_strategy_breakeven_nan")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Estratégia robusta (edge enorme) → breakeven alto (> 0.005)
# ──────────────────────────────────────────────────────────────────────────────

def test_robust_strategy_high_breakeven():
    """Só vitórias gordas (margem 5%) → PF sobrevive a toda a faixa →
    breakeven_slippage > 0.005."""
    data, factory = _build([("win", 0.05)] * 3)
    res = find_breakeven_slippage({}, data, commission=0.001,
                                  slip_search_range=(0.0001, 0.01),
                                  strategy_factory=factory)
    assert res["breakeven_slippage"] > 0.005
    print(f"  [OK] test_robust_strategy_high_breakeven  (be={res['breakeven_slippage']})")


# ──────────────────────────────────────────────────────────────────────────────
# 3. Monotonia: PF não-cresce com slippage (comissão fixa)
# ──────────────────────────────────────────────────────────────────────────────

def test_pf_monotonic_decreasing_in_slippage():
    """Com comissão fixa, PF é monotonicamente não-crescente em slippage."""
    data, factory = _build([("win", 0.006)] * 3 + [("loss", 0.006)] * 2)
    slip_grid = [0.0005, 0.001, 0.002, 0.003, 0.005]
    df = cost_sensitivity_sweep({}, data, comm_grid=[0.001], slip_grid=slip_grid,
                                strategy_factory=factory)
    df = df.sort_values("slip")
    pfs = df["pf"].to_numpy()
    for a, b in zip(pfs[:-1], pfs[1:]):
        assert b <= a + 1e-9, f"PF subiu com slippage: {a} -> {b}"
    print(f"  [OK] test_pf_monotonic_decreasing_in_slippage  (pf={pfs})")


# ──────────────────────────────────────────────────────────────────────────────
# 4. Idempotência: mesma entrada → mesmo resultado
# ──────────────────────────────────────────────────────────────────────────────

def test_idempotent_same_seed():
    """Duas corridas com a mesma entrada produzem DataFrames idênticos."""
    data, factory = _build([("win", 0.006)] * 2 + [("loss", 0.006)])
    df1 = cost_sensitivity_sweep({}, data, comm_grid=[0.0005, 0.001],
                                 slip_grid=[0.0005, 0.002], strategy_factory=factory)
    df2 = cost_sensitivity_sweep({}, data, comm_grid=[0.0005, 0.001],
                                 slip_grid=[0.0005, 0.002], strategy_factory=factory)
    assert df1.equals(df2)
    print("  [OK] test_idempotent_same_seed")


# ──────────────────────────────────────────────────────────────────────────────
# 5. Shape correto do grid sweep
# ──────────────────────────────────────────────────────────────────────────────

def test_sweep_returns_correct_shape():
    """DataFrame shape = (len(comm)*len(slip), 9) com as colunas certas."""
    data, factory = _build([("win", 0.006)] * 2 + [("loss", 0.006)])
    comm_grid = [0.0005, 0.001, 0.002]
    slip_grid = [0.0005, 0.001, 0.002, 0.005]
    df = cost_sensitivity_sweep({}, data, comm_grid=comm_grid, slip_grid=slip_grid,
                                strategy_factory=factory)
    assert df.shape == (len(comm_grid) * len(slip_grid), 9)
    assert list(df.columns) == [
        "comm", "slip", "pf", "sharpe", "win_rate", "num_trades",
        "total_return_pct", "mdd_total_pct", "mdd_capital_at_risk_pct",
    ]
    print(f"  [OK] test_sweep_returns_correct_shape  (shape={df.shape})")


# ──────────────────────────────────────────────────────────────────────────────
# 6. Defaults respeitados quando grids são None
# ──────────────────────────────────────────────────────────────────────────────

def test_defaults_used_when_grids_none():
    """comm_grid/slip_grid None → usa os defaults da spec (4×5 = 20 linhas)."""
    data, factory = _build([("win", 0.006)] * 2 + [("loss", 0.006)])
    df = cost_sensitivity_sweep({}, data, comm_grid=None, slip_grid=None,
                                strategy_factory=factory)
    assert df.shape == (4 * 5, 9)
    assert sorted(df["comm"].unique()) == [0.0005, 0.001, 0.002, 0.005]
    assert sorted(df["slip"].unique()) == [0.0005, 0.001, 0.002, 0.003, 0.005]
    print("  [OK] test_defaults_used_when_grids_none")


# ──────────────────────────────────────────────────────────────────────────────
# 7. Custo zero é o melhor PF do grid
# ──────────────────────────────────────────────────────────────────────────────

def test_zero_cost_is_best():
    """PF em (comm=0, slip=0) é o maior do grid (custos só pioram)."""
    data, factory = _build([("win", 0.006)] * 3 + [("loss", 0.006)] * 2)
    df = cost_sensitivity_sweep({}, data, comm_grid=[0.0, 0.001, 0.003],
                                slip_grid=[0.0, 0.002, 0.005], strategy_factory=factory)
    pf00 = float(df[(df["comm"] == 0.0) & (df["slip"] == 0.0)]["pf"].iloc[0])
    assert pf00 >= np.nanmax(df["pf"].to_numpy()) - 1e-9
    print(f"  [OK] test_zero_cost_is_best  (pf00={pf00})")


# ──────────────────────────────────────────────────────────────────────────────
# 8. Convergência da busca binária (< 30 iterações)
# ──────────────────────────────────────────────────────────────────────────────

def test_breakeven_converges_under_30_iter():
    """Cruzamento dentro da faixa → busca binária converge em < 30 iterações."""
    # Wins gordos (alvo 1.2%) com stop e sizing iguais aos losses (stop 0.6%):
    # PF > 1 no slip mínimo e cai abaixo de 1 conforme o slippage corrói o alvo.
    data, factory = _build([("win", 0.006, 0.012)] * 3 + [("loss", 0.006)] * 2)
    res = find_breakeven_slippage({}, data, commission=0.001,
                                  slip_search_range=(0.0001, 0.01),
                                  strategy_factory=factory)
    assert res["converged"] is True
    assert res["num_iterations"] < 30
    assert 0.0001 < res["breakeven_slippage"] < 0.01
    print(f"  [OK] test_breakeven_converges_under_30_iter  "
          f"(be={res['breakeven_slippage']:.5f}, iters={res['num_iterations']})")


# ──────────────────────────────────────────────────────────────────────────────
# Smoke tests das visualizações (E3) — geram PNG em diretório temporário.
# (Adições além dos 8 da spec, p/ cobertura do código de plotagem.)
# ──────────────────────────────────────────────────────────────────────────────

def test_viz_outputs_created():
    """As 3 visualizações geram arquivos PNG legíveis."""
    data, factory = _build([("win", 0.006)] * 3 + [("loss", 0.006)] * 2)
    df = cost_sensitivity_sweep({}, data, comm_grid=[0.0005, 0.001],
                                slip_grid=[0.0005, 0.002, 0.005], strategy_factory=factory)
    with tempfile.TemporaryDirectory() as d:
        p1 = plot_pf_heatmap(df, os.path.join(d, "pf.png"), title="t")
        p2 = plot_sharpe_heatmap(df, os.path.join(d, "sharpe.png"))
        p3 = plot_degradation_curve(df, os.path.join(d, "deg.png"),
                                    comm_fixed=0.0005, breakeven_slip=0.002)
        for p in (p1, p2, p3):
            assert os.path.exists(p) and os.path.getsize(p) > 0
    print("  [OK] test_viz_outputs_created")


# ──────────────────────────────────────────────────────────────────────────────
# Runner standalone
# ──────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_losing_strategy_breakeven_nan,
    test_robust_strategy_high_breakeven,
    test_pf_monotonic_decreasing_in_slippage,
    test_idempotent_same_seed,
    test_sweep_returns_correct_shape,
    test_defaults_used_when_grids_none,
    test_zero_cost_is_best,
    test_breakeven_converges_under_30_iter,
    test_viz_outputs_created,
]


def run_all() -> bool:
    passed = failed = 0
    print(f"\n{'='*60}")
    print("  Suite: cost_sensitivity/ — sensibilidade a custos (Sprint 19)")
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
