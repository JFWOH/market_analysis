# scripts/cost_sensitivity.py — Sprint 19: sensibilidade a custos de transação
"""Superfície de sensibilidade de custos: para cada (config, ticker), mede como
Profit Factor / Sharpe / MDD degradam ao varrer comissão (%) × slippage (%), e
encontra o **breakeven slippage** (slippage que zera o edge: PF → 1.0).

Natureza: apesar de viver em ``scripts/`` (é um script de análise, como
``bear_market_validation.py``), o núcleo (``cost_sensitivity_sweep`` e
``find_breakeven_slippage``) é **biblioteca** — funções puras, testáveis e sem rede.

Notas de modelagem:
    - O eixo "comissão" usa ``Backtester.commission_pct`` (fracionário, Sprint-19),
      NÃO o ``commission_per_trade`` absoluto (R$ fixo), que é zerado nos sweeps para
      isolar os eixos percentuais (decisão 5 do plano).
    - Custos modelados aqui NÃO capturam impacto de mercado para sizes muito grandes.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtester import Backtester
from strategy import CombinedStrategy

# Grades default (frações; 0.0005 = 0.05%). Ver spec §3/E1.
DEFAULT_COMM_GRID = [0.0005, 0.001, 0.002, 0.005]
DEFAULT_SLIP_GRID = [0.0005, 0.001, 0.002, 0.003, 0.005]

_SWEEP_COLUMNS = [
    "comm", "slip", "pf", "sharpe", "win_rate", "num_trades",
    "total_return_pct", "mdd_total_pct", "mdd_capital_at_risk_pct",
]


def _num(x) -> float:
    """Converte para float, mapeando None/ausente → NaN (preserva inf)."""
    if x is None:
        return float("nan")
    return float(x)


def _run_single_backtest(
    strategy_config: dict,
    data: pd.DataFrame,
    comm: float,
    slip: float,
    initial_capital: float,
    risk_per_trade: float,
    strategy_factory=None,
) -> dict:
    """Roda UM backtest com (comm, slip) e devolve o dict de métricas.

    Caminho de produção (``strategy_factory`` None): reusa o padrão canônico de
    ``bear_market_validation.py`` (CombinedStrategy → set_data → params.update).
    O ``strategy_factory`` é um *seam* só para testes determinísticos — não
    interfere no caminho de produção.
    """
    if strategy_factory is not None:
        strat = strategy_factory(data)
    else:
        strat = CombinedStrategy("SWEEP")
        strat.set_data(data.copy())
        cfg = dict(strategy_config)
        cfg["max_risk_pct"] = risk_per_trade
        strat.params.update(cfg)

    bt = Backtester(
        strat,
        initial_capital=initial_capital,
        commission_per_trade=0.0,   # decisão 5: isola o eixo de comissão percentual
        commission_pct=comm,
        slippage_pct=slip,
        cooldown_bars=2,
    )
    return bt.run()


def cost_sensitivity_sweep(
    strategy_config: dict,
    data: pd.DataFrame,
    comm_grid: list[float] | None = None,
    slip_grid: list[float] | None = None,
    initial_capital: float = 100_000,
    risk_per_trade: float = 0.01,
    strategy_factory=None,
) -> pd.DataFrame:
    """Roda um backtest por combinação (comm × slip) na grade.

    Parameters
    ----------
    strategy_config : dict
        Params a aplicar via ``CombinedStrategy.params.update`` (ex.: SPRINT13_PARAMS).
    data : pd.DataFrame
        OHLCV já recortado para a janela desejada.
    comm_grid, slip_grid : list[float] | None
        Grades de comissão e slippage (frações). None → defaults da spec.
    initial_capital, risk_per_trade : float
        Capital inicial e risco por trade (este entra como ``max_risk_pct``).
    strategy_factory : callable | None
        SEAM de teste: ``(data) -> strategy``. None no uso normal.

    Returns
    -------
    pd.DataFrame
        Colunas: comm, slip, pf, sharpe, win_rate, num_trades, total_return_pct,
        mdd_total_pct, mdd_capital_at_risk_pct. Shape (len(comm)*len(slip), 9).

    Nota: comm → ``commission_pct`` ; slip → ``slippage_pct`` ; a comissão absoluta
    (``commission_per_trade``) é zerada para isolar os eixos percentuais.
    """
    comm_grid = list(DEFAULT_COMM_GRID if comm_grid is None else comm_grid)
    slip_grid = list(DEFAULT_SLIP_GRID if slip_grid is None else slip_grid)

    rows = []
    for comm in comm_grid:
        for slip in slip_grid:
            m = _run_single_backtest(
                strategy_config, data, comm, slip,
                initial_capital, risk_per_trade, strategy_factory,
            )
            rows.append({
                "comm": comm,
                "slip": slip,
                "pf": _num(m.get("profit_factor")),
                "sharpe": _num(m.get("sharpe_ratio")),
                "win_rate": _num(m.get("win_rate")),
                "num_trades": int(m.get("trade_count", 0) or 0),
                "total_return_pct": _num(m.get("return_pct")) * 100.0,
                "mdd_total_pct": _num(m.get("max_drawdown_total_equity_pct")),
                "mdd_capital_at_risk_pct": _num(m.get("max_drawdown_capital_at_risk_pct")),
            })

    return pd.DataFrame(rows, columns=_SWEEP_COLUMNS)


_METRIC_KEY = {
    "profit_factor": "profit_factor",
    "pf": "profit_factor",
    "sharpe": "sharpe_ratio",
    "sharpe_ratio": "sharpe_ratio",
}


def find_breakeven_slippage(
    strategy_config: dict,
    data: pd.DataFrame,
    commission: float = 0.001,
    slip_search_range: tuple = (0.0001, 0.01),
    metric: str = "profit_factor",
    target_value: float = 1.0,
    tolerance: float = 0.01,
    initial_capital: float = 100_000,
    risk_per_trade: float = 0.01,
    strategy_factory=None,
    max_iter: int = 40,
) -> dict:
    """Busca binária pelo slippage onde ``metric`` atinge ``target_value``.

    Pressupõe ``metric`` monotonicamente **decrescente** em slippage (slippage é
    adverso). Comissão fixada em ``commission``.

    Returns
    -------
    dict
        breakeven_slippage : float
            Slippage do cruzamento. ``NaN`` se a métrica já está abaixo do target
            no slippage mínimo (sem edge nem com custo mínimo). Igual a ``hi`` (com
            ``converged=False``) se a métrica sobrevive a toda a faixa (breakeven > hi).
        metric_at_breakeven : float
        num_iterations : int
        converged : bool
    """
    metric_key = _METRIC_KEY.get(metric, metric)
    lo, hi = slip_search_range

    def f(slip: float) -> float:
        m = _run_single_backtest(
            strategy_config, data, commission, slip,
            initial_capital, risk_per_trade, strategy_factory,
        )
        return _num(m.get(metric_key))

    f_lo = f(lo)
    iters = 1
    # Sem edge nem com custo mínimo → NaN.
    if not (f_lo > target_value):
        return {"breakeven_slippage": float("nan"), "metric_at_breakeven": f_lo,
                "num_iterations": iters, "converged": False}

    f_hi = f(hi)
    iters += 1
    # Sobrevive a toda a faixa → breakeven além de hi (reporta hi como cota inferior).
    if f_hi > target_value:
        return {"breakeven_slippage": float(hi), "metric_at_breakeven": f_hi,
                "num_iterations": iters, "converged": False}

    # Cruzamento garantido em (lo, hi): f_lo > target >= f_hi.
    mid = (lo + hi) / 2.0
    f_mid = f_lo
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        iters += 1
        if abs(f_mid - target_value) < tolerance or (hi - lo) < 1e-6:
            return {"breakeven_slippage": float(mid), "metric_at_breakeven": f_mid,
                    "num_iterations": iters, "converged": True}
        if f_mid > target_value:
            lo = mid          # ainda acima do target → precisa de mais slippage
        else:
            hi = mid
    return {"breakeven_slippage": float(mid), "metric_at_breakeven": f_mid,
            "num_iterations": iters, "converged": False}


# ──────────────────────────────────────────────────────────────────────────────
# E3 — Visualizações (matplotlib Agg). Importadas tarde p/ não exigir display.
# ──────────────────────────────────────────────────────────────────────────────

def _pivot(df: pd.DataFrame, value: str) -> tuple:
    """Pivota o sweep em matriz (linhas=slip asc, colunas=comm asc)."""
    comms = sorted(df["comm"].unique())
    slips = sorted(df["slip"].unique())
    mat = np.full((len(slips), len(comms)), np.nan)
    for _, r in df.iterrows():
        i = slips.index(r["slip"])
        j = comms.index(r["comm"])
        mat[i, j] = r[value]
    return mat, comms, slips


def plot_pf_heatmap(df: pd.DataFrame, out_path: str, title: str = "") -> str:
    """Heatmap de Profit Factor (X=comissão, Y=slippage), cmap RdYlGn."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mat, comms, slips = _pivot(df, "pf")
    plot_mat = np.where(np.isfinite(mat), mat, np.nan)
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(plot_mat, cmap="RdYlGn", origin="lower", aspect="auto",
                   vmin=0.0, vmax=2.0)
    ax.set_xticks(range(len(comms)))
    ax.set_xticklabels([f"{c*100:.2f}%" for c in comms])
    ax.set_yticks(range(len(slips)))
    ax.set_yticklabels([f"{s*100:.2f}%" for s in slips])
    ax.set_xlabel("Comissão"); ax.set_ylabel("Slippage")
    ax.set_title(title or "Profit Factor — sensibilidade a custos")
    for i in range(len(slips)):
        for j in range(len(comms)):
            v = mat[i, j]
            txt = "inf" if np.isinf(v) else ("—" if np.isnan(v) else f"{v:.2f}")
            ax.text(j, i, txt, ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="Profit Factor")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_sharpe_heatmap(df: pd.DataFrame, out_path: str, title: str = "") -> str:
    """Heatmap de Sharpe, escala de cor fixa [-2, 3] (comparabilidade)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mat, comms, slips = _pivot(df, "sharpe")
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(mat, cmap="RdYlGn", origin="lower", aspect="auto", vmin=-2.0, vmax=3.0)
    ax.set_xticks(range(len(comms)))
    ax.set_xticklabels([f"{c*100:.2f}%" for c in comms])
    ax.set_yticks(range(len(slips)))
    ax.set_yticklabels([f"{s*100:.2f}%" for s in slips])
    ax.set_xlabel("Comissão"); ax.set_ylabel("Slippage")
    ax.set_title(title or "Sharpe — sensibilidade a custos")
    for i in range(len(slips)):
        for j in range(len(comms)):
            v = mat[i, j]
            txt = "—" if np.isnan(v) else f"{v:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="Sharpe")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_degradation_curve(
    df: pd.DataFrame, out_path: str, comm_fixed: float | None = None,
    breakeven_slip: float | None = None, title: str = "",
) -> str:
    """Curva de degradação: slippage no X; PF/Sharpe/WinRate no Y.

    Fixa a comissão em ``comm_fixed`` (default: menor comissão da grade). Marca a
    linha horizontal de breakeven (y=1.0 para PF) e a vertical no breakeven slip.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if comm_fixed is None:
        comm_fixed = sorted(df["comm"].unique())[0]
    sub = df[np.isclose(df["comm"], comm_fixed)].sort_values("slip")

    fig, ax = plt.subplots(figsize=(9, 6))
    pf_plot = sub["pf"].replace([np.inf, -np.inf], np.nan)
    ax.plot(sub["slip"] * 100, pf_plot, "o-", label="Profit Factor", color="#2196F3")
    ax.plot(sub["slip"] * 100, sub["sharpe"], "s--", label="Sharpe", color="#FF9800")
    ax.plot(sub["slip"] * 100, sub["win_rate"], "^:", label="Win Rate", color="#4CAF50")
    ax.axhline(1.0, color="red", linestyle="-", alpha=0.6, label="breakeven (y=1.0)")
    if breakeven_slip is not None and np.isfinite(breakeven_slip):
        ax.axvline(breakeven_slip * 100, color="purple", linestyle="--", alpha=0.7,
                   label=f"breakeven slip = {breakeven_slip*100:.3f}%")
    ax.set_xlabel("Slippage (%)"); ax.set_ylabel("Métrica")
    ax.set_title(title or f"Degradação por slippage (comissão fixa {comm_fixed*100:.2f}%)")
    ax.legend(); ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# CLI (E5) — implementada no Checkpoint 3.
if __name__ == "__main__":   # pragma: no cover
    print("CLI de execução (E5) será implementada no Checkpoint 3 do Sprint 19.")
