# scripts/compare_walkforward_methods.py — Sprint 21 (E5)
"""Compara o walk-forward HONESTO (re-otimização por fold) com o ANTIGO/FIXO (params
selecionados UMA vez no histórico inteiro, depois aplicados fixos nas mesmas janelas OOS).

A diferença entre as duas linhas é a estimativa do **data dredging** na seleção de
hiperparâmetros: o método fixo "viu" todo o histórico (inclusive os OOS) ao escolher os
params; o honesto só viu o IS de cada fold.

Achado factual (CP1): nenhum walk-forward legado (`walk_forward_real.py` etc.) serve como
referência — eles re-otimizam por fold com grid minúsculo, non-anchored, sem embargo, em
datas/dados distintos. Por isso o "antigo/fixo" é **reconstruído aqui** sobre o MESMO
dataset/param_space/folds do honesto, reusando ``walk_forward_with_reopt`` (o fixo é o
caso degenerado: param_space de 1 combo = os params globais).

Natureza: camada de execução real (rede). Toda em ``# pragma: no cover`` — validada pela
corrida real do CP3 (^BVSP). Disciplina S18: aborta se a fonte for sintética.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from walkforward_honest import (
    DEFAULT_PARAM_SPACE,
    N_TRIALS_OPTUNA,
    compute_degradation,
    optimize_window,
    sprint13_base_params,
    walk_forward_with_reopt,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(_REPO_ROOT, "findings", "sprint_21_data")

TICKER = "^BVSP"
TICKER_SLUG = "bvsp"
HISTORY_START = "2010-01-01"        # ~15 anos (spec E6)
N_FOLDS = 5


def _deg_str(is_m: float, oos_m: float) -> str:   # pragma: no cover
    """String de degradação honesta — trata IS≤0 (não há performance a degradar)."""
    d = compute_degradation(is_m, oos_m)
    if d["interpretation"] == "is_nao_positivo":
        return f"n/a (IS<=0: {d['interpretation']})"
    rel = d["relative_degradation_pct"]
    return f"{rel:+.1f}% ({d['interpretation']})"


def run_comparison(   # pragma: no cover — execução real (rede); validada no CP3
    ticker: str = TICKER,
    history_start: str = HISTORY_START,
    history_end: str | None = None,
    n_folds: int = N_FOLDS,
    n_trials: int = N_TRIALS_OPTUNA,
    output_dir: str = OUTPUT_DIR,
) -> dict:
    """Roda honesto vs antigo/fixo no MESMO dataset/param_space/folds. Returns dict-resumo.

    Gate S18: aborta se ``download`` devolver dados sintéticos.
    """
    import json

    from scripts.fetch_real_data import download

    if history_end is None:
        history_end = pd.Timestamp.today().strftime("%Y-%m-%d")

    df, source = download(ticker, history_start, history_end, interval="1d")
    if source == "synthetic":
        raise RuntimeError(
            f"{ticker}: download retornou dados SINTÉTICOS — abortado (disciplina S18).")

    base = sprint13_base_params()
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n[1/3] Honesto (re-otim por fold) — Optuna {n_trials} trials x {n_folds} folds…")
    honest = walk_forward_with_reopt(
        df, DEFAULT_PARAM_SPACE, ticker=ticker, n_folds=n_folds,
        optimizer="optuna", n_trials_optuna=n_trials, metric_to_optimize="sharpe_dsr",
        base_params=base, verbose=True)

    print(f"\n[2/3] Antigo/fixo — otimiza 1x no histórico inteiro ({len(df)} barras)…")
    best_global, _, _ = optimize_window(
        df, DEFAULT_PARAM_SPACE, ticker=ticker, base_params=base,
        optimizer="optuna", n_trials_optuna=n_trials, metric_to_optimize="sharpe_dsr")
    print(f"      best_global = {best_global}")

    print(f"\n[3/3] Aplica best_global FIXO nas mesmas {n_folds} janelas…")
    fixed_space = {k: [best_global[k]] for k in DEFAULT_PARAM_SPACE}  # 1 combo/fold
    fixed = walk_forward_with_reopt(
        df, fixed_space, ticker=ticker, n_folds=n_folds,
        optimizer="grid", metric_to_optimize="sharpe_dsr",
        base_params=base, verbose=True)

    rows = [
        {"method": "antigo_fixo", "is_sharpe_mean": fixed.is_sharpe_mean,
         "oos_sharpe_mean": fixed.oos_sharpe_mean, "is_pf_mean": fixed.is_pf_mean,
         "oos_pf_mean": fixed.oos_pf_mean, "degradation_pct": fixed.degradation_pct,
         "param_stability": fixed.param_stability_score},
        {"method": "honesto_reotim", "is_sharpe_mean": honest.is_sharpe_mean,
         "oos_sharpe_mean": honest.oos_sharpe_mean, "is_pf_mean": honest.is_pf_mean,
         "oos_pf_mean": honest.oos_pf_mean, "degradation_pct": honest.degradation_pct,
         "param_stability": honest.param_stability_score},
    ]
    csv_path = os.path.join(output_dir, "walkforward_comparison.csv")
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    # JSON detalhado (registro completo dos folds de ambos os métodos).
    with open(os.path.join(output_dir, f"compare_{TICKER_SLUG}.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"ticker": ticker, "history_start": history_start,
                   "history_end": history_end, "n_bars": len(df),
                   "n_folds": n_folds, "best_global": best_global,
                   "honest": honest.to_dict(), "fixed": fixed.to_dict()},
                  fh, indent=2, ensure_ascii=False)

    return {"honest": honest, "fixed": fixed, "best_global": best_global,
            "n_bars": len(df), "csv_path": csv_path,
            "cover_start": str(honest.folds[0].is_start.date()),
            "cover_end": str(honest.folds[-1].oos_end.date())}


def main(argv: list[str] | None = None) -> int:   # pragma: no cover — CLI/rede
    import argparse
    import contextlib

    with contextlib.suppress(Exception):   # console Windows cp1252; UTF-8 evita UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Sprint 21 E5 — comparação walk-forward honesto vs antigo/fixo (^BVSP).")
    parser.add_argument("--ticker", default=TICKER)
    parser.add_argument("--history-start", default=HISTORY_START)
    parser.add_argument("--n-folds", type=int, default=N_FOLDS)
    parser.add_argument("--n-trials", type=int, default=N_TRIALS_OPTUNA)
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    print("=" * 92)
    print(" Sprint 21 E5 — Walk-forward HONESTO vs ANTIGO/FIXO (estimativa de data dredging)")
    print("=" * 92)
    try:
        out = run_comparison(args.ticker, history_start=args.history_start,
                             n_folds=args.n_folds, n_trials=args.n_trials,
                             output_dir=args.output_dir)
    except RuntimeError as e:
        print(f"  [ABORT] {e}")
        return 1

    h, f = out["honest"], out["fixed"]
    print("\n" + "=" * 92)
    print(f"  TABELA COMPARATIVA - {args.ticker} | {out['n_bars']} barras | "
          f"folds cobrem {out['cover_start']} -> {out['cover_end']}")
    print("=" * 92)
    print(f"  {'Método':<22} {'IS Sharpe':>11} {'OOS Sharpe':>11} {'IS PF':>8} "
          f"{'OOS PF':>8} {'Degradação':>14} {'stability':>10}")
    print("  " + "-" * 88)
    for label, r in (("Antigo (params fixos)", f), ("Honesto (re-otim)", h)):
        print(f"  {label:<22} {r.is_sharpe_mean:>+11.3f} {r.oos_sharpe_mean:>+11.3f} "
              f"{r.is_pf_mean:>8.3f} {r.oos_pf_mean:>8.3f} "
              f"{_deg_str(r.is_sharpe_mean, r.oos_sharpe_mean):>14} "
              f"{r.param_stability_score:>10.3f}")
    print("  " + "-" * 88)
    dredge = h.oos_sharpe_mean - f.oos_sharpe_mean
    print(f"\n  Delta OOS Sharpe (honesto - fixo) = {dredge:+.3f}  "
          f"(estimativa do data dredging)")
    print(f"  best_global (fixo): {out['best_global']}")
    print(f"\n  CSV: {out['csv_path']}")
    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
