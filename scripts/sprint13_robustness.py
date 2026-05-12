# scripts/sprint13_robustness.py — Robustez da config Sprint-13
"""Cross-ticker + sweep de chandelier_atr_mult.

Verifica:
  (a) Sprint-13 generaliza para outros instrumentos (BRL=X, PETR4.SA, VALE3.SA)
      além de ^BVSP, ou está overfit ao OOS 70/30 do IBOV.
  (b) Existe plateau de robustez em chandelier_atr_mult [1.5..4.0]
      ou o ganho é frágil em torno de 3.0.

Uso:
    python scripts/sprint13_robustness.py
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from scripts.fetch_real_data import download
from strategy import CombinedStrategy
from backtester import Backtester


CAPITAL  = 100_000.0
IS_RATIO = 0.70
START    = "2024-04-01"
END      = "2026-04-17"

TICKERS = ["^BVSP", "BRL=X", "PETR4.SA", "VALE3.SA"]
SWEEP   = [1.5, 2.0, 2.5, 3.0, 4.0]


def base_params(chandelier_mult: float) -> dict:
    return dict(
        use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
        use_vol_targeting=True, vol_target_annual=0.15,
        use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
        macro_direction_lock=True, macro_direction_window=60,
        macro_direction_ret_min=0.08, macro_direction_hurst_min=0.55,
        use_partial_exit=True, partial_exit_r=1.0, partial_exit_fraction=0.5,
        breakeven_offset_atr=0.0,
        use_chandelier_after_be=True, chandelier_atr_mult=chandelier_mult,
    )


def _split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = int(len(df) * IS_RATIO)
    return df.iloc[:n].copy(), df.iloc[n:].copy()


def _run_oos(ticker: str, oos: pd.DataFrame, params: dict) -> dict:
    s = CombinedStrategy(ticker, name="oos")
    s.set_data(oos)
    s.params.update(params)
    bt = Backtester(s, initial_capital=CAPITAL, cooldown_bars=2,
                    commission_per_trade=0.001, slippage_pct=0.001)
    m = bt.run()
    return {
        "trades": len(bt.trades),
        "pf":     m.get("profit_factor", 0) or 0,
        "ret":    (m.get("return_pct", 0) or 0) * 100,
        "mdd":    m.get("max_drawdown", 0) or 0,
        "sharpe": m.get("sharpe_ratio", 0) or 0,
        "winr":   m.get("win_rate", 0) or 0,
    }


def _bh_return(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 0.0
    return ((float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0])) - 1) * 100


def main():
    print("=" * 88)
    print(" Sprint-14: Robustez Sprint-13 — cross-ticker + sweep chandelier_atr_mult")
    print("=" * 88)

    cache: dict[str, pd.DataFrame] = {}
    for tk in TICKERS:
        try:
            df, src = download(tk, START, END, interval="1d")
            cache[tk] = df
            print(f"  {tk:10s} {len(df):4d} bars  ({src})")
        except Exception as e:
            print(f"  {tk:10s} FAIL: {e}")

    print()
    print("=" * 88)

    rows: list[dict] = []
    for tk, df in cache.items():
        is_df, oos_df = _split(df)
        bh = _bh_return(oos_df)
        line_parts: list[str] = []
        for m in SWEEP:
            try:
                r = _run_oos(tk, oos_df, base_params(m))
                line_parts.append(
                    f"  ch={m}: T={r['trades']:>2} PF={r['pf']:.2f} "
                    f"Ret={r['ret']:+.2f}% Sh={r['sharpe']:+.2f}"
                )
                rows.append({"ticker": tk, "ch_mult": m, **r, "bh_oos": bh})
            except Exception as e:
                line_parts.append(f"  ch={m}: ERR ({e.__class__.__name__})")
        print(f"\n{tk:10s} B&H_OOS={bh:+.2f}%")
        for lp in line_parts:
            print(lp)

    print()
    print("=" * 88)
    print(" Resumo: melhor chandelier_atr_mult por ticker (por Sharpe OOS)")
    print("=" * 88)
    df_res = pd.DataFrame(rows)
    if not df_res.empty:
        for tk in df_res["ticker"].unique():
            sub = df_res[df_res["ticker"] == tk].sort_values("sharpe", ascending=False)
            best = sub.iloc[0]
            print(f"  {tk:10s} best ch={best['ch_mult']}  "
                  f"PF={best['pf']:.2f}  Ret={best['ret']:+.2f}%  "
                  f"Sharpe={best['sharpe']:+.2f}  WinR={best['winr']*100:.1f}%  "
                  f"(vs B&H {best['bh_oos']:+.2f}%)")

        # Estabilidade: std do Sharpe entre tickers no mesmo mult
        print()
        print(" Estabilidade do sweep (média±std de Sharpe entre tickers):")
        agg = df_res.groupby("ch_mult").agg(
            sharpe_mean=("sharpe", "mean"),
            sharpe_std=("sharpe", "std"),
            pf_mean=("pf", "mean"),
            ret_mean=("ret", "mean"),
        ).round(3)
        print(agg.to_string())


if __name__ == "__main__":
    main()
