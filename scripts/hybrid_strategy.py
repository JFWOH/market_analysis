# scripts/hybrid_strategy.py — Sprint-17: Híbrido B&H + Sprint-13
"""Combina alocação fixa em buy-and-hold com a config Sprint-13.

Cada cenário (bull, bear, mix) é avaliado com pesos:
   0/100 (100% Sprint-13), 30/70, 50/50, 70/30, 100/0 (100% B&H)

Métricas: Ret%, MDD%, Sharpe, Calmar. Hipótese: 50/50 dá Sharpe
e Calmar superiores tanto a B&H puro quanto a estratégia pura,
porque diversifica regimes mantendo upside parcial em bulls.

Uso:
    python scripts/hybrid_strategy.py
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


CAPITAL = 100_000.0

SPRINT13 = dict(
    use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
    use_vol_targeting=True, vol_target_annual=0.15,
    use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
    macro_direction_lock=True, macro_direction_window=60,
    macro_direction_ret_min=0.08, macro_direction_hurst_min=0.55,
    use_partial_exit=True, partial_exit_r=1.0, partial_exit_fraction=0.5,
    breakeven_offset_atr=0.0,
    use_chandelier_after_be=True, chandelier_atr_mult=3.0,
)

ALLOCS = [
    ("100% Sprint-13", 0.0),
    ("30/70 BH/S13",   0.30),
    ("50/50 BH/S13",   0.50),
    ("70/30 BH/S13",   0.70),
    ("100% B&H",       1.0),
]

# (label, ticker, warmup_start, eval_start, eval_end)
SCENARIOS = [
    ("Bear 2008 ^BVSP",       "^BVSP", "2007-06-01", "2008-06-01", "2009-06-01"),
    ("Bear 2022 ^GSPC",       "^GSPC", "2021-06-01", "2022-01-01", "2022-12-31"),
    ("COVID 2020 ^BVSP",      "^BVSP", "2019-06-01", "2020-01-01", "2020-06-30"),
    ("Bull 2024-26 ^BVSP",    "^BVSP", "2024-04-01", "2025-04-01", "2026-04-17"),
    ("Bull 2024-26 VALE3.SA", "VALE3.SA", "2024-04-01", "2025-04-01", "2026-04-17"),
]


def _strat_equity(df_run: pd.DataFrame, ticker: str, capital: float) -> pd.Series:
    s = CombinedStrategy(ticker); s.set_data(df_run.copy())
    s.params.update(SPRINT13)
    bt = Backtester(s, initial_capital=capital, cooldown_bars=2,
                    commission_per_trade=0.001, slippage_pct=0.001)
    bt.run()
    return pd.Series(bt.equity, index=pd.DatetimeIndex(bt.equity_dates))


def _bh_equity(closes: pd.Series, capital: float) -> pd.Series:
    return capital * (closes / float(closes.iloc[0]))


def _metrics(eq: pd.Series, capital0: float) -> dict:
    rets = eq.pct_change().dropna()
    peak = eq.cummax(); dd = (eq / peak) - 1
    mdd = float(abs(dd.min()) * 100) if len(dd) else 0.0
    total_ret = float((eq.iloc[-1] / capital0 - 1) * 100)
    sharpe = 0.0
    if len(rets) > 5 and rets.std() > 0:
        sharpe = float(np.sqrt(252) * rets.mean() / rets.std())
    calmar = total_ret / mdd if mdd > 1e-9 else 0.0
    return {"ret": total_ret, "mdd": mdd, "sharpe": sharpe, "calmar": calmar}


def _run_scenario(label: str, ticker: str, warmup_start: str,
                  eval_start: str, eval_end: str) -> list[dict]:
    df, _ = download(ticker, warmup_start, eval_end, interval="1d")
    eval_mask = (df.index >= eval_start) & (df.index <= eval_end)
    if eval_mask.sum() < 20:
        return []

    warmup_idx = max(0, df.index.get_indexer([eval_start])[0] - 90)
    df_run = df.iloc[warmup_idx:].copy()

    # equity da estrategia, restrita ao periodo de eval
    strat_eq_full = _strat_equity(df_run, ticker, CAPITAL)
    strat_eq = strat_eq_full[strat_eq_full.index >= pd.Timestamp(eval_start)]
    if strat_eq.empty:
        return []
    # rebasear estrategia ao inicio do eval
    strat_eq = strat_eq * (CAPITAL / float(strat_eq.iloc[0]))

    # B&H sobre o periodo de eval
    closes_eval = df.loc[eval_mask, "Close"]
    bh_eq = _bh_equity(closes_eval, CAPITAL)

    # alinhar indices (interseccao)
    idx = strat_eq.index.intersection(bh_eq.index)
    strat_eq = strat_eq.reindex(idx).ffill()
    bh_eq    = bh_eq.reindex(idx).ffill()

    rows = []
    for alloc_label, w_bh in ALLOCS:
        # alocacao fixa nao-rebalanceada: cada componente comeca com sua quota.
        # Equity total = w_bh * bh_eq (rebaseado) + (1-w_bh) * strat_eq (rebaseado).
        # Cada componente comeca em CAPITAL no inicio, mas representam w*CAPITAL
        # logicamente, entao multiplicamos pelos pesos sobre o nivel rebaseado.
        bh_norm    = bh_eq    / float(bh_eq.iloc[0])
        strat_norm = strat_eq / float(strat_eq.iloc[0])
        port_eq = CAPITAL * (w_bh * bh_norm + (1 - w_bh) * strat_norm)
        m = _metrics(port_eq, CAPITAL)
        rows.append({"scenario": label, "alloc": alloc_label, **m})
    return rows


def main():
    print("=" * 96)
    print(" Sprint-17: Hibrido B&H + Sprint-13 — varias alocacoes em multiplos regimes")
    print("=" * 96)

    all_rows = []
    for sc in SCENARIOS:
        try:
            rs = _run_scenario(*sc)
            all_rows.extend(rs)
        except Exception as e:
            print(f"[{sc[0]}] FAIL: {e}")

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("Sem resultados.")
        return

    # Tabela por cenario
    print()
    for sc_label in df["scenario"].unique():
        sub = df[df["scenario"] == sc_label]
        print(f"\n  {sc_label}")
        print(f"  {'Alocacao':<18s}  {'Ret%':>8s}  {'MDD%':>7s}  {'Sharpe':>7s}  {'Calmar':>7s}")
        print("  " + "-" * 60)
        for _, r in sub.iterrows():
            print(f"  {r['alloc']:<18s}  {r['ret']:+7.2f}%  {r['mdd']:6.2f}%  "
                  f"{r['sharpe']:+6.2f}  {r['calmar']:+6.2f}")

    # Agregado por alocacao
    print()
    print("=" * 96)
    print(" Agregado: mediana entre cenarios por alocacao")
    print("=" * 96)
    agg = df.groupby("alloc").agg(
        ret_med    = ("ret", "median"),
        mdd_med    = ("mdd", "median"),
        sharpe_med = ("sharpe", "median"),
        calmar_med = ("calmar", "median"),
    ).round(3)
    # Mantem ordem original de ALLOCS
    agg = agg.reindex([a[0] for a in ALLOCS])
    print(agg.to_string())

    # Vencedor por metrica
    print()
    best_sharpe = agg["sharpe_med"].idxmax()
    best_calmar = agg["calmar_med"].idxmax()
    print(f"  Melhor Sharpe mediano: {best_sharpe} ({agg.loc[best_sharpe,'sharpe_med']:+.2f})")
    print(f"  Melhor Calmar mediano: {best_calmar} ({agg.loc[best_calmar,'calmar_med']:+.2f})")


if __name__ == "__main__":
    main()
