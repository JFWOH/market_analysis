"""
scripts/oos_final.py — Validação OOS final com parâmetros Optuna.

Sprint-5 passo 2: aplica os melhores parâmetros encontrados pelo Optuna
(Sprint-4 passo 3) num split IS/OOS nunca visto:
  - IS: primeiros 70% dos dados (2024-05 até ~2025-07)
  - OOS: últimos 30% (2025-07 até 2026-04) — NOT touched during optimization

Compara 4 configurações no OOS:
  0. Baseline (sem Sprint)
  1. Params Optuna (adx=18.5, breakout=21, meta_min_prob=0.675, etc.)
  2. Params Optuna + microestrutura (Sprint-5 passo 1)
  3. Sprint-2 default (como referência)

Uso:
    python scripts/oos_final.py
"""
from __future__ import annotations

import datetime
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.fetch_real_data import download
from strategy import CombinedStrategy
from backtester import Backtester

# ─────────────────────────────────────────────────────────────────────────────
# Melhores parâmetros encontrados pelo Optuna (Sprint-4, trial #3, BVSP)
# ─────────────────────────────────────────────────────────────────────────────

OPTUNA_BEST = dict(
    use_regime_filter        = True,
    adx_threshold            = 18.49,
    hurst_threshold          = 0.508,
    use_vol_targeting        = True,
    vol_target_annual        = 0.173,
    vol_scalar_min           = 0.25,
    vol_scalar_max           = 2.0,
    use_ensemble             = True,
    ensemble_ema_cross       = True,
    ensemble_breakout        = True,
    ensemble_breakout_window = 21,
    use_meta_labeler         = True,
    meta_min_prob            = 0.675,
    meta_n_estimators        = 200,
    meta_auto_train          = True,
    atr_stop_multiplier      = 1.40,
    atr_target_multiplier    = 3.30,
)

CONFIGS = {
    "Baseline":               {},
    "Sprint-2 default":       dict(
        use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
        use_vol_targeting=True, vol_target_annual=0.15,
        use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
    ),
    "Optuna best":            OPTUNA_BEST,
    "Optuna best (retrain)":  {**OPTUNA_BEST, "meta_n_estimators": 300},
}

CAPITAL    = 100_000.0
IS_RATIO   = 0.70
COMMISSION = 0.001
SLIPPAGE   = 0.001
COOLDOWN   = 2


def _run(ticker: str, df: pd.DataFrame, is_df: pd.DataFrame,
         oos_df: pd.DataFrame, label: str, params: dict) -> dict:
    """Treina (se necessário) em IS, avalia em OOS."""
    use_meta = params.get("use_meta_labeler", False)

    if use_meta:
        s_is = CombinedStrategy(ticker, name="is")
        s_is.set_data(is_df.copy())
        s_is.params.update(params)
        s_is.prepare()
        s_is.train_meta_labeler()
        ml_trained = s_is._meta_labeler
    else:
        ml_trained = None

    s_oos = CombinedStrategy(ticker, name="oos")
    s_oos.set_data(oos_df.copy())
    s_oos.params.update(params)
    if ml_trained is not None:
        s_oos._meta_labeler = ml_trained

    return Backtester(
        s_oos,
        initial_capital=CAPITAL,
        cooldown_bars=COOLDOWN,
        commission_per_trade=COMMISSION,
        slippage_pct=SLIPPAGE,
    ).run()


def main() -> None:
    end   = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=730)).isoformat()

    tickers = ["^BVSP", "BRL=X"]

    print("=" * 78)
    print(f"{'OOS FINAL — Sistema Sprint-5 vs Optuna vs Baseline':^78}")
    print(f"  IS: primeiros {IS_RATIO*100:.0f}%   OOS: ultimos {(1-IS_RATIO)*100:.0f}% (nunca vistos)")
    print("=" * 78)

    for ticker in tickers:
        df, src = download(ticker, start=start, end=end, interval="1d")
        if df is None or df.empty:
            print(f"  {ticker}: sem dados"); continue

        n      = len(df)
        is_n   = int(n * IS_RATIO)
        is_df  = df.iloc[:is_n]
        oos_df = df.iloc[is_n:]

        print(f"\n  [{ticker}] total={n}  IS={len(is_df)}  OOS={len(oos_df)}  — {src}")
        print(f"  {'Config':<30} {'Trades':>7} {'PF':>7} {'Ret%':>8} "
              f"{'MaxDD%':>8} {'Sharpe':>8} {'WinR%':>7}")
        print("  " + "-" * 76)

        for label, params in CONFIGS.items():
            m  = _run(ticker, df, is_df, oos_df, label, params)
            tc = m.get("trade_count",  0) or 0
            pf = m.get("profit_factor", 0) or 0
            rt = (m.get("return_pct",   0) or 0) * 100
            dd = m.get("max_drawdown",  0) or 0
            sh = m.get("sharpe_ratio",  0) or 0
            wr = (m.get("win_rate",     0) or 0) * 100
            mark = " <<" if "Optuna" in label else ""
            print(f"  {label:<30} {tc:>7} {pf:>7.3f} {rt:>8.2f} "
                  f"{dd:>8.3f} {sh:>8.3f} {wr:>7.1f}{mark}")

        # Delta Optuna vs Baseline
        m_base = _run(ticker, df, is_df, oos_df, "B", {})
        m_opt  = _run(ticker, df, is_df, oos_df, "O", OPTUNA_BEST)
        dpf = (m_opt.get("profit_factor", 0) or 0) - (m_base.get("profit_factor", 0) or 0)
        ddd = (m_opt.get("max_drawdown",  0) or 0) - (m_base.get("max_drawdown",  0) or 0)
        print(f"\n  Delta Optuna vs Baseline: PF {dpf:+.3f}  DD {ddd:+.3f}")

    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()
