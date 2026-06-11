# scripts/compare_walkforward_methods.py — Sprint 21 (E5 + E6)
"""Compara o walk-forward HONESTO (re-otimização por fold) com o ANTIGO/FIXO (params
selecionados UMA vez no histórico inteiro, depois aplicados fixos nas mesmas janelas OOS),
no MESMO dataset/param_space/folds. A diferença de OOS Sharpe é a estimativa do data
dredging na seleção de hiperparâmetros.

E5 (CP3): ^BVSP. E6 (CP4): ^BVSP, ^GSPC, VALE3.SA — anchored, n_folds dinâmico (cobre o
histórico até ~2026), 50 trials. O fixo é reconstruído reusando ``walk_forward_with_reopt``
(caso degenerado: param_space de 1 combo = os params globais).

Achado factual (CP1): nenhum walk-forward legado serve de referência — re-otimizam por fold
com grid minúsculo, non-anchored, sem embargo, em datas/dados distintos.

Natureza: camada de execução real (rede). Toda em ``# pragma: no cover`` — validada pelas
corridas reais. Disciplina S18: aborta o ticker se a fonte for sintética (registra, não fabrica).
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from walkforward_honest import (
    DEFAULT_PARAM_SPACE,
    EMBARGO_BARS,
    IS_WINDOW_BARS,
    OOS_WINDOW_BARS,
    compute_degradation,
    optimize_window,
    sprint13_base_params,
    walk_forward_with_reopt,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(_REPO_ROOT, "findings", "sprint_21_data")

TICKERS = [("^BVSP", "bvsp"), ("^GSPC", "gspc"), ("VALE3.SA", "vale3")]
HISTORY_START = "2010-01-01"        # ~15 anos
N_TRIALS = 50                        # E6 (CP4): 50 trials (CP3/E5 do ^BVSP usou 100)


def _max_folds(n_bars: int) -> int:   # pragma: no cover
    """Maior n_folds anchored que cabe em ``n_bars`` (cobre o histórico até o fim)."""
    return max(1, (n_bars - IS_WINDOW_BARS - EMBARGO_BARS - OOS_WINDOW_BARS) // OOS_WINDOW_BARS + 1)


def _deg_str(is_m: float, oos_m: float) -> str:   # pragma: no cover
    """String de degradação honesta — trata IS<=0 (não há performance a degradar)."""
    d = compute_degradation(is_m, oos_m)
    if d["interpretation"] == "is_nao_positivo":
        return "n/a (IS<=0)"
    return f"{d['relative_degradation_pct']:+.1f}% ({d['interpretation']})"


def _plot_is_oos(result, out_path: str, title: str) -> str:   # pragma: no cover
    """Gráfico IS vs OOS Sharpe por fold (PNG gitignored)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    folds = result.folds
    x = [f.fold_id for f in folds]
    is_s = [f.is_metrics.get("sharpe_ratio", float("nan")) for f in folds]
    oos_s = [f.oos_metrics.get("sharpe_ratio", float("nan")) for f in folds]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(x, is_s, "o-", label="IS Sharpe (re-otimizado)", color="#2196F3")
    ax.plot(x, oos_s, "s--", label="OOS Sharpe (honesto)", color="#F44336")
    ax.axhline(0.0, color="gray", lw=1, alpha=0.7)
    ax.set_xlabel("Fold")
    ax.set_ylabel("Sharpe")
    ax.set_title(title)
    ax.set_xticks(x)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def _compare_one(   # pragma: no cover — execução real (rede)
    ticker: str, slug: str, n_trials: int, output_dir: str,
    history_start: str, history_end: str,
) -> dict | None:
    """Roda honesto + fixo para UM ticker. Returns dict-resumo (None se fonte sintética)."""
    import json

    from scripts.fetch_real_data import download

    df, source = download(ticker, history_start, history_end, interval="1d")
    if source == "synthetic":
        print(f"  [ABORT-TICKER] {ticker}: fonte SINTÉTICA — pulado (disciplina S18).")
        return None

    base = sprint13_base_params()
    n_folds = _max_folds(len(df))
    print(f"\n[{ticker}] {len(df)} barras | n_folds={n_folds} (anchored) | {n_trials} trials")

    def _wf_or_unmeasurable(label: str, **kwargs):
        """walk_forward_with_reopt tolerando o caso 'todos os folds pulados' (VALE3-fixo):
        método inavaliável no ticker é RESULTADO (sem trades para medir), não crash."""
        try:
            return walk_forward_with_reopt(**kwargs)
        except ValueError as exc:
            if "todos os" in str(exc):
                print(f"  [{label}] INAVALIÁVEL — {exc}")
                return None
            raise

    print("  honesto (re-otim por fold)…")
    honest = _wf_or_unmeasurable(
        "honesto", data=df, param_space=DEFAULT_PARAM_SPACE, ticker=ticker,
        n_folds=n_folds, optimizer="optuna", n_trials_optuna=n_trials,
        metric_to_optimize="sharpe_dsr", base_params=base, verbose=True,
        skip_invalid_folds=True)
    if honest is not None and honest.skipped_folds:
        print(f"  [skip] {len(honest.skipped_folds)} fold(s) sem combo válido "
              f"(IS sem trades): {honest.skipped_folds}")

    print("  fixo: otimiza 1x no histórico inteiro…")
    best_global, _, _ = optimize_window(
        df, DEFAULT_PARAM_SPACE, ticker=ticker, base_params=base,
        optimizer="optuna", n_trials_optuna=n_trials, metric_to_optimize="sharpe_dsr")
    fixed_space = {k: [best_global[k]] for k in DEFAULT_PARAM_SPACE}
    fixed = _wf_or_unmeasurable(
        "fixo", data=df, param_space=fixed_space, ticker=ticker, n_folds=n_folds,
        optimizer="grid", metric_to_optimize="sharpe_dsr", base_params=base,
        verbose=False, skip_invalid_folds=True)
    if fixed is not None and fixed.skipped_folds:
        print(f"  [skip-fixo] {len(fixed.skipped_folds)} fold(s) sem trades com o combo "
              f"global: {fixed.skipped_folds}")

    if honest is None and fixed is None:
        print(f"  [{ticker}] NENHUM método avaliável — registrado como não-amostra.")

    ref = honest or fixed
    cover_start = str(ref.folds[0].is_start.date()) if ref else ""
    cover_end = str(ref.folds[-1].oos_end.date()) if ref else ""

    # E6: JSON completo + PNG IS-vs-OOS por ticker (None = método inavaliável; registro honesto).
    with open(os.path.join(output_dir, f"compare_{slug}.json"), "w", encoding="utf-8") as fh:
        json.dump({"ticker": ticker, "history_start": history_start, "history_end": history_end,
                   "n_bars": len(df), "n_folds": n_folds, "n_trials": n_trials,
                   "cover_start": cover_start, "cover_end": cover_end,
                   "best_global": best_global,
                   "honest": honest.to_dict() if honest else None,
                   "fixed": fixed.to_dict() if fixed else None}, fh, indent=2,
                  ensure_ascii=False)
    if honest is not None:
        _plot_is_oos(honest, os.path.join(output_dir, f"walkforward_{slug}.png"),
                     f"{ticker} — Walk-forward honesto: IS vs OOS Sharpe por fold "
                     f"({n_folds} folds, {cover_start}->{cover_end})")

    return {"ticker": ticker, "slug": slug, "n_bars": len(df), "n_folds": n_folds,
            "cover_start": cover_start, "cover_end": cover_end,
            "best_global": best_global, "honest": honest, "fixed": fixed}


def _rows_for(res: dict, n_trials: int) -> list[dict]:   # pragma: no cover
    """Duas linhas (fixo, honesto) para o CSV consolidado. Método inavaliável → NaNs +
    n_folds_valid=0 (registro explícito, não omissão)."""
    nan = float("nan")
    out = []
    for method, r in (("antigo_fixo", res["fixed"]), ("honesto_reotim", res["honest"])):
        base_row = {
            "ticker": res["ticker"], "method": method, "n_folds": res["n_folds"],
            "n_trials": n_trials, "cover_start": res["cover_start"], "cover_end": res["cover_end"],
        }
        if r is None:
            base_row.update({
                "is_sharpe_mean": nan, "oos_sharpe_mean": nan, "is_pf_mean": nan,
                "oos_pf_mean": nan, "degradation_pct": nan, "param_stability": nan,
                "n_folds_valid": 0, "skipped_folds": res["n_folds"],
            })
        else:
            base_row.update({
                "is_sharpe_mean": r.is_sharpe_mean, "oos_sharpe_mean": r.oos_sharpe_mean,
                "is_pf_mean": r.is_pf_mean, "oos_pf_mean": r.oos_pf_mean,
                "degradation_pct": r.degradation_pct, "param_stability": r.param_stability_score,
                "n_folds_valid": len(r.folds), "skipped_folds": len(r.skipped_folds),
            })
        out.append(base_row)
    return out


def run_comparison(   # pragma: no cover — execução real (rede); validada nas corridas CP3/CP4
    tickers: list[tuple[str, str]] | None = None,
    history_start: str = HISTORY_START,
    history_end: str | None = None,
    n_trials: int = N_TRIALS,
    output_dir: str = OUTPUT_DIR,
) -> dict:
    """Roda a comparação honesto vs fixo para a lista de tickers; consolida o CSV.

    Gate S18: aborta o ticker (não o run) se a fonte for sintética; registra em ``aborted``.
    """
    tickers = tickers or TICKERS
    if history_end is None:
        history_end = pd.Timestamp.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)

    results, rows, aborted = [], [], []
    for ticker, slug in tickers:
        res = _compare_one(ticker, slug, n_trials, output_dir, history_start, history_end)
        if res is None:
            aborted.append(ticker)
            continue
        results.append(res)
        rows.extend(_rows_for(res, n_trials))

    csv_path = os.path.join(output_dir, "walkforward_comparison.csv")
    if rows:
        cols = ["ticker", "method", "n_folds", "n_trials", "cover_start", "cover_end",
                "is_sharpe_mean", "oos_sharpe_mean", "is_pf_mean", "oos_pf_mean",
                "degradation_pct", "param_stability", "n_folds_valid", "skipped_folds"]
        pd.DataFrame(rows, columns=cols).to_csv(csv_path, index=False)

    return {"results": results, "aborted": aborted, "csv_path": csv_path, "n_trials": n_trials}


def main(argv: list[str] | None = None) -> int:   # pragma: no cover — CLI/rede
    import argparse
    import contextlib

    with contextlib.suppress(Exception):   # console Windows cp1252; UTF-8 evita UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Sprint 21 E5/E6 — walk-forward honesto vs antigo/fixo (data dredging).")
    parser.add_argument("--ticker", help="ticker único (ex.: ^BVSP). Sem isto, roda os 3 oficiais.")
    parser.add_argument("--history-start", default=HISTORY_START)
    parser.add_argument("--n-trials", type=int, default=N_TRIALS)
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    if args.ticker:
        slug_map = dict(TICKERS)
        slug = slug_map.get(args.ticker,
                            args.ticker.replace("^", "").replace(".SA", "").lower())
        tickers = [(args.ticker, slug)]
    else:
        tickers = TICKERS

    print("=" * 100)
    print(" Sprint 21 E5/E6 — Walk-forward HONESTO vs ANTIGO/FIXO (estimativa de data dredging)")
    print("=" * 100)
    out = run_comparison(tickers, history_start=args.history_start,
                         n_trials=args.n_trials, output_dir=args.output_dir)

    if not out["results"]:
        print("\n  [ABORT] nenhum ticker com dados reais — nada gerado.")
        return 1

    print("\n" + "=" * 100)
    print(f"  TABELA COMPARATIVA — {args.n_trials} trials | anchored | n_folds dinâmico")
    print("=" * 100)
    print(f"  {'Ticker':<10} {'Método':<16} {'folds':>5} {'IS Sharpe':>10} {'OOS Sharpe':>11} "
          f"{'IS PF':>7} {'OOS PF':>7} {'stab':>6}  Degradação")
    print("  " + "-" * 96)
    for res in out["results"]:
        for label, r in (("antigo (fixo)", res["fixed"]), ("honesto", res["honest"])):
            if r is None:
                print(f"  {res['ticker']:<10} {label:<16} {res['n_folds']:>5} "
                      f"{'INAVALIÁVEL (0 folds com trades)':>52}")
                continue
            nv = len(r.folds)
            print(f"  {res['ticker']:<10} {label:<16} {nv:>2}/{res['n_folds']:<2} "
                  f"{r.is_sharpe_mean:>+10.3f} {r.oos_sharpe_mean:>+11.3f} "
                  f"{r.is_pf_mean:>7.3f} {r.oos_pf_mean:>7.3f} "
                  f"{r.param_stability_score:>6.2f}  {_deg_str(r.is_sharpe_mean, r.oos_sharpe_mean)}")
        if res["honest"] is not None and res["fixed"] is not None:
            dredge = res["honest"].oos_sharpe_mean - res["fixed"].oos_sharpe_mean
            print(f"  {'':<10} {'-> Δ OOS (hon-fix)':<16} {'':>5} {dredge:>+10.3f}  (data dredging)")
        print("  " + "-" * 96)
    if out["aborted"]:
        print(f"\n  [S18] tickers abortados (fonte sintética): {out['aborted']}")
    print(f"\n  CSV: {out['csv_path']}")
    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
