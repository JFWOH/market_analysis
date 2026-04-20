"""Benchmark empírico: Partial Exit + Breakeven vs baseline.

Compara o mesmo grid de sinais (mesmo seed, mesmos dados sintéticos)
com e sem ``use_partial_exit`` habilitado, medindo o impacto em
Profit Factor, Sharpe, Win Rate e capital final.

Dados: OHLC sintético com volatilidade calibrada para Mini Índice
(~1.2%/dia) e Mini Dólar (~0.7%/dia). Seed fixo = reprodutível.
"""
from __future__ import annotations

import os
import sys
import numpy as np
import pandas as pd

# Permite rodar direto: `python scripts/bench_partial_exit.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtester import Backtester
from strategy import CombinedStrategy


def make_synthetic(n_days: int, daily_vol: float, start: float,
                   seed: int) -> pd.DataFrame:
    """Gera OHLC diário sintético com drift ~0 e vol calibrada."""
    rng = np.random.default_rng(seed)
    log_ret = rng.normal(loc=0.0, scale=daily_vol, size=n_days)
    close = start * np.exp(np.cumsum(log_ret))
    # High/Low como fração da vol intra-bar (~0.6 * daily_vol)
    intra = np.abs(rng.normal(0, daily_vol * 0.6, size=n_days))
    high = close * (1 + intra)
    low  = close * (1 - intra)
    open_ = np.concatenate(([start], close[:-1]))
    dates = pd.date_range('2024-01-01', periods=n_days, freq='B')
    return pd.DataFrame({
        'Open':  open_,
        'High':  np.maximum(high, np.maximum(open_, close)),
        'Low':   np.minimum(low,  np.minimum(open_, close)),
        'Close': close,
        'Volume': rng.integers(1_000_000, 5_000_000, size=n_days).astype(float),
    }, index=dates)


def run_case(label: str, data: pd.DataFrame, ticker: str,
             use_partial: bool) -> dict:
    strat = CombinedStrategy(ticker, name=label)
    strat.set_data(data.copy())
    strat.params.update({
        'use_partial_exit':       use_partial,
        'partial_exit_r':         1.0,
        'partial_exit_fraction':  0.5,
        'breakeven_offset_atr':   0.1,   # pequeno buffer para cobrir custos
    })
    bt = Backtester(strat, initial_capital=100_000.0, cooldown_bars=4)
    m = bt.run()
    return m


def fmt_delta(base: float, new: float, pct: bool = False) -> str:
    if base == 0:
        return f"{new:+.3f}"
    delta = new - base
    if pct:
        return f"{delta:+.2%}"
    return f"{delta:+.3f}"


def print_comparison(asset: str, base: dict, new: dict) -> None:
    print(f"\n  === {asset} ===")
    print(f"  {'Métrica':<22} {'baseline':>12} {'com partial':>12} {'delta':>12}")
    print(f"  {'-'*22} {'-'*12} {'-'*12} {'-'*12}")
    rows = [
        ('Profit Factor',      'profit_factor',     3, False),
        ('Win Rate',           'win_rate',          4, True),
        ('Sharpe Ratio',       'sharpe_ratio',      3, False),
        ('Max Drawdown (%)',   'max_drawdown',      2, False),
        ('Retorno Total',      'return_pct',        4, True),
        ('Trade Count',        'trade_count',       0, False),
        ('Expectativa (R$)',   'expectancy',        2, False),
    ]
    for lbl, key, dec, is_pct in rows:
        b, n = base.get(key, 0), new.get(key, 0)
        if isinstance(b, float) and (b == float('inf') or np.isnan(b)):
            b = 0.0
        if isinstance(n, float) and (n == float('inf') or np.isnan(n)):
            n = 0.0
        if is_pct:
            print(f"  {lbl:<22} {b:>12.{dec}%} {n:>12.{dec}%} "
                  f"{fmt_delta(b, n, pct=True):>12}")
        else:
            print(f"  {lbl:<22} {b:>12.{dec}f} {n:>12.{dec}f} "
                  f"{fmt_delta(b, n):>12}")


def main() -> None:
    print("=" * 70)
    print("  BENCHMARK — Sprint-1 passo 3 (Partial Exit + Breakeven)")
    print("  dados sintéticos, seed fixo, 500 pregões, cooldown=4")
    print("=" * 70)

    scenarios = [
        ('Mini Indice (^BVSP)',  '^BVSP',     0.012,  120_000.0, 42),
        ('Mini Dolar (USDBRL)',  'USDBRL=X',  0.007,  5.20,      17),
    ]

    for asset, ticker, vol, start, seed in scenarios:
        data = make_synthetic(n_days=500, daily_vol=vol, start=start, seed=seed)
        base = run_case(f"{asset} baseline", data, ticker, use_partial=False)
        new  = run_case(f"{asset} +partial", data, ticker, use_partial=True)
        if not base or not new:
            print(f"\n  !!! {asset}: sem trades — pulando.")
            continue
        print_comparison(asset, base, new)

    print("\n" + "=" * 70)
    print("  Interpretação:")
    print("  - PF > 1 via partial ataca quase-losers (convertidos em BE~0).")
    print("  - Espera-se PF levemente maior, DD levemente menor, trade count")
    print("    estável (partial NÃO adiciona entradas, só divide saídas).")
    print("=" * 70)


if __name__ == '__main__':
    main()
