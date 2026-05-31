"""
tests/unit/test_metrics.py — Testes de ``metrics.compute_drawdown_dual``.

Sprint 18 (E3): drawdown em base dupla (equity total + capital-em-risco).

Todos os casos são determinísticos (curvas analíticas, sem RNG). As séries são
construídas à mão e os resultados esperados calculados manualmente nos comentários.

Executável diretamente:
    python tests/unit/test_metrics.py
"""

from __future__ import annotations

import math
import os
import sys
import traceback

import numpy as np
import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from metrics import compute_drawdown_dual

# ──────────────────────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────────────────────


def _mk(equity: list[float], position_value: list[float]) -> tuple[pd.Series, pd.Series]:
    """Constrói (equity_curve, position_value_curve) com índice datetime comum."""
    assert len(equity) == len(position_value)
    idx = pd.date_range("2023-01-02", periods=len(equity), freq="B")
    return (
        pd.Series(equity, index=idx, dtype=float),
        pd.Series(position_value, index=idx, dtype=float),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. Always-long sem caixa ocioso → as duas bases coincidem
# ──────────────────────────────────────────────────────────────────────────────


def test_always_long_equals_both_mdds():
    """Zero caixa ocioso (equity == position_value em TODAS as barras) →
    total_equity_mdd == capital_at_risk_mdd; time_in_market == 100%.

    Ajuste #1: a igualdade só vale sem caixa ocioso. Com position_value idêntico
    a equity em toda barra, a curva CAR (normalizada por equity[0]) tem a mesma
    forma de drawdown que a equity total.
    """
    eq = [100.0, 110.0, 90.0, 95.0, 105.0]
    eq_s, pv_s = _mk(eq, eq)  # position_value == equity em toda barra

    m = compute_drawdown_dual(eq_s, pv_s)

    # Vale na barra 2: 90/110 - 1 = -18.1818%  → mesma forma nas duas bases
    assert m["total_equity_mdd"] == pytest.approx(m["capital_at_risk_mdd"], abs=1e-9)
    assert m["total_equity_mdd"] == pytest.approx(18.18181818, abs=1e-6)
    assert m["time_in_market_pct"] == pytest.approx(100.0)
    print("  [OK] test_always_long_equals_both_mdds")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Nunca opera → CAR é NaN
# ──────────────────────────────────────────────────────────────────────────────


def test_never_opens_car_is_nan():
    """position_value sempre 0 → total_mdd calculado normalmente, capital_at_risk_mdd
    é NaN (nunca operou — decisão 6.1), time_in_market == 0%."""
    eq_s, pv_s = _mk([100.0, 95.0, 105.0], [0.0, 0.0, 0.0])

    m = compute_drawdown_dual(eq_s, pv_s)

    assert m["total_equity_mdd"] == pytest.approx(5.0)  # 95/100 - 1
    assert math.isnan(m["capital_at_risk_mdd"])
    assert m["capital_at_risk_mdd_duration_bars"] == 0
    assert m["time_in_market_pct"] == pytest.approx(0.0)
    print("  [OK] test_never_opens_car_is_nan")


# ──────────────────────────────────────────────────────────────────────────────
# 3. Metade do capital exposto na queda → CAR ≈ 2× total (tese central)
# ──────────────────────────────────────────────────────────────────────────────


def test_half_time_losing_car_doubles_total():
    """Posição (50k) aberta nas barras 1-2; equity cai de 100k→90k na barra 2.
    A queda atinge só metade do capital (50k de 100k) → CAR ≈ 2× o MDD total.

    equity = [100, 100, 90, 90] ; position_value = [0, 50, 50, 0]
    total: vale 90/100-1 = -10%
    CAR:   ret barra 2 = (90-100)/50 = -20%
    """
    eq_s, pv_s = _mk([100.0, 100.0, 90.0, 90.0], [0.0, 50.0, 50.0, 0.0])

    m = compute_drawdown_dual(eq_s, pv_s)

    assert m["total_equity_mdd"] == pytest.approx(10.0)
    assert m["capital_at_risk_mdd"] == pytest.approx(20.0)
    assert m["capital_at_risk_mdd"] == pytest.approx(2.0 * m["total_equity_mdd"])
    assert m["time_in_market_pct"] == pytest.approx(50.0)
    print("  [OK] test_half_time_losing_car_doubles_total")


# ──────────────────────────────────────────────────────────────────────────────
# 4. 50% em mercado, ganho no fim, mas dip intra-trade → CAR relativo > equity
# ──────────────────────────────────────────────────────────────────────────────


def test_half_time_winning_asymmetric():
    """Trade vencedor no agregado (108 > 100) mas com dip intermediário. O MDD
    relativo sobre o capital exposto excede o MDD sobre a equity inteira.

    equity = [100, 100, 98, 108] ; position_value = [0, 40, 40, 0]
    total: vale 98/100-1 = -2%
    CAR:   ret barra 2 = (98-100)/40 = -5%
    """
    eq_s, pv_s = _mk([100.0, 100.0, 98.0, 108.0], [0.0, 40.0, 40.0, 0.0])

    m = compute_drawdown_dual(eq_s, pv_s)

    assert m["total_equity_mdd"] == pytest.approx(2.0)
    assert m["capital_at_risk_mdd"] == pytest.approx(5.0)
    assert m["capital_at_risk_mdd"] > m["total_equity_mdd"]
    assert eq_s.iloc[-1] > eq_s.iloc[0]  # trade vencedor no agregado
    assert m["time_in_market_pct"] == pytest.approx(50.0)
    print("  [OK] test_half_time_winning_asymmetric")


# ──────────────────────────────────────────────────────────────────────────────
# 5. Short lucrativo, mas com recuo intermediário capturado pela CAR
# ──────────────────────────────────────────────────────────────────────────────


def test_short_position_profitable_drawdown():
    """Short lucrativo no agregado (equity 100→105) com recuo adverso na barra 2.
    O position_value é o módulo da exposição; a CAR captura o recuo intermediário.

    equity = [100, 100, 97, 105, 105] ; position_value = [0, 60, 60, 60, 0]
    total: vale 97/100-1 = -3%
    CAR:   ret barra 2 = (97-100)/60 = -5%  → car_equity 1→0.95
           ret barra 3 = (105-97)/60 = +13.33% → recupera (sem novo vale)
    """
    eq_s, pv_s = _mk(
        [100.0, 100.0, 97.0, 105.0, 105.0], [0.0, 60.0, 60.0, 60.0, 0.0]
    )

    m = compute_drawdown_dual(eq_s, pv_s)

    assert m["total_equity_mdd"] == pytest.approx(3.0)
    assert m["capital_at_risk_mdd"] == pytest.approx(5.0)
    assert eq_s.iloc[-1] > eq_s.iloc[0]  # short lucrativo
    print("  [OK] test_short_position_profitable_drawdown")


# ──────────────────────────────────────────────────────────────────────────────
# 6. Partial exit: position_value cai à metade sem criar drawdown espúrio
# ──────────────────────────────────────────────────────────────────────────────


def test_partial_exit_position_value_halves():
    """A redução de position_value no partial (50k→25k) NÃO é uma perda e não pode
    gerar drawdown espúrio (a CAR usa Δequity, não Δposition_value). Após o partial,
    um recuo real é contado sobre a base menor.

    equity         = [100, 100, 104, 104, 100, 100]
    position_value = [  0,  50,  50,  25,  25,   0]   # partial na barra 3
    Barra 4 (recuo real): ret = (100-104)/25 = -16%  → CAR = 16%
    total: vale 100/104-1 = -3.846%
    """
    eq_s, pv_s = _mk(
        [100.0, 100.0, 104.0, 104.0, 100.0, 100.0],
        [0.0, 50.0, 50.0, 25.0, 25.0, 0.0],
    )

    m = compute_drawdown_dual(eq_s, pv_s)

    assert m["capital_at_risk_mdd"] == pytest.approx(16.0)
    assert m["total_equity_mdd"] == pytest.approx(3.84615384, abs=1e-6)
    assert m["capital_at_risk_mdd"] > m["total_equity_mdd"]
    print("  [OK] test_partial_exit_position_value_halves")


# ──────────────────────────────────────────────────────────────────────────────
# 7. Gap overnight: salto de equity sem variação proporcional de position_value
# ──────────────────────────────────────────────────────────────────────────────


def test_gap_overnight_handled():
    """Salto grande de equity (gap) não pode produzir NaN/inf na CAR.

    equity = [100, 100, 130, 128, 128] ; position_value = [0, 50, 50, 50, 0]
    ret barra 2 = (130-100)/50 = +60%  → sem vale
    ret barra 3 = (128-130)/50 = -4%   → CAR = 4%
    """
    eq_s, pv_s = _mk(
        [100.0, 100.0, 130.0, 128.0, 128.0], [0.0, 50.0, 50.0, 50.0, 0.0]
    )

    m = compute_drawdown_dual(eq_s, pv_s)

    assert math.isfinite(m["capital_at_risk_mdd"])
    assert m["capital_at_risk_mdd"] == pytest.approx(4.0)
    assert math.isfinite(m["total_equity_mdd"])
    print("  [OK] test_gap_overnight_handled")


# ──────────────────────────────────────────────────────────────────────────────
# 8. Determinismo: mesma entrada → mesma saída
# ──────────────────────────────────────────────────────────────────────────────


def test_determinismo():
    """Duas chamadas com a mesma entrada retornam dicts idênticos (sem estado
    global). Cobre também a validação de entrada (ValueError)."""
    eq_s, pv_s = _mk([100.0, 100.0, 90.0, 90.0], [0.0, 50.0, 50.0, 0.0])

    m1 = compute_drawdown_dual(eq_s, pv_s)
    m2 = compute_drawdown_dual(eq_s, pv_s)
    assert m1 == m2

    # Validação de contrato: comprimentos e índices precisam bater.
    bad_len_eq, _ = _mk([100.0, 100.0], [0.0, 0.0])
    _, bad_len_pv = _mk([1.0, 2.0, 3.0], [0.0, 0.0, 0.0])
    with pytest.raises(ValueError):
        compute_drawdown_dual(bad_len_eq, bad_len_pv)

    eq_idx = pd.Series([100.0, 100.0], index=pd.date_range("2023-01-02", periods=2, freq="B"))
    pv_idx = pd.Series([0.0, 50.0], index=pd.date_range("2024-06-03", periods=2, freq="B"))
    with pytest.raises(ValueError):
        compute_drawdown_dual(eq_idx, pv_idx)

    print("  [OK] test_determinismo")


# ──────────────────────────────────────────────────────────────────────────────
# 9. Equity constante → ambos MDD == 0 (operou-sem-recuo → 0.0, não NaN)
# ──────────────────────────────────────────────────────────────────────────────


def test_equity_constant_returns_zero():
    """Equity constante com posição aberta → total_mdd == 0 e capital_at_risk_mdd
    == 0.0 (operou, mas sem recuo: é 0.0, não NaN)."""
    eq_s, pv_s = _mk([100.0, 100.0, 100.0, 100.0], [0.0, 50.0, 50.0, 0.0])

    m = compute_drawdown_dual(eq_s, pv_s)

    assert m["total_equity_mdd"] == pytest.approx(0.0)
    assert m["capital_at_risk_mdd"] == pytest.approx(0.0)  # operou-sem-recuo
    assert not math.isnan(m["capital_at_risk_mdd"])
    assert m["total_equity_mdd_duration_bars"] == 0
    assert m["capital_at_risk_mdd_duration_bars"] == 0

    # Edge: série de 1 elemento → sem drawdown possível.
    one_eq, one_pv = _mk([100.0], [50.0])
    m1 = compute_drawdown_dual(one_eq, one_pv)
    assert m1["total_equity_mdd"] == 0.0
    assert m1["capital_at_risk_mdd"] == 0.0
    print("  [OK] test_equity_constant_returns_zero")


# ──────────────────────────────────────────────────────────────────────────────
# 10. position_value fracionário → resultado finito, sem divisão por zero
# ──────────────────────────────────────────────────────────────────────────────


def test_fractional_position_value():
    """position_value em valores fracionários intermediários (scale-down gradual)
    produz resultado finito e bem-definido."""
    eq_s, pv_s = _mk(
        [100.0, 101.0, 99.0, 100.0], [0.0, 33.3, 17.7, 0.0]
    )

    m = compute_drawdown_dual(eq_s, pv_s)

    assert math.isfinite(m["total_equity_mdd"])
    assert math.isfinite(m["capital_at_risk_mdd"])
    # Recuo na barra 2 (em mercado nas barras 1-2): ret = (99-101)/33.3 = -6.006%
    assert m["capital_at_risk_mdd"] == pytest.approx(6.006006, abs=1e-4)
    print("  [OK] test_fractional_position_value")


# ──────────────────────────────────────────────────────────────────────────────
# 11. Caixa ocioso → total_mdd <= car_mdd (coerência matemática)
# ──────────────────────────────────────────────────────────────────────────────


def test_total_mdd_le_car_when_cash_idle():
    """Com caixa ocioso, a base menor (capital exposto) amplifica o drawdown:
    total_equity_mdd <= capital_at_risk_mdd (até tolerância)."""
    eq_s, pv_s = _mk(
        [100.0, 100.0, 95.0, 92.0, 92.0], [0.0, 40.0, 40.0, 40.0, 0.0]
    )

    m = compute_drawdown_dual(eq_s, pv_s)

    assert m["total_equity_mdd"] <= m["capital_at_risk_mdd"] + 1e-9
    print("  [OK] test_total_mdd_le_car_when_cash_idle")


# ──────────────────────────────────────────────────────────────────────────────
# 12. Input de referência com saída calculada à mão
# ──────────────────────────────────────────────────────────────────────────────


def test_reference_input_reproduces_known_output():
    """Input de 6 barras com TODAS as saídas calculadas manualmente.

    equity         = [100, 100,  90,  95,  95, 100]
    position_value = [  0,  50,  50,  50,   0,   0]   # aberto nas barras 1-3

    Equity total:
        peak = [100,100,100,100,100,100]
        dd   = [0, 0, -10%, -5%, -5%, 0]  → MDD = 10% no vale (barra 2)
        duração: pico barra 0 → vale barra 2 = 2 barras

    CAR (both nas barras 2 e 3):
        ret[2] = (90-100)/50 = -20%  → car_equity 1→0.80
        ret[3] = (95-90)/50  = +10%  → car_equity 0.80→0.88
        car_equity = [1, 1, 0.80, 0.88, 0.88, 0.88]
        dd → MDD = 20% no vale (barra 2); duração pico barra 0 → vale barra 2 = 2

    time_in_market = 3/6 = 50%
    """
    eq_s, pv_s = _mk(
        [100.0, 100.0, 90.0, 95.0, 95.0, 100.0], [0.0, 50.0, 50.0, 50.0, 0.0, 0.0]
    )

    m = compute_drawdown_dual(eq_s, pv_s)

    assert m["total_equity_mdd"] == pytest.approx(10.0)
    assert m["capital_at_risk_mdd"] == pytest.approx(20.0)
    assert m["time_in_market_pct"] == pytest.approx(50.0)
    assert m["total_equity_mdd_duration_bars"] == 2
    assert m["capital_at_risk_mdd_duration_bars"] == 2
    assert isinstance(m["mdd_explanation"], str) and m["mdd_explanation"]
    print("  [OK] test_reference_input_reproduces_known_output")


# ──────────────────────────────────────────────────────────────────────────────
# 13. Anti-lookahead (CLAUDE.md §2.2): MDD sobre prefixo é monotônico
# ──────────────────────────────────────────────────────────────────────────────


def test_no_lookahead_prefix_monotonic():
    """O MDD total sobre o prefixo [:k] não pode diminuir ao estender a série —
    um drawdown presente num prefixo permanece presente. Isso demonstra ausência
    de vazamento de informação futura (o cálculo é causal: cummax).
    """
    eq = [100.0, 110.0, 90.0, 95.0, 80.0, 120.0]
    pv = [0.0] * len(eq)  # base total independe de pv; pv flat basta aqui
    eq_s, pv_s = _mk(eq, pv)

    prev = -1.0
    for k in range(2, len(eq) + 1):
        m = compute_drawdown_dual(eq_s.iloc[:k], pv_s.iloc[:k])
        cur = m["total_equity_mdd"]
        assert cur >= prev - 1e-9, f"MDD diminuiu em k={k}: {cur} < {prev}"
        prev = cur

    # Sanidade do valor final: vale 80/110-1 = -27.2727%
    m_full = compute_drawdown_dual(eq_s, pv_s)
    assert m_full["total_equity_mdd"] == pytest.approx(27.27272727, abs=1e-6)
    print("  [OK] test_no_lookahead_prefix_monotonic")


# ──────────────────────────────────────────────────────────────────────────────
# Runner standalone
# ──────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_always_long_equals_both_mdds,
    test_never_opens_car_is_nan,
    test_half_time_losing_car_doubles_total,
    test_half_time_winning_asymmetric,
    test_short_position_profitable_drawdown,
    test_partial_exit_position_value_halves,
    test_gap_overnight_handled,
    test_determinismo,
    test_equity_constant_returns_zero,
    test_fractional_position_value,
    test_total_mdd_le_car_when_cash_idle,
    test_reference_input_reproduces_known_output,
    test_no_lookahead_prefix_monotonic,
]


def run_all() -> bool:
    passed = failed = 0
    print(f"\n{'='*60}")
    print("  Suite: metrics/ — drawdown em base dupla (total + CAR)")
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
