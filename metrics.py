# metrics.py — Métricas de drawdown em base dupla (Sprint 18)
"""Cálculo de drawdown em duas bases — equity total e capital-em-risco (CAR).

Motivação (Bloco I — Auditoria): o MDD reportado sobre o *equity total* inclui
o caixa ocioso (o sistema fica fora do mercado boa parte do tempo), o que dilui
a percepção de risco. O MDD sobre o *capital empregado* (CAR) mede só o dinheiro
efetivamente exposto. As duas bases podem diferir por uma ordem de magnitude.

Função pura: sem I/O, sem ``print``, vetorizada em numpy/pandas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _mdd_and_duration(curve: np.ndarray) -> tuple[float, int]:
    """MDD (% positivo) e duração em barras (pico→vale) de uma curva.

    Retorna ``(0.0, 0)`` quando não há drawdown ou a curva tem < 2 pontos.
    A duração é o número de barras do pico que antecede o vale até o vale.
    """
    n = len(curve)
    if n < 2:
        return 0.0, 0
    peak = np.maximum.accumulate(curve)
    drawdown = curve / peak - 1.0
    trough = int(np.argmin(drawdown))
    mdd = float(abs(drawdown[trough]) * 100.0)
    if mdd == 0.0:
        return 0.0, 0
    # Pico que inicia o drawdown: maior valor até (inclusive) o vale.
    peak_idx = int(np.argmax(curve[: trough + 1]))
    return mdd, int(trough - peak_idx)


def compute_drawdown_dual(
    equity_curve: pd.Series,
    position_value_curve: pd.Series,
) -> dict:
    """Calcula drawdown em duas bases — total e capital-at-risk.

    Parameters
    ----------
    equity_curve : pd.Series
        Valor total da conta a cada barra (caixa livre + posições marcadas a
        mercado). Indexada por timestamp. Não deve conter NaN.
    position_value_curve : pd.Series
        Valor absoluto das posições abertas a cada barra. **Zero quando flat**
        (sem posição). Mesmo índice e mesmo comprimento de ``equity_curve``.

    Returns
    -------
    dict com chaves:
        total_equity_mdd : float
            MDD em % positivo sobre ``equity_curve``. Convenção: ``5.2`` = 5.2%.
            Sempre >= 0.
        capital_at_risk_mdd : float
            MDD em % positivo sobre a curva sintética de "equity por unidade de
            capital empregado" (ver algoritmo abaixo). ``NaN`` se nunca houve
            posição aberta.
        time_in_market_pct : float
            Percentual de barras com ``position_value > 0``, em [0, 100].
        total_equity_mdd_duration_bars : int
            Número de barras do pico ao vale do drawdown de equity total.
            ``0`` se nenhum drawdown.
        capital_at_risk_mdd_duration_bars : int
            Idem para a curva sintética CAR. ``0`` se nunca houve posição.
        mdd_explanation : str
            Texto curto explicando as duas bases, para uso em relatórios.

    Notes
    -----
    Algoritmo CAR (multiplicativo — decisão 6.1 do plano do sprint)::

        mask_open = position_value_curve > 0
        car_equity[0] = 1.0
        for i in 1..N-1:
            if mask_open[i] and mask_open[i-1]:           # duas barras consecutivas
                ret = (equity[i] - equity[i-1]) / position_value[i-1]
                car_equity[i] = car_equity[i-1] * (1 + ret)
            else:                                          # flat OU barra de abertura
                car_equity[i] = car_equity[i-1]
        capital_at_risk_mdd = abs((car_equity / car_equity.cummax() - 1).min()) * 100

    Convenção (explícita — não silenciosa):
        - **Flat = 0.0**; a máscara de "em mercado" é ``position_value > 0``.
        - Drawdown sempre reportado como número **positivo**.
        - A curva CAR só avança com posição aberta em **duas barras consecutivas**.
          Logo o PnL da **barra de abertura** de cada trade *não entra* na CAR
          (a barra de abertura apenas carrega o nível; precisa-se da barra
          anterior já em mercado para medir um recuo). Simétrico ao tratamento de
          short abaixo.
        - **Short**: o ``position_value`` é o módulo do nominal exposto; o PnL
          atribuído à barra usa ``equity[i] - equity[i-1]``, que já reflete o
          sinal correto do short. Um short lucrativo ainda exibe recuos
          intermediários, capturados pela CAR.
        - ``capital_at_risk_mdd`` é ``NaN`` apenas quando **nunca** houve posição;
          se houve posição mas sem recuo, é ``0.0``.

    Exemplo numérico (holding de 2 barras, coerente com a regra das duas barras
    consecutivas — uma versão de 1 barra daria CAR=0, pois a barra de abertura
    não entra na CAR)::

        Long R$ 50k; abre na barra 1, ação cai 10% na barra 2, fecha na barra 3:
        equity_curve         = [100k, 100k,  90k,  90k]
        position_value_curve = [   0,  50k,  50k,    0]
        total_equity_mdd     = 10.0%   (90k vs 100k)
        capital_at_risk_mdd  = 20.0%   (ret barra 2 = -10k / 50k = -20%)

    Raises
    ------
    ValueError
        Se os índices das séries diferirem ou os comprimentos não baterem.
    """
    eq = (
        equity_curve
        if isinstance(equity_curve, pd.Series)
        else pd.Series(equity_curve, dtype=float)
    )
    pv = (
        position_value_curve
        if isinstance(position_value_curve, pd.Series)
        else pd.Series(position_value_curve, dtype=float)
    )

    if len(eq) != len(pv):
        raise ValueError(
            f"comprimentos diferentes: equity_curve={len(eq)}, "
            f"position_value_curve={len(pv)}"
        )
    if not eq.index.equals(pv.index):
        raise ValueError("equity_curve e position_value_curve têm índices diferentes")

    eq_vals = eq.to_numpy(dtype=float)
    pv_vals = pv.to_numpy(dtype=float)
    n = len(eq_vals)

    # ── Base 1: equity total ──────────────────────────────────────────────
    total_mdd, total_dur = _mdd_and_duration(eq_vals)

    # ── Tempo em mercado ──────────────────────────────────────────────────
    mask_open = pv_vals > 0.0
    time_in_market_pct = float(mask_open.mean() * 100.0) if n > 0 else 0.0

    # ── Base 2: capital-em-risco (CAR), multiplicativo ────────────────────
    if not mask_open.any():
        car_mdd: float = float("nan")
        car_dur = 0
    else:
        # both[i] = posição aberta na barra i E na barra i-1 (duas consecutivas).
        both = np.zeros(n, dtype=bool)
        both[1:] = mask_open[1:] & mask_open[:-1]

        delta = np.zeros(n, dtype=float)
        delta[1:] = eq_vals[1:] - eq_vals[:-1]
        pv_prev = np.zeros(n, dtype=float)
        pv_prev[1:] = pv_vals[:-1]

        # Onde both é False, o retorno é 0 (nível carregado). Onde both é True,
        # pv_prev > 0 por construção (mask_open[i-1] verdadeiro), então a divisão
        # é segura; o errstate só silencia o 0/0 dos ramos descartados pelo where.
        with np.errstate(divide="ignore", invalid="ignore"):
            ret = np.where(both, delta / pv_prev, 0.0)
        car_equity = np.cumprod(1.0 + ret)
        car_mdd, car_dur = _mdd_and_duration(car_equity)

    # ── Texto explicativo p/ relatórios ───────────────────────────────────
    car_txt = "N/A (nunca operou)" if np.isnan(car_mdd) else f"{car_mdd:.2f}%"
    mdd_explanation = (
        f"MDD equity total {total_mdd:.2f}% (caixa + posições, {total_dur} barras); "
        f"MDD capital-em-risco {car_txt} (só capital exposto, {car_dur} barras); "
        f"tempo em mercado {time_in_market_pct:.1f}%."
    )

    return {
        "total_equity_mdd": total_mdd,
        "capital_at_risk_mdd": car_mdd,
        "time_in_market_pct": time_in_market_pct,
        "total_equity_mdd_duration_bars": total_dur,
        "capital_at_risk_mdd_duration_bars": car_dur,
        "mdd_explanation": mdd_explanation,
    }
