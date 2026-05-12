# scripts/portfolio_sprint13.py — Carteira Sprint-13 com 1/N
"""Roda a config Sprint-13 em múltiplos tickers simultaneamente,
agrega as curvas de equity e reporta métricas de carteira.

Compara contra:
  • Cada ticker individual (Sprint-13)
  • Carteira buy-and-hold equal-weight

Inclui dois cenários:
  A. Carteira BR equities (^BVSP, VALE3.SA, PETR4.SA) — thresholds padrão
  B. Carteira diversificada (+ BRL=X com thresholds adaptativos forex)

Uso:
    python scripts/portfolio_sprint13.py
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

DEFAULT_PARAMS = dict(
    use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
    use_vol_targeting=True, vol_target_annual=0.15,
    use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
    macro_direction_lock=True, macro_direction_window=60,
    macro_direction_ret_min=0.08, macro_direction_hurst_min=0.55,
    use_partial_exit=True, partial_exit_r=1.0, partial_exit_fraction=0.5,
    breakeven_offset_atr=0.0,
    use_chandelier_after_be=True, chandelier_atr_mult=3.0,
)

# Sprint-15: thresholds relaxados para forex (oscilação mais contida)
FOREX_PARAMS = dict(DEFAULT_PARAMS,
    macro_direction_window=90,
    macro_direction_ret_min=0.03,
    macro_direction_hurst_min=0.50,
)


def _split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = int(len(df) * IS_RATIO)
    return df.iloc[:n].copy(), df.iloc[n:].copy()


def _equity_series(bt: Backtester) -> pd.Series:
    return pd.Series(bt.equity, index=pd.DatetimeIndex(bt.equity_dates))


def _portfolio_metrics(equity: pd.Series, capital0: float) -> dict:
    rets = equity.pct_change().dropna()
    peak = equity.cummax()
    dd = (equity / peak) - 1
    mdd = abs(dd.min()) * 100 if len(dd) else 0.0
    total_ret = (equity.iloc[-1] / capital0 - 1) * 100
    sharpe = 0.0
    if len(rets) > 5 and rets.std() > 0:
        sharpe = float(np.sqrt(252) * rets.mean() / rets.std())
    return {
        "ret_pct": total_ret,
        "mdd_pct": mdd,
        "sharpe":  sharpe,
        "bars":    len(equity),
    }


def run_ticker(ticker: str, capital: float, params: dict
               ) -> tuple[pd.Series, dict, dict]:
    """Roda Sprint-13 config no ticker; retorna (equity_series, metrics, bh_metrics)."""
    df, _ = download(ticker, START, END, interval="1d")
    _, oos = _split(df)
    s = CombinedStrategy(ticker)
    s.set_data(oos.copy())
    s.params.update(params)
    bt = Backtester(s, initial_capital=capital, cooldown_bars=2,
                    commission_per_trade=0.001, slippage_pct=0.001)
    m = bt.run()
    eq = _equity_series(bt)
    # Buy-and-hold equity equivalente
    closes = oos["Close"]
    bh_eq = capital * (closes / closes.iloc[0])
    bh_eq.index = pd.DatetimeIndex(bh_eq.index)
    bh = _portfolio_metrics(bh_eq, capital)
    strat_summary = {
        "trades": len(bt.trades),
        "pf":     m.get("profit_factor", 0) or 0,
        "ret":    (m.get("return_pct", 0) or 0) * 100,
        "mdd":    m.get("max_drawdown", 0) or 0,
        "sharpe": m.get("sharpe_ratio", 0) or 0,
        "winr":   (m.get("win_rate", 0) or 0) * 100,
    }
    return eq, strat_summary, bh, bh_eq


def aggregate_portfolio(equities: dict[str, pd.Series],
                        capital0: float) -> pd.Series:
    """Soma curvas de equity num índice de datas unificado.

    Para datas onde um ticker não tem amostra, ffill (equity inalterada).
    """
    all_dates = sorted(set().union(*[set(eq.index) for eq in equities.values()]))
    master = pd.DatetimeIndex(all_dates)
    aligned = []
    for tk, eq in equities.items():
        s = eq.reindex(master).ffill()
        s = s.fillna(capital0 / len(equities))  # antes do primeiro bar
        aligned.append(s)
    total = sum(aligned)
    return total


def main():
    print("=" * 88)
    print(" Sprint-15: Carteira agregada Sprint-13 — equal-weight 1/N")
    print("=" * 88)

    # ── Cenário A: BR equities (^BVSP, VALE3.SA, PETR4.SA) ────────────────
    A_TICKERS = ["^BVSP", "VALE3.SA", "PETR4.SA"]
    print(f"\n[A] Carteira BR equities ({len(A_TICKERS)} tickers, thresholds padrão)")
    print("-" * 88)
    cap_each = CAPITAL / len(A_TICKERS)
    eqs_A: dict[str, pd.Series] = {}
    bh_eqs_A: dict[str, pd.Series] = {}
    for tk in A_TICKERS:
        eq, summ, _bh, bh_eq = run_ticker(tk, cap_each, DEFAULT_PARAMS)
        eqs_A[tk] = eq; bh_eqs_A[tk] = bh_eq
        print(f"  {tk:10s}  T={summ['trades']:>2}  PF={summ['pf']:.2f}  "
              f"Ret={summ['ret']:+.2f}%  Sharpe={summ['sharpe']:+.2f}  "
              f"WinR={summ['winr']:.1f}%")

    port_A = aggregate_portfolio(eqs_A, CAPITAL)
    bh_port_A = aggregate_portfolio(bh_eqs_A, CAPITAL)
    mA   = _portfolio_metrics(port_A, CAPITAL)
    bhA  = _portfolio_metrics(bh_port_A, CAPITAL)
    print()
    print(f"  CARTEIRA  Ret={mA['ret_pct']:+.2f}%  MDD={mA['mdd_pct']:.2f}%  "
          f"Sharpe={mA['sharpe']:+.2f}")
    print(f"  B&H 1/N   Ret={bhA['ret_pct']:+.2f}%  MDD={bhA['mdd_pct']:.2f}%  "
          f"Sharpe={bhA['sharpe']:+.2f}")
    print(f"  Alpha     {mA['ret_pct'] - bhA['ret_pct']:+.2f}pp  "
          f"(Sharpe d {mA['sharpe'] - bhA['sharpe']:+.2f})")

    # ── Cenário B: + BRL=X com thresholds forex ───────────────────────────
    B_TICKERS = ["^BVSP", "VALE3.SA", "PETR4.SA", "BRL=X"]
    print(f"\n[B] Carteira diversificada ({len(B_TICKERS)} tickers, BRL=X adaptado)")
    print("-" * 88)
    cap_each = CAPITAL / len(B_TICKERS)
    eqs_B: dict[str, pd.Series] = {}
    bh_eqs_B: dict[str, pd.Series] = {}
    for tk in B_TICKERS:
        params = FOREX_PARAMS if tk == "BRL=X" else DEFAULT_PARAMS
        eq, summ, _bh, bh_eq = run_ticker(tk, cap_each, params)
        eqs_B[tk] = eq; bh_eqs_B[tk] = bh_eq
        print(f"  {tk:10s}  T={summ['trades']:>2}  PF={summ['pf']:.2f}  "
              f"Ret={summ['ret']:+.2f}%  Sharpe={summ['sharpe']:+.2f}  "
              f"WinR={summ['winr']:.1f}%")

    port_B = aggregate_portfolio(eqs_B, CAPITAL)
    bh_port_B = aggregate_portfolio(bh_eqs_B, CAPITAL)
    mB   = _portfolio_metrics(port_B, CAPITAL)
    bhB  = _portfolio_metrics(bh_port_B, CAPITAL)
    print()
    print(f"  CARTEIRA  Ret={mB['ret_pct']:+.2f}%  MDD={mB['mdd_pct']:.2f}%  "
          f"Sharpe={mB['sharpe']:+.2f}")
    print(f"  B&H 1/N   Ret={bhB['ret_pct']:+.2f}%  MDD={bhB['mdd_pct']:.2f}%  "
          f"Sharpe={bhB['sharpe']:+.2f}")
    print(f"  Alpha     {mB['ret_pct'] - bhB['ret_pct']:+.2f}pp  "
          f"(Sharpe d {mB['sharpe'] - bhB['sharpe']:+.2f})")

    # ── Resumo ────────────────────────────────────────────────────────────
    print()
    print("=" * 88)
    print(" Resumo: diversificação melhora o Sharpe agregado?")
    print("=" * 88)
    print(f"  [A] 3 BR equities       Sharpe carteira={mA['sharpe']:+.2f}  MDD={mA['mdd_pct']:.2f}%")
    print(f"  [B] +BRL=X (forex)      Sharpe carteira={mB['sharpe']:+.2f}  MDD={mB['mdd_pct']:.2f}%")


if __name__ == "__main__":
    main()
