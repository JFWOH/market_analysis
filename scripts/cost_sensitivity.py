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


# ──────────────────────────────────────────────────────────────────────────────
# E5 — Execução real (CLI). Importa dependências de I/O tarde (rede/config) para
# manter o núcleo-biblioteca acima livre de side-effects nos testes.
# ──────────────────────────────────────────────────────────────────────────────

# Tickers oficiais do sprint (spec §3/E5) e seus slugs de arquivo.
TICKERS = [("^BVSP", "bvsp"), ("VALE3.SA", "vale3"), ("PETR4.SA", "petr4")]
HISTORY_START = "2000-01-01"        # histórico longo; a janela OOS é o último 30%
OOS_FRACTION = 0.30                 # decisão 3 do plano: últimos 30% por ticker
BASELINE_COMM = 0.001              # 0.1% — comissão fixa para baseline/breakeven
BASELINE_SLIP = 0.001              # 0.1% — slippage do baseline (spec/template)
STRESS_SLIP = 0.003                # 0.3% — pessimista realista (CLAUDE.md §6.6)
CONFIG_FILE_LABEL = "sprint_13"     # rótulo nos nomes de PNG (casa com o template)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(_REPO_ROOT, "findings", "sprint_19_data")


def _load_config(config_name: str) -> dict:
    """Carrega o dict de params da config (lazy import: DRY com bear_market_validation).

    Único registro existente é ``sprint_13_reference`` → ``SPRINT13_PARAMS`` (ver
    plano Q3). Formalizar um registry YAML fica para S21+.
    """
    try:
        from scripts.bear_market_validation import SPRINT13_PARAMS
    except ImportError:  # execução direta do script (sys.path já tem a raiz)
        from bear_market_validation import SPRINT13_PARAMS
    registry = {"sprint_13_reference": SPRINT13_PARAMS}
    if config_name not in registry:
        raise KeyError(
            f"config desconhecida: {config_name!r}. Disponíveis: {list(registry)}")
    return dict(registry[config_name])


def _slice_oos(df: pd.DataFrame, frac: float = OOS_FRACTION) -> pd.DataFrame:
    """Recorta os últimos ``frac`` (proporção de barras) do histórico.

    Os indicadores (ADX/Hurst/macro_window=60) se auto-aquecem nas ~90 primeiras
    barras do recorte — perda desprezível numa janela OOS de ~1900 barras. As datas
    de calendário do início da janela DIFEREM entre tickers (cada um tem seu próprio
    nº de barras); isso é documentado no finding (consequência do 30% proporcional).
    """
    n = len(df)
    start = int(n * (1.0 - frac))
    return df.iloc[start:].copy()


def _cell(df: pd.DataFrame, col: str, comm: float, slip: float) -> float:
    """Extrai o valor de ``col`` na célula (comm, slip) do sweep."""
    m = df[np.isclose(df["comm"], comm) & np.isclose(df["slip"], slip)]
    if m.empty:
        return float("nan")
    return float(m.iloc[0][col])


def run_ticker(   # pragma: no cover — camada de execução (rede); validada pela corrida real do CP3
    ticker: str,
    slug: str,
    config_name: str = "sprint_13_reference",
    output_dir: str = OUTPUT_DIR,
    history_start: str = HISTORY_START,
    history_end: str | None = None,
) -> dict:
    """Executa o sweep + breakeven + visualizações para UM ticker (dados reais).

    Disciplina do S18: ABORTA se a fonte for sintética — nunca fabricar números.

    Saídas: ``sweep_<slug>.csv``, ``heatmap_<config>_<slug>_pf.png``,
    ``heatmap_<config>_<slug>_sharpe.png``, ``degradation_<slug>.png``.

    Returns
    -------
    dict
        Linha de resumo: ticker, janela OOS, nº barras, PF baseline, PF @ slip 0.3%,
        breakeven slip, passa@0.3%, e diagnóstico de absorção de custos.
    """
    from scripts.fetch_real_data import download  # lazy: rede só no caminho de execução

    if history_end is None:
        history_end = pd.Timestamp.today().strftime("%Y-%m-%d")

    df, source = download(ticker, history_start, history_end, interval="1d")
    if source == "synthetic":
        raise RuntimeError(
            f"{ticker}: download retornou dados SINTÉTICOS (yfinance indisponível). "
            f"Abortado — disciplina do Sprint 18: não fabricar números.")

    oos = _slice_oos(df)
    oos_start = oos.index[0].date()
    oos_end = oos.index[-1].date()
    config = _load_config(config_name)

    os.makedirs(output_dir, exist_ok=True)

    # Sweep (4×5 = 20 células).
    sweep = cost_sensitivity_sweep(config, oos)
    sweep.to_csv(os.path.join(output_dir, f"sweep_{slug}.csv"), index=False)

    # Breakeven (comissão fixa 0.1%).
    be = find_breakeven_slippage(config, oos, commission=BASELINE_COMM)
    breakeven_slip = be["breakeven_slippage"]

    # Visualizações.
    plot_pf_heatmap(
        sweep, os.path.join(output_dir, f"heatmap_{CONFIG_FILE_LABEL}_{slug}_pf.png"),
        title=f"Profit Factor — {ticker} (OOS {oos_start}→{oos_end})")
    plot_sharpe_heatmap(
        sweep, os.path.join(output_dir, f"heatmap_{CONFIG_FILE_LABEL}_{slug}_sharpe.png"),
        title=f"Sharpe — {ticker} (OOS {oos_start}→{oos_end})")
    plot_degradation_curve(
        sweep, os.path.join(output_dir, f"degradation_{slug}.png"),
        comm_fixed=BASELINE_COMM, breakeven_slip=breakeven_slip,
        title=f"Degradação por slippage — {ticker} (comissão 0.10%)")

    # Métricas de resumo (baseline e estresse vêm direto do grid).
    pf_baseline = _cell(sweep, "pf", BASELINE_COMM, BASELINE_SLIP)
    pf_stress = _cell(sweep, "pf", BASELINE_COMM, STRESS_SLIP)
    sharpe_baseline = _cell(sweep, "sharpe", BASELINE_COMM, BASELINE_SLIP)
    ret_baseline = _cell(sweep, "total_return_pct", BASELINE_COMM, BASELINE_SLIP)
    trades_baseline = _cell(sweep, "num_trades", BASELINE_COMM, BASELINE_SLIP)

    # Diagnóstico de absorção de custos: retorno bruto (custo ~0) vs líquido (baseline).
    gross = _run_single_backtest(config, oos, 0.0, 0.0, 100_000, 0.01)
    ret_gross_pct = _num(gross.get("return_pct")) * 100.0
    absorbed_pp = ret_gross_pct - ret_baseline  # pontos percentuais comidos pelos custos

    passes_03 = bool(np.isfinite(pf_stress) and pf_stress > 1.0)

    return {
        "ticker": ticker,
        "oos_start": str(oos_start),
        "oos_end": str(oos_end),
        "oos_bars": int(len(oos)),
        "pf_baseline": round(pf_baseline, 4),
        "sharpe_baseline": round(sharpe_baseline, 4),
        "ret_baseline_pct": round(ret_baseline, 2),
        "trades_baseline": int(trades_baseline),
        "pf_slip_03": round(pf_stress, 4),
        "breakeven_slip": (round(breakeven_slip, 6)
                           if np.isfinite(breakeven_slip) else float("nan")),
        "breakeven_converged": bool(be["converged"]),
        "ret_gross_pct": round(ret_gross_pct, 2),
        "cost_absorbed_pp": round(absorbed_pp, 2),
        "passes_slip_03": passes_03,
    }


def main(argv: list[str] | None = None) -> int:   # pragma: no cover — CLI/rede; validada pela corrida real do CP3
    import argparse

    parser = argparse.ArgumentParser(
        description="Sprint 19 — sensibilidade a custos (sweep comm×slip + breakeven).")
    parser.add_argument("--ticker", help="ticker único (ex.: ^BVSP)")
    parser.add_argument("--config", default="sprint_13_reference",
                        help="config de params (default: sprint_13_reference)")
    parser.add_argument("--all-tickers", action="store_true",
                        help="roda os 3 tickers oficiais (^BVSP, VALE3.SA, PETR4.SA)")
    parser.add_argument("--n-jobs", type=int, default=1,
                        help="reservado p/ paralelização (CLAUDE.md §6.3: spawn no "
                             "Windows é arriscado; execução é sequencial por ora)")
    args = parser.parse_args(argv)

    if args.n_jobs != 1:
        print("  [nota] --n-jobs ignorado: execução sequencial (paralelização adiada, "
              "CLAUDE.md §6.3). Sweep sequencial roda em poucos minutos.")

    # Resolve a lista de (ticker, slug).
    if args.all_tickers:
        targets = list(TICKERS)
    elif args.ticker:
        slug_map = dict(TICKERS)
        slug = slug_map.get(args.ticker,
                            args.ticker.replace("^", "").replace(".SA", "").lower())
        targets = [(args.ticker, slug)]
    else:
        parser.error("informe --ticker <TICKER> ou --all-tickers")
        return 2

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 96)
    print(" Sprint 19 — Sensibilidade a custos (sweep comm×slip, OOS = últimos 30%)")
    print("=" * 96)

    rows = []
    for ticker, slug in targets:
        print(f"\n[{ticker}] baixando histórico e rodando sweep…")
        try:
            r = run_ticker(ticker, slug, config_name=args.config)
        except RuntimeError as e:
            print(f"  [ABORT] {e}")
            return 1
        rows.append(r)
        verdict = "PASSA" if r["passes_slip_03"] else "NÃO PASSA"
        be_s = (f"{r['breakeven_slip']*100:.3f}%"
                if np.isfinite(r["breakeven_slip"]) else "NaN (sem edge)")
        print(f"  [OK] OOS {r['oos_start']}->{r['oos_end']} ({r['oos_bars']} barras) | "
              f"PF base={r['pf_baseline']:.3f} | PF@slip0.3%={r['pf_slip_03']:.3f} "
              f"[{verdict}] | breakeven={be_s}")

    # breakeven_summary.csv — 1 linha por ticker.
    summary_cols = [
        "ticker", "oos_start", "oos_end", "oos_bars", "pf_baseline",
        "sharpe_baseline", "ret_baseline_pct", "trades_baseline", "pf_slip_03",
        "breakeven_slip", "breakeven_converged", "ret_gross_pct",
        "cost_absorbed_pp", "passes_slip_03",
    ]
    summary_path = os.path.join(OUTPUT_DIR, "breakeven_summary.csv")
    pd.DataFrame(rows, columns=summary_cols).to_csv(summary_path, index=False)

    n_pass = sum(1 for r in rows if r["passes_slip_03"])
    print("\n" + "=" * 96)
    print(f"  Veredito: {n_pass}/{len(rows)} tickers passam no teste de slippage 0.3% "
          f"(PF > 1.0).")
    print(f"  Resumo: {summary_path}")
    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
