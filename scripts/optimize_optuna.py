"""
scripts/optimize_optuna.py — Otimização de hiperparâmetros via Optuna.

Sprint-4 passo 3: busca bayesiana (TPE) sobre o espaço de parâmetros do
sistema completo Sprint-2+3, usando PurgedKFold para avaliação interna.

Objetivo: maximizar PF médio OOS num subset dos dados (in-sample).

Parâmetros otimizados:
  - adx_threshold        [15, 40]
  - hurst_threshold      [0.45, 0.65]
  - vol_target_annual    [0.10, 0.30]
  - ensemble_breakout_window [5, 40]
  - meta_min_prob        [0.40, 0.75]
  - atr_stop_multiplier  [1.0, 3.0]
  - atr_target_multiplier [1.5, 5.0]

Uso:
    python scripts/optimize_optuna.py [--ticker ^BVSP] [--trials 50]
"""
from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
import warnings

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import optuna
from optuna.samplers import TPESampler

from scripts.fetch_real_data import download
from strategy import CombinedStrategy
from backtester import Backtester
from labels import PurgedKFold

optuna.logging.set_verbosity(optuna.logging.WARNING)
logging.basicConfig(level=logging.WARNING)

CAPITAL    = 100_000.0
COMMISSION = 0.001
SLIPPAGE   = 0.001
COOLDOWN   = 2
N_FOLDS    = 4       # folds para PurgedKFold interno


# ─────────────────────────────────────────────────────────────────────────────
# Objetivo Optuna
# ─────────────────────────────────────────────────────────────────────────────

def _objective(trial: optuna.Trial, ticker: str, df: pd.DataFrame) -> float:
    """
    Avalia um conjunto de hiperparâmetros via PurgedKFold OOS médio.
    Retorna PF médio OOS (a ser maximizado).
    """
    params = dict(
        # Sprint-2
        use_regime_filter      = True,
        adx_threshold          = trial.suggest_float("adx_threshold",   15.0, 40.0),
        hurst_threshold        = trial.suggest_float("hurst_threshold",  0.45, 0.65),
        use_vol_targeting      = True,
        vol_target_annual      = trial.suggest_float("vol_target_annual", 0.10, 0.30),
        vol_scalar_min         = 0.25,
        vol_scalar_max         = 2.0,
        # Sprint-2 ensemble
        use_ensemble           = True,
        ensemble_ema_cross     = True,
        ensemble_breakout      = True,
        ensemble_breakout_window = trial.suggest_int("breakout_window", 5, 40),
        # Sprint-3/4 meta
        use_meta_labeler       = True,
        meta_min_prob          = trial.suggest_float("meta_min_prob",   0.40, 0.75),
        meta_n_estimators      = 50,   # fixo p/ velocidade
        meta_auto_train        = True,
        # Risco
        atr_stop_multiplier    = trial.suggest_float("atr_stop",        1.0, 3.0),
        atr_target_multiplier  = trial.suggest_float("atr_target",      1.5, 5.0),
    )

    n   = len(df)
    idx = np.arange(n)
    pkf = PurgedKFold(n_splits=N_FOLDS, embargo_pct=0.01)
    # Usa DatetimeIndex do df como pred_times
    X_dummy = pd.DataFrame(index=df.index)

    fold_pfs: list[float] = []
    for tr_idx, te_idx in pkf.split(X_dummy):
        if len(te_idx) < 15:
            continue
        is_df  = df.iloc[tr_idx]
        oos_df = df.iloc[te_idx]

        # Treina meta no IS (rápido — n_estimators=50)
        s_is = CombinedStrategy(ticker, name="opt_is")
        s_is.set_data(is_df.copy())
        s_is.params.update(params)
        s_is.prepare()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s_is.train_meta_labeler()
        ml_trained = s_is._meta_labeler

        # Avalia OOS
        s_oos = CombinedStrategy(ticker, name="opt_oos")
        s_oos.set_data(oos_df.copy())
        s_oos.params.update(params)
        s_oos._meta_labeler = ml_trained
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = Backtester(s_oos, initial_capital=CAPITAL, cooldown_bars=COOLDOWN,
                           commission_per_trade=COMMISSION,
                           slippage_pct=SLIPPAGE).run()

        pf = m.get("profit_factor", 0) or 0
        tc = m.get("trade_count", 0) or 0
        if tc < 3:
            pf = 0.0   # penaliza configs com poucos trades (nao significativos)
        elif not np.isfinite(pf):
            pf = 3.0   # cap: inf PF (sem perdas) = bom mas incerto — cap em 3x
        fold_pfs.append(pf)

    return float(np.mean(fold_pfs)) if fold_pfs else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def optimize(ticker: str, n_trials: int = 30) -> None:
    end   = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=730)).isoformat()

    df, src = download(ticker, start=start, end=end, interval="1d")
    if df is None or df.empty:
        print(f"  Sem dados para {ticker}"); return

    print("=" * 70)
    print(f"  Optuna — {ticker} ({len(df)} barras, {n_trials} trials)")
    print("=" * 70)

    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=42),
        study_name=f"sprint4_{ticker.replace('^','').replace('=','')}",
    )
    study.optimize(
        lambda t: _objective(t, ticker, df),
        n_trials=n_trials,
        show_progress_bar=False,
    )

    best = study.best_trial
    print(f"\n  Melhor PF OOS médio: {best.value:.4f}")
    print(f"  Trial #{best.number} — parâmetros:")
    for k, v in best.params.items():
        print(f"    {k:<30} = {v:.4f}" if isinstance(v, float) else f"    {k:<30} = {v}")

    # Top-5
    trials_df = study.trials_dataframe()
    top5 = trials_df.nlargest(5, "value")[["number", "value"] +
           [c for c in trials_df.columns if c.startswith("params_")]]
    print(f"\n  Top-5 trials:")
    print(top5.to_string(index=False))

    # Importância de parâmetros (Optuna built-in)
    try:
        imp = optuna.importance.get_param_importances(study)
        print(f"\n  Importancia dos parametros:")
        for param, importance in sorted(imp.items(), key=lambda x: -x[1]):
            bar = "#" * int(importance * 30)
            print(f"    {param:<30} {importance:.3f}  {bar}")
    except Exception as exc:
        print(f"\n  (importancia indisponivel: {exc})")

    print("\n" + "=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Optuna hyperparameter optimization")
    parser.add_argument("--ticker",  default="^BVSP", help="Ticker (default ^BVSP)")
    parser.add_argument("--trials",  type=int, default=30, help="Número de trials (default 30)")
    args = parser.parse_args()
    optimize(args.ticker, n_trials=args.trials)


if __name__ == "__main__":
    main()
