"""
scripts/walk_forward_sprint4.py — Walk-forward Sprint-4: sistema completo.

Compara em dados reais (^BVSP, BRL=X diário):
  0. Baseline         — Sprint-1 somente
  1. Sprint-2         — regime + vol targeting + ensemble
  2. Sprint-2 + Meta  — tudo + meta-labeler

Método: 5-fold walk-forward (70% IS / 30% OOS) sem grid search —
mede a qualidade OOS de cada configuração fixa.

Uso:
    python scripts/walk_forward_sprint4.py
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
# Configurações a comparar
# ─────────────────────────────────────────────────────────────────────────────

CONFIGS = {
    "Baseline": {},
    "Sprint-2 (R+VT+Ens)": dict(
        use_regime_filter=True,  adx_threshold=25.0, hurst_threshold=0.50,
        use_vol_targeting=True,  vol_target_annual=0.15,
        use_ensemble=True,       ensemble_ema_cross=True, ensemble_breakout=True,
    ),
    "Sprint-2+Meta": dict(
        use_regime_filter=True,  adx_threshold=25.0, hurst_threshold=0.50,
        use_vol_targeting=True,  vol_target_annual=0.15,
        use_ensemble=True,       ensemble_ema_cross=True, ensemble_breakout=True,
        use_meta_labeler=True,   meta_min_prob=0.55,      meta_n_estimators=100,
    ),
}

N_FOLDS    = 5
IS_RATIO   = 0.70
CAPITAL    = 100_000.0
COMMISSION = 0.001
SLIPPAGE   = 0.001
COOLDOWN   = 2


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward
# ─────────────────────────────────────────────────────────────────────────────

def _run_bt(ticker: str, df: pd.DataFrame, **params) -> dict:
    s = CombinedStrategy(ticker, name="wf")
    s.set_data(df.copy())
    s.params.update(params)
    return Backtester(s, initial_capital=CAPITAL, cooldown_bars=COOLDOWN,
                      commission_per_trade=COMMISSION,
                      slippage_pct=SLIPPAGE).run()


def walk_forward(ticker: str, df: pd.DataFrame) -> dict[str, dict]:
    """Executa WF para todos os configs; retorna métricas OOS agregadas."""
    n      = len(df)
    result: dict[str, list] = {name: [] for name in CONFIGS}

    for fold in range(N_FOLDS):
        fold_size = n // N_FOLDS
        is_end    = fold_size * (fold + 1)
        oos_end   = min(is_end + fold_size, n) if fold < N_FOLDS - 1 else n
        # IS: primeiros is_end barras; OOS: is_end → oos_end
        # (WF walk-forward expandindo janela IS)
        is_df  = df.iloc[:is_end]
        oos_df = df.iloc[is_end:oos_end]
        if len(oos_df) < 20:
            continue

        for name, params in CONFIGS.items():
            # Para o meta-labeler: treina no IS, avalia no OOS
            if params.get("use_meta_labeler", False):
                # Treina em IS
                s_is = CombinedStrategy(ticker, name="is")
                s_is.set_data(is_df.copy())
                s_is.params.update(params)
                s_is.prepare()
                s_is.train_meta_labeler()
                ml_trained = s_is._meta_labeler

                # Roda OOS com modelo treinado no IS
                s_oos = CombinedStrategy(ticker, name="oos")
                s_oos.set_data(oos_df.copy())
                s_oos.params.update(params)
                s_oos._meta_labeler = ml_trained   # injeta modelo IS
                m = Backtester(s_oos, initial_capital=CAPITAL, cooldown_bars=COOLDOWN,
                               commission_per_trade=COMMISSION,
                               slippage_pct=SLIPPAGE).run()
            else:
                m = _run_bt(ticker, oos_df, **params)

            result[name].append({
                "fold":         fold + 1,
                "oos_bars":     len(oos_df),
                "trade_count":  m.get("trade_count", 0) or 0,
                "profit_factor":m.get("profit_factor", 0) or 0,
                "return_pct":   (m.get("return_pct", 0) or 0) * 100,
                "max_drawdown": m.get("max_drawdown", 0) or 0,
                "sharpe":       m.get("sharpe_ratio", 0) or 0,
            })

    # Agrega folds
    agg: dict[str, dict] = {}
    for name, folds in result.items():
        if not folds:
            agg[name] = {}
            continue
        df_folds = pd.DataFrame(folds)
        agg[name] = {
            "folds":      len(df_folds),
            "trades_avg": df_folds["trade_count"].mean(),
            "pf_avg":     df_folds["profit_factor"].mean(),
            "pf_std":     df_folds["profit_factor"].std(),
            "ret_avg":    df_folds["return_pct"].mean(),
            "dd_avg":     df_folds["max_drawdown"].mean(),
            "sharpe_avg": df_folds["sharpe"].mean(),
        }
    return agg


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    end   = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=730)).isoformat()

    tickers = ["^BVSP", "BRL=X"]

    print("=" * 76)
    print(f"{'WALK-FORWARD Sprint-4 — Sistema Completo (5-fold OOS)':^76}")
    print("=" * 76)

    for ticker in tickers:
        df, src = download(ticker, start=start, end=end, interval="1d")
        if df is None or df.empty:
            print(f"  {ticker}: sem dados"); continue
        print(f"\n  [{ticker}] {len(df)} barras — {src}")
        print(f"  {'Config':<28} {'Folds':>5} {'Trades/f':>9} "
              f"{'PF avg':>8} {'PF±':>6} {'Ret%':>8} {'DD%':>8} {'Sharpe':>8}")
        print("  " + "-" * 74)

        agg = walk_forward(ticker, df)
        for name, m in agg.items():
            if not m:
                print(f"  {name:<28}  —"); continue
            mark = " <<" if name == "Sprint-2+Meta" else ""
            print(f"  {name:<28} {m['folds']:>5} {m['trades_avg']:>9.1f} "
                  f"{m['pf_avg']:>8.3f} {m['pf_std']:>6.3f} "
                  f"{m['ret_avg']:>8.2f} {m['dd_avg']:>8.3f} "
                  f"{m['sharpe_avg']:>8.3f}{mark}")

    print("\n" + "=" * 76)


if __name__ == "__main__":
    main()
