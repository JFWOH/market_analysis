"""Benchmark empírico: filtro de horário intraday vs baseline.

Gera OHLC 1h sintético cobrindo pregão B3 (10-17h) por 60 dias úteis com
volatilidade elevada na abertura/fechamento (modelagem do smile intraday).
Compara três cenários:
    1. baseline (sem filtro)
    2. filtro padrão (10:15-16:45)
    3. filtro agressivo (11:00-15:00 + skip lunch)
"""
from __future__ import annotations

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtester import Backtester
from strategy import CombinedStrategy


def make_intraday_1h(n_days: int, daily_vol: float, start: float,
                      seed: int) -> pd.DataFrame:
    """1h bars com 'volatility smile' — vol mais alta no open/close/lunch."""
    rng = np.random.default_rng(seed)
    rows, idx = [], []
    price = start
    bdays = pd.bdate_range("2024-01-02", periods=n_days)
    hours = list(range(10, 18))   # 10:00..17:00 = 8 barras/dia

    # Fator de vol por hora (smile): abertura e fechamento 2x, almoço 1.5x
    vol_factor = {
        10: 2.0, 11: 1.0, 12: 1.5, 13: 1.5,
        14: 1.0, 15: 1.0, 16: 1.2, 17: 2.2,
    }
    hourly_base = daily_vol / np.sqrt(8)

    for d in bdays:
        for h in hours:
            ts = pd.Timestamp(d) + pd.Timedelta(hours=h)
            v = hourly_base * vol_factor[h]
            ret = rng.normal(0, v)
            new_price = price * np.exp(ret)
            hi = max(price, new_price) * (1 + abs(rng.normal(0, v * 0.3)))
            lo = min(price, new_price) * (1 - abs(rng.normal(0, v * 0.3)))
            rows.append((price, hi, lo, new_price, float(rng.integers(1e5, 1e6))))
            idx.append(ts)
            price = new_price
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx),
                        columns=["Open", "High", "Low", "Close", "Volume"])


def run_case(label: str, data: pd.DataFrame, ticker: str,
             use_filter: bool, aggressive: bool = False) -> dict:
    strat = CombinedStrategy(ticker, name=label)
    strat.set_data(data.copy())
    strat.params.update({
        # Passo 3 ligado em todos os cenários (melhor baseline honesto)
        'use_partial_exit':       True,
        'partial_exit_r':         1.0,
        'partial_exit_fraction':  0.5,
        'breakeven_offset_atr':   0.1,
        # Passo 4 — parâmetro sob teste
        'use_time_filter':        use_filter,
    })
    if aggressive:
        strat.params.update({
            'time_filter_start_hour':   11,
            'time_filter_start_minute': 0,
            'time_filter_end_hour':     15,
            'time_filter_end_minute':   0,
            'time_filter_skip_lunch':   True,
        })
    bt = Backtester(strat, initial_capital=100_000.0, cooldown_bars=4)
    return bt.run()


def print_row(lbl: str, m: dict) -> None:
    pf = m.get('profit_factor', 0)
    pf_str = f"{pf:>8.3f}" if pf != float('inf') else "     inf"
    print(f"  {lbl:<28} "
          f"PF={pf_str}  "
          f"WR={m.get('win_rate', 0):>6.1%}  "
          f"Sharpe={m.get('sharpe_ratio', 0):>+6.2f}  "
          f"DD={m.get('max_drawdown', 0):>5.2f}%  "
          f"Ret={m.get('return_pct', 0):>+6.2%}  "
          f"Trades={m.get('trade_count', 0):>3d}")


def main() -> None:
    print("=" * 88)
    print("  BENCHMARK - Sprint-1 passo 4 (Filtro de horario intraday)")
    print("  dados sinteticos 1h, 60 dias uteis (~480 barras), cooldown=4, passo3 ON")
    print("=" * 88)

    scenarios = [
        ('Mini Indice', '^BVSP',    0.012, 120_000.0, 42),
        ('Mini Dolar',  'USDBRL=X', 0.007,    5.20,   17),
    ]

    for asset, ticker, vol, start, seed in scenarios:
        data = make_intraday_1h(n_days=60, daily_vol=vol, start=start, seed=seed)
        print(f"\n  === {asset} ({len(data)} barras 1h) ===")
        base = run_case(f"{asset} baseline",   data, ticker, use_filter=False)
        std  = run_case(f"{asset} filtro std", data, ticker, use_filter=True)
        agg  = run_case(f"{asset} filtro agr", data, ticker, use_filter=True, aggressive=True)
        print_row("baseline (sem filtro)",       base)
        print_row("filtro padrao 10:15-16:45",   std)
        print_row("filtro agressivo 11-15 +LN",  agg)

    print("\n" + "=" * 88)
    print("  Hipotese: filtro remove ruido de abertura/fechamento/almoco")
    print("  -> espera-se PF >=, DD <= e trade count menor (sinais filtrados)")
    print("=" * 88)


if __name__ == '__main__':
    main()
