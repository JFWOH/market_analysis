# scripts/bear_market_validation.py — Sprint-16: validação em bears históricos
"""Hipótese: a config Sprint-13 ("ultra-defensiva") deve PRESERVAR capital
melhor que buy-and-hold em mercados de baixa, mesmo que perca em bull.

Testa janelas históricas conhecidamente adversas:
  • 2008 GFC               (^BVSP, ^GSPC)        ~50% drawdown global
  • 2020 COVID crash       (^BVSP, ^GSPC)        ~35% drawdown rápido
  • 2022 bear (Fed hikes)  (^GSPC, ^IXIC)        ~25% drawdown NASDAQ
  • 2015-16 BR mini-bear   (^BVSP)               ~30% queda

Métrica-chave: ESTRATÉGIA_MDD vs B&H_MDD. Se hipótese vale, MDD da
estratégia deve ser dramaticamente menor (mesmo que retorno seja
modesto ou levemente negativo).

Uso:
    python scripts/bear_market_validation.py
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

SPRINT13_PARAMS = dict(
    use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
    use_vol_targeting=True, vol_target_annual=0.15,
    use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
    macro_direction_lock=True, macro_direction_window=60,
    macro_direction_ret_min=0.08, macro_direction_hurst_min=0.55,
    use_partial_exit=True, partial_exit_r=1.0, partial_exit_fraction=0.5,
    breakeven_offset_atr=0.0,
    use_chandelier_after_be=True, chandelier_atr_mult=3.0,
)

# Cada cenário: (label, ticker, prewarmup_start, evaluate_start, evaluate_end)
# O prewarmup é necessário para indicadores (60+20 bars de ADX/Hurst/Fib).
SCENARIOS = [
    ("2008 GFC ^BVSP",    "^BVSP", "2007-06-01", "2008-06-01", "2009-06-01"),
    ("2008 GFC ^GSPC",    "^GSPC", "2007-06-01", "2008-06-01", "2009-06-01"),
    ("COVID 2020 ^BVSP",  "^BVSP", "2019-06-01", "2020-01-01", "2020-06-30"),
    ("COVID 2020 ^GSPC",  "^GSPC", "2019-06-01", "2020-01-01", "2020-06-30"),
    ("2022 bear ^GSPC",   "^GSPC", "2021-06-01", "2022-01-01", "2022-12-31"),
    ("2022 bear ^IXIC",   "^IXIC", "2021-06-01", "2022-01-01", "2022-12-31"),
    ("2015 BR ^BVSP",     "^BVSP", "2014-06-01", "2015-01-01", "2016-01-31"),
]


def _bh_metrics(closes: pd.Series, capital: float) -> dict:
    """Retorna métricas de buy-and-hold sobre a série de closes."""
    eq = capital * (closes / float(closes.iloc[0]))
    peak = eq.cummax()
    dd = (eq / peak) - 1
    return {
        "ret_pct": float((eq.iloc[-1] / capital - 1) * 100),
        "mdd_pct": float(abs(dd.min()) * 100),
    }


def _strat_metrics(df: pd.DataFrame, ticker: str) -> dict:
    s = CombinedStrategy(ticker)
    s.set_data(df.copy())
    s.params.update(SPRINT13_PARAMS)
    bt = Backtester(s, initial_capital=CAPITAL, cooldown_bars=2,
                    commission_per_trade=0.001, slippage_pct=0.001)
    m = bt.run()
    return {
        "trades": len(bt.trades),
        "pf":     m.get("profit_factor", 0) or 0,
        "ret":    (m.get("return_pct", 0) or 0) * 100,
        "mdd":    m.get("max_drawdown", 0) or 0,
        "sharpe": m.get("sharpe_ratio", 0) or 0,
        "winr":   (m.get("win_rate", 0) or 0) * 100,
    }


def main():
    print("=" * 96)
    print(" Sprint-16: Validacao Sprint-13 em bears historicos")
    print("=" * 96)
    print()

    results = []

    for label, ticker, prewarm, eval_start, eval_end in SCENARIOS:
        try:
            df, _ = download(ticker, prewarm, eval_end, interval="1d")
        except Exception as e:
            print(f"[{label}] FAIL download: {e}")
            continue

        # Estratégia: roda com o pré-aquecimento incluído, mas as métricas
        # do backtester só registram trades nos bars processados.
        # Vamos cortar o df para [prewarm.., eval_end] e deixar warmup p/ indicadores.
        eval_mask = (df.index >= eval_start) & (df.index <= eval_end)
        if eval_mask.sum() < 20:
            print(f"[{label}] WARN: poucos bars no periodo de eval ({eval_mask.sum()})")
            continue

        # Métricas B&H restritas ao período de eval (sem warmup)
        closes_eval = df.loc[eval_mask, "Close"]
        bh = _bh_metrics(closes_eval, CAPITAL)

        # Strat: roda sobre [prewarm..eval_end] mas calculamos métricas do
        # SUBSET no período de eval. Para simplicidade, cortamos o df p/
        # eval com 90 bars de warmup antes.
        warmup_start_idx = max(0, df.index.get_indexer([eval_start])[0] - 90)
        df_run = df.iloc[warmup_start_idx:].copy()
        strat = _strat_metrics(df_run, ticker)

        results.append({
            "scenario": label,
            "ticker":   ticker,
            "bh_ret":   bh["ret_pct"],
            "bh_mdd":   bh["mdd_pct"],
            "st_trd":   strat["trades"],
            "st_pf":    strat["pf"],
            "st_ret":   strat["ret"],
            "st_mdd":   strat["mdd"],
            "st_sharpe": strat["sharpe"],
            "st_winr":  strat["winr"],
        })

    # ── Print tabela ──────────────────────────────────────────────────────
    print()
    print(f"  {'Cenario':<24s}  {'B&H Ret':>8s} {'B&H MDD':>8s}  "
          f"{'Trd':>3s} {'PF':>5s} {'StRet':>7s} {'StMDD':>7s} {'StSh':>6s} {'WinR':>5s}")
    print("  " + "-" * 92)
    for r in results:
        print(f"  {r['scenario']:<24s}  "
              f"{r['bh_ret']:+7.2f}% {r['bh_mdd']:7.2f}%  "
              f"{r['st_trd']:>3d} {r['st_pf']:5.2f} "
              f"{r['st_ret']:+6.2f}% {r['st_mdd']:6.2f}% "
              f"{r['st_sharpe']:+5.2f} {r['st_winr']:4.1f}%")

    # ── Análise ───────────────────────────────────────────────────────────
    if results:
        df_r = pd.DataFrame(results)
        # MDD ratio: estrategia / B&H. < 1.0 = estrategia protege melhor.
        df_r["mdd_ratio"] = df_r["st_mdd"] / df_r["bh_mdd"].replace(0, np.nan)
        # Retorno relativo: ret_strat - ret_bh (em pontos percentuais).
        df_r["alpha_pp"] = df_r["st_ret"] - df_r["bh_ret"]

        print()
        print("=" * 96)
        print(" Hipotese: 'defensiva brilha em bears' — validacao")
        print("=" * 96)
        print()
        print(f"  Mediana MDD estrategia : {df_r['st_mdd'].median():.2f}%")
        print(f"  Mediana MDD B&H        : {df_r['bh_mdd'].median():.2f}%")
        print(f"  Mediana razao MDD est/B&H : {df_r['mdd_ratio'].median():.2f}x")
        print(f"  Mediana alpha (ret strat - ret B&H) : {df_r['alpha_pp'].median():+.2f}pp")
        print()
        wins_mdd = (df_r["mdd_ratio"] < 0.5).sum()
        wins_alpha = (df_r["alpha_pp"] > 0).sum()
        print(f"  Cenarios com MDD < 50% do B&H : {wins_mdd}/{len(df_r)}")
        print(f"  Cenarios com alpha positivo   : {wins_alpha}/{len(df_r)}")


if __name__ == "__main__":
    main()
