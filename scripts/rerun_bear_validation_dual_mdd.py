# scripts/rerun_bear_validation_dual_mdd.py — Sprint-18 (E4)
"""Re-emite os 7 cenários de bear histórico com MDD em DUAS bases.

Reaproveita os cenários, parâmetros (config Sprint-13) e janela de avaliação de
``scripts/bear_market_validation.py``, mas reporta o drawdown em duas bases:

  • total_mdd_pct          — MDD sobre o equity total (caixa ocioso + posições).
  • capital_at_risk_mdd_pct — MDD sobre o capital efetivamente exposto (CAR).

A tese da auditoria (Bloco I): como o sistema fica FORA do mercado a maior parte
do tempo nos crashes, o MDD-equity é diluído pelo caixa ocioso. O MDD-CAR mede o
risco real do capital empregado e pode ser uma ordem de magnitude maior.

Convenção do CAR (ver metrics.compute_drawdown_dual): a curva sintética de capital
empregado só avança com posição aberta em DUAS barras consecutivas; o PnL da barra
de ABERTURA de cada trade não entra na CAR.

Saídas (em findings/sprint_18_data/):
  • bears_dual_mdd.csv   — tabela de evidência (versionada).
  • dual_mdd_chart.png   — gráfico de barras (regenerável; NÃO versionado).

Uso:
    python scripts/rerun_bear_validation_dual_mdd.py
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib

matplotlib.use("Agg")  # backend não-interativo
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtester import Backtester
from metrics import compute_drawdown_dual
from scripts.bear_market_validation import CAPITAL, SCENARIOS, SPRINT13_PARAMS
from scripts.fetch_real_data import download
from strategy import CombinedStrategy

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "findings", "sprint_18_data",
)

WARMUP_BARS = 90  # barras de pré-aquecimento p/ indicadores (ADX/Hurst/Fib)


def _run_scenario(label, ticker, prewarm, eval_start, eval_end) -> dict | None:
    """Roda a estratégia Sprint-13 e calcula o MDD dual no período de eval.

    O backtester roda sobre [warmup .. eval_end]; o MDD dual é calculado APENAS
    sobre a janela de avaliação (sem o pré-aquecimento), recortando as curvas de
    equity/position_value rastreadas pelo motor. num_trades e sharpe vêm da
    rodada completa (mesma convenção do bear_market_validation.py legado).
    """
    df, source = download(ticker, prewarm, eval_end, interval="1d")
    if source == "synthetic":
        print(f"  [AVISO] {label}: dados SINTÉTICOS (yfinance falhou) — número não é real")

    eval_start_ts = pd.Timestamp(eval_start)
    eval_end_ts = pd.Timestamp(eval_end)

    eval_mask = (df.index >= eval_start_ts) & (df.index <= eval_end_ts)
    if int(eval_mask.sum()) < 20:
        print(f"  [SKIP] {label}: poucas barras no eval ({int(eval_mask.sum())})")
        return None

    # Recorte com warmup antes do eval_start (para indicadores).
    warmup_idx = max(0, int(df.index.get_indexer([eval_start_ts])[0]) - WARMUP_BARS)
    df_run = df.iloc[warmup_idx:].copy()

    strat = CombinedStrategy(ticker)
    strat.set_data(df_run)
    strat.params.update(SPRINT13_PARAMS)
    bt = Backtester(strat, initial_capital=CAPITAL, cooldown_bars=2,
                    commission_per_trade=0.001, slippage_pct=0.001)
    m = bt.run()

    # Curvas rastreadas pelo motor (índice = barras processadas após prepare()).
    eq = pd.Series(bt.equity, index=bt.equity_dates)
    pv = pd.Series(bt.position_value, index=bt.equity_dates)
    win = (eq.index >= eval_start_ts) & (eq.index <= eval_end_ts)
    eq_eval, pv_eval = eq[win], pv[win]
    if len(eq_eval) < 2:
        print(f"  [SKIP] {label}: curva de eval curta demais ({len(eq_eval)})")
        return None

    dual = compute_drawdown_dual(eq_eval, pv_eval)

    total_mdd = float(dual["total_equity_mdd"])
    car_mdd = float(dual["capital_at_risk_mdd"])
    ratio = (car_mdd / total_mdd) if total_mdd > 0 else float("nan")

    return {
        "cenario": label,
        "periodo": f"{eval_start} a {eval_end}",
        "ticker": ticker,
        "total_mdd_pct": round(total_mdd, 2),
        "capital_at_risk_mdd_pct": (round(car_mdd, 2) if not np.isnan(car_mdd) else np.nan),
        "ratio_car_eq": (round(ratio, 2) if not np.isnan(ratio) else np.nan),
        "time_in_market_pct": round(float(dual["time_in_market_pct"]), 1),
        "num_trades": int(m.get("trade_count", 0) or 0),
        "sharpe": round(float(m.get("sharpe_ratio", 0) or 0), 2),
    }


def _write_csv(rows: list[dict]) -> str:
    path = os.path.join(OUTPUT_DIR, "bears_dual_mdd.csv")
    cols = ["cenario", "periodo", "ticker", "total_mdd_pct",
            "capital_at_risk_mdd_pct", "ratio_car_eq", "time_in_market_pct",
            "num_trades", "sharpe"]
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    return path


def _plot_dual_mdd(rows: list[dict]) -> str:
    path = os.path.join(OUTPUT_DIR, "dual_mdd_chart.png")
    labels = [r["cenario"] for r in rows]
    total = [r["total_mdd_pct"] for r in rows]
    car = [(r["capital_at_risk_mdd_pct"]
            if not (isinstance(r["capital_at_risk_mdd_pct"], float)
                    and np.isnan(r["capital_at_risk_mdd_pct"])) else 0.0)
           for r in rows]

    x = np.arange(len(labels))
    w = 0.38
    fig, ax = plt.subplots(figsize=(13, 7))
    b1 = ax.bar(x - w / 2, total, w, label="MDD equity total", color="#2196F3")
    b2 = ax.bar(x + w / 2, car, w, label="MDD capital-em-risco", color="#F44336")

    for r, xi, c in zip(rows, x, car):
        ratio = r["ratio_car_eq"]
        if isinstance(ratio, float) and not np.isnan(ratio):
            ax.text(xi + w / 2, c, f"{ratio:.1f}x", ha="center", va="bottom",
                    fontsize=9, fontweight="bold")

    ax.set_title("Sprint 18 — MDD em base dupla nos bears históricos "
                 "(config Sprint-13)", fontsize=13)
    ax.set_ylabel("Max Drawdown (%)", fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=9)
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


def _print_markdown(rows: list[dict]) -> None:
    """Imprime a tabela markdown pronta para colar no finding."""
    print("\n| Cenário | Período | total_mdd% | CAR_mdd% | CAR/eq | tempo_mkt% | trades | sharpe |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        car = r["capital_at_risk_mdd_pct"]
        ratio = r["ratio_car_eq"]
        car_s = "NaN" if (isinstance(car, float) and np.isnan(car)) else f"{car:.2f}"
        ratio_s = "NaN" if (isinstance(ratio, float) and np.isnan(ratio)) else f"{ratio:.2f}"
        print(f"| {r['cenario']} | {r['periodo']} | {r['total_mdd_pct']:.2f} | "
              f"{car_s} | {ratio_s} | {r['time_in_market_pct']:.1f} | "
              f"{r['num_trades']} | {r['sharpe']:.2f} |")


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 96)
    print(" Sprint-18: re-validação dos bears com MDD em base dupla (total + CAR)")
    print("=" * 96)

    rows = []
    for label, ticker, prewarm, eval_start, eval_end in SCENARIOS:
        try:
            r = _run_scenario(label, ticker, prewarm, eval_start, eval_end)
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {label}: {str(e)[:160]}")
            continue
        if r is not None:
            rows.append(r)
            print(f"  [OK] {label}: total={r['total_mdd_pct']}% "
                  f"CAR={r['capital_at_risk_mdd_pct']}% "
                  f"ratio={r['ratio_car_eq']} tempo_mkt={r['time_in_market_pct']}%")

    if not rows:
        print("\n  NENHUM cenário produziu resultado. Abortando sem escrever saídas.")
        sys.exit(1)

    csv_path = _write_csv(rows)
    png_path = _plot_dual_mdd(rows)
    _print_markdown(rows)

    # Resumo agregado para o finding.
    ratios = [r["ratio_car_eq"] for r in rows
              if not (isinstance(r["ratio_car_eq"], float) and np.isnan(r["ratio_car_eq"]))]
    tim = [r["time_in_market_pct"] for r in rows]
    print("\n" + "=" * 96)
    if ratios:
        print(f"  Mediana razão CAR/equity : {float(np.median(ratios)):.2f}x")
        print(f"  Razão CAR/equity máxima   : {float(np.max(ratios)):.2f}x")
    print(f"  Mediana tempo em mercado  : {float(np.median(tim)):.1f}%")
    print(f"\n  CSV : {csv_path}")
    print(f"  PNG : {png_path}")


if __name__ == "__main__":
    main()
