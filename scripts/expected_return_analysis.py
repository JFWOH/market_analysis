# scripts/expected_return_analysis.py — Análise de Retorno Esperado
"""
Consolida métricas de performance via três metodologias:
  1. OOS único 70/30 — comparativo de configurações
  2. Walk-Forward 5-fold — estabilidade do PF entre folds
  3. Monte Carlo Bootstrap + GBM — distribuição prospectiva

Uso:
    python scripts/expected_return_analysis.py
"""
from __future__ import annotations
import datetime, os, sys, warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from scripts.fetch_real_data import download
from strategy import CombinedStrategy
from backtester import Backtester
from stress_test import StressTester


# ─────────────────────────────────────────────────────────────────────────────
TICKER   = "^BVSP"
CAPITAL  = 100_000.0
N_FOLDS  = 5
IS_RATIO = 0.70
N_SIM    = 2000

# max_drawdown já é retornado em % pelo backtester (eq/peak - 1) * 100
# return_pct é fração decimal (0.12 = 12%)

CONFIGS = {
    "Baseline": {},
    "Sprint-2 (Regime+VT+Ens)": dict(
        use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
        use_vol_targeting=True, vol_target_annual=0.15,
        use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
    ),
    "Sprint-2+Meta (min_prob=0.50)": dict(
        use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
        use_vol_targeting=True, vol_target_annual=0.15,
        use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
        use_meta_labeler=True, meta_min_prob=0.50, meta_n_estimators=100,
    ),
    "Sprint-2+Fibonacci": dict(
        use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
        use_vol_targeting=True, vol_target_annual=0.15,
        use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
        ensemble_fibonacci=True, fib_swing_window=20,
        fib_min_swing_atr=3.0, fib_tolerance_atr=0.5, fib_min_strength=7,
    ),
    "Sprint-10+FibMacro60": dict(
        use_regime_filter=True, adx_threshold=25.0, hurst_threshold=0.50,
        use_vol_targeting=True, vol_target_annual=0.15,
        use_ensemble=True, ensemble_ema_cross=True, ensemble_breakout=True,
        ensemble_fibonacci=True, fib_swing_window=20,
        fib_min_swing_atr=3.0, fib_tolerance_atr=0.5, fib_min_strength=7,
        fib_regime_bypass=False, fib_regime_macro_window=60,
        fib_macro_adx_min=20.0, fib_macro_hurst_min=0.50,
    ),
}

BEST_CFG = "Sprint-2 (Regime+VT+Ens)"


def _run_oos(is_df, oos_df, params):
    """Treina em IS (se meta), avalia sempre no OOS."""
    use_meta = params.get("use_meta_labeler", False)
    ml_trained = None

    if use_meta:
        s_is = CombinedStrategy(TICKER, name="is")
        s_is.set_data(is_df.copy())
        s_is.params.update(params)
        s_is.prepare()
        s_is.train_meta_labeler()
        ml_trained = s_is._meta_labeler

    s_oos = CombinedStrategy(TICKER, name="oos")
    s_oos.set_data(oos_df.copy())
    s_oos.params.update(params)
    if ml_trained is not None:
        s_oos._meta_labeler = ml_trained

    bt = Backtester(s_oos, initial_capital=CAPITAL, cooldown_bars=2,
                    commission_per_trade=0.001, slippage_pct=0.001)
    m = bt.run()
    return m, bt.trades


def _wf_fold(df, fold, params):
    n         = len(df)
    fold_size = n // N_FOLDS
    is_end    = fold_size * (fold + 1)
    oos_end   = min(is_end + fold_size, n) if fold < N_FOLDS - 1 else n
    is_df     = df.iloc[:is_end]
    oos_df    = df.iloc[is_end:oos_end]
    if len(oos_df) < 20:
        return None
    m, _ = _run_oos(is_df, oos_df, params)
    return m


# ─────────────────────────────────────────────────────────────────────────────
W = 72
def _sep():  return "+" + "=" * W + "+"
def _sub():  return "+" + "-" * W + "+"
def _hdr(t): return f"|  {'--- ' + t + ' ---':^{W-3}}|"
def _line(t): return f"| {t:<{W-1}}|"


def main():
    end   = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=730)).isoformat()
    df, src = download(TICKER, start=start, end=end, interval="1d")
    n     = len(df)
    n_is  = int(n * IS_RATIO)
    n_oos = n - n_is
    is_df  = df.iloc[:n_is]
    oos_df = df.iloc[n_is:]
    date_start   = str(df.index[0])[:10]
    date_is_end  = str(is_df.index[-1])[:10]
    date_oos_end = str(oos_df.index[-1])[:10]
    # Retorno do índice BVSP no período OOS (buy-and-hold)
    bh_ret = (oos_df["Close"].iloc[-1] / oos_df["Close"].iloc[0] - 1.0) * 100

    print(_sep())
    print(_line(f"ANALISE DE RETORNO ESPERADO — {TICKER}"))
    print(_line(f"Periodo total : {date_start} a {date_oos_end}  ({n} pregoes)"))
    print(_line(f"IS  (treino)  : {n_is} barras  ate {date_is_end}"))
    print(_line(f"OOS (avaliacao): {n_oos} barras  {date_is_end} a {date_oos_end}"))
    print(_line(f"Buy-and-Hold IBOVESPA no OOS: {bh_ret:+.2f}%"))
    print(_sep())

    # ─────────────────────────────────────────────────────────────────────────
    # 1. OOS 70/30
    # ─────────────────────────────────────────────────────────────────────────
    print(_hdr("1. OOS FINAL 70/30 — comparativo"))
    print(_line(f"  {'Config':<34} {'Trd':>4} {'PF':>6} {'Ret%':>7} "
                f"{'MDD%':>6} {'Sharpe':>7} {'WinR%':>7}"))
    print(_sub())

    oos_all = {}
    for label, params in CONFIGS.items():
        m, trades = _run_oos(is_df, oos_df, params)
        tc = m.get("trade_count",   0) or 0
        pf = m.get("profit_factor", 0) or 0
        if pf == float("inf"): pf = 999.0
        rt = (m.get("return_pct",   0) or 0) * 100
        dd =  m.get("max_drawdown", 0) or 0       # já em %
        sh =  m.get("sharpe_ratio", 0) or 0
        wr = (m.get("win_rate",     0) or 0) * 100
        oos_all[label] = {"m": m, "trades": trades,
                          "tc": tc, "pf": pf, "rt": rt, "dd": dd, "sh": sh, "wr": wr}
        mark = " <<" if label == BEST_CFG else ""
        print(_line(f"  {label:<34} {tc:>4} {pf:>6.3f} {rt:>7.2f} "
                    f"{dd:>6.2f} {sh:>7.3f} {wr:>7.1f}{mark}"))

    best = oos_all[BEST_CFG]
    best_trades = best["trades"]
    best_m      = best["m"]
    wins   = [t["pnl"] for t in best_trades if t.get("pnl", 0) > 0]
    losses = [t["pnl"] for t in best_trades if t.get("pnl", 0) < 0]
    avg_win  = np.mean(wins)   if wins   else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    rr       = abs(avg_win / avg_loss) if avg_loss else 0.0
    exp_per_trade = (avg_win*len(wins) + avg_loss*len(losses)) / max(len(best_trades), 1)
    ann_factor    = 252.0 / max(n_oos, 1)
    ann_ret       = (best_m.get("return_pct", 0) or 0) * ann_factor * 100
    alpha         = best["rt"] - bh_ret

    print(_sub())
    print(_line(f"  Detalhes — {BEST_CFG}:"))
    print(_line(f"    Avg win : R$ {avg_win:>+10,.0f}   |   Avg loss: R$ {avg_loss:>+10,.0f}"))
    print(_line(f"    R:R medio              : 1:{rr:.2f}"))
    print(_line(f"    Expectativa / trade    : R$ {exp_per_trade:>+,.0f}"))
    print(_line(f"    Retorno OOS            : {best['rt']:>+7.2f}%  (R$ {best['rt']/100*CAPITAL:>+,.0f})"))
    print(_line(f"    Retorno anualizado est.: {ann_ret:>+7.2f}%"))
    print(_line(f"    Alpha vs IBOV OOS      : {alpha:>+7.2f}%"))
    print(_sep())

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Walk-Forward 5-fold
    # ─────────────────────────────────────────────────────────────────────────
    print(_hdr("2. WALK-FORWARD 5-FOLD — estabilidade temporal"))
    print(_line(f"  {'Config':<34} {'Fld':>3} {'PF med':>7} {'PF std':>7} "
                f"{'Ret med%':>9} {'MDD med%':>9} {'Sh med':>7}"))
    print(_sub())

    wf_data = {}
    for label, params in CONFIGS.items():
        fold_ms = []
        for fold in range(N_FOLDS):
            fm = _wf_fold(df, fold, params)
            if fm: fold_ms.append(fm)
        if not fold_ms:
            print(_line(f"  {label:<34}  sem trades"))
            continue
        pfs  = [min(fm.get("profit_factor", 0) or 0, 9.99) for fm in fold_ms]
        rets = [(fm.get("return_pct", 0) or 0) * 100 for fm in fold_ms]
        dds  = [fm.get("max_drawdown", 0) or 0 for fm in fold_ms]
        shs  = [fm.get("sharpe_ratio", 0) or 0 for fm in fold_ms]
        wf_data[label] = {"pfs": pfs, "rets": rets, "dds": dds, "shs": shs}
        mark = " <<" if label == BEST_CFG else ""
        print(_line(f"  {label:<34} {len(fold_ms):>3} {np.median(pfs):>7.3f} "
                    f"{np.std(pfs):>7.3f} {np.median(rets):>9.2f} "
                    f"{np.median(dds):>9.2f} {np.median(shs):>7.3f}{mark}"))

    if BEST_CFG in wf_data:
        wd = wf_data[BEST_CFG]
        print(_sub())
        print(_line(f"  {BEST_CFG} — retorno por fold:"))
        positive = 0
        for i, (r, p) in enumerate(zip(wd["rets"], wd["pfs"]), 1):
            bar = ("#" * min(int(abs(r)*2), 18)) if r >= 0 else ("x" * min(int(abs(r)*2), 18))
            prefix = "+" if r >= 0 else " "
            if r >= 0: positive += 1
            print(_line(f"    Fold {i}: {r:>+6.2f}%  PF={p:.3f}  |{bar}"))
        print(_line(f"    Folds lucrativos: {positive}/{len(wd['rets'])}  "
                    f"({positive/len(wd['rets'])*100:.0f}% de consistencia)"))
    print(_sep())

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Monte Carlo
    # ─────────────────────────────────────────────────────────────────────────
    print(_hdr(f"3. MONTE CARLO ({N_SIM} simulacoes) — distribuicao de retorno"))

    if len(best_trades) >= 3:
        st   = StressTester(best_trades, initial_capital=CAPITAL)
        rng  = np.random.default_rng(42)
        boot = st.bootstrap(n_sim=N_SIM, rng=rng)
        gbm  = st.gbm_jump(n_sim=N_SIM, rng=rng)
        frp  = boot["final_ret_pct"]
        ruin_pct = boot["n_ruin"] / N_SIM * 100

        print(_line(f"  Bootstrap ({len(best_trades)} trades OOS reamostrados):"))
        print(_line(f"    Retorno esperado (mediana p50)  : {frp['p50']:>+7.2f}%"))
        print(_line(f"    Intervalo 90%%  (p05 a p95)     : {frp['p05']:>+7.2f}%  a  {frp['p95']:>+7.2f}%"))
        print(_line(f"    Intervalo 50%%  (p25 a p75)     : {frp['p25']:>+7.2f}%  a  {frp['p75']:>+7.2f}%"))
        print(_line(f"    VaR 95%%  (perda max. esperada) : {boot['var95']:>7.2f}%  "
                    f"(R$ {boot['var95']/100*CAPITAL:>,.0f})"))
        print(_line(f"    CVaR 95%% (Expected Shortfall)  : {boot['cvar95']:>7.2f}%  "
                    f"(R$ {boot['cvar95']/100*CAPITAL:>,.0f})"))
        print(_line(f"    MDD median / MDD p95           : {boot['mdd_median']:>6.2f}% / {boot['mdd_p95']:>6.2f}%"))
        print(_line(f"    Simulacoes com ruina (>80%%)    : {boot['n_ruin']:>4}/{N_SIM}  ({ruin_pct:.1f}%)"))
        print(_sub())
        print(_line(f"  GBM + Jump Diffusion "
                    f"(sigma={gbm['sigma_used']:.4f}, mu={gbm['mu_used']:+.4f}):"))
        print(_line(f"    Cenario pessimista (p05)        : {gbm['ret_p05']:>+7.2f}%"))
        print(_line(f"    Cenario base      (p50)         : {gbm['ret_p50']:>+7.2f}%"))
        print(_line(f"    Cenario otimista  (p95)         : {gbm['ret_p95']:>+7.2f}%"))
        print(_line(f"    MDD median / MDD p95            : {gbm['mdd_median']:>6.2f}% / {gbm['mdd_p95']:>6.2f}%"))
    else:
        frp = {"p50": 0, "p05": 0, "p95": 0, "p25": 0, "p75": 0}
        boot = {"var95": 0, "cvar95": 0, "mdd_median": 0, "mdd_p95": 0, "n_ruin": 0}
        ruin_pct = 0.0
        print(_line(f"  Poucos trades ({len(best_trades)}) para simulacao robusta."))
    print(_sep())

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Síntese
    # ─────────────────────────────────────────────────────────────────────────
    print(_hdr("4. SINTESE — Retorno Esperado e Perfil de Risco"))
    print(_sub())
    print(_line(f"  Instrumento      : {TICKER}"))
    print(_line(f"  Configuracao     : {BEST_CFG}"))
    print(_line(f"  Capital simulado : R$ {CAPITAL:,.0f}"))
    print(_sub())

    # Métricas OOS reais
    rt  = best["rt"]
    pf  = best["pf"]
    dd  = best["dd"]
    sh  = best["sh"]
    wr  = best["wr"]
    tc  = best["tc"]

    print(_line(f"  RETORNO (OOS historico, {n_oos} barras)"))
    print(_line(f"    Total             : {rt:>+7.2f}%   (R$ {rt/100*CAPITAL:>+10,.0f})"))
    print(_line(f"    Anualizado (est.) : {ann_ret:>+7.2f}%"))
    print(_line(f"    Alpha vs IBOV     : {alpha:>+7.2f}%"))
    print(_line(f"    Trades OOS        : {tc}   Win rate: {wr:.1f}%   R:R medio: 1:{rr:.2f}"))
    print(_sub())

    print(_line(f"  RETORNO (Monte Carlo p50 — bootstrap)"))
    print(_line(f"    Mediana           : {frp['p50']:>+7.2f}%   "
                f"(R$ {frp['p50']/100*CAPITAL:>+10,.0f})"))
    print(_line(f"    Intervalo 50%%    : {frp['p25']:>+7.2f}%  a  {frp['p75']:>+7.2f}%"))
    print(_sub())

    print(_line(f"  RISCO"))
    print(_line(f"    Profit Factor     : {pf:.3f}"))
    print(_line(f"    Sharpe Ratio      : {sh:.3f}"))
    print(_line(f"    Max Drawdown OOS  : {dd:.2f}%   (R$ {dd/100*CAPITAL:,.0f})"))
    print(_line(f"    VaR 95%%          : {boot['var95']:.2f}%   (R$ {boot['var95']/100*CAPITAL:,.0f})"))
    print(_line(f"    CVaR 95%%         : {boot['cvar95']:.2f}%   (R$ {boot['cvar95']/100*CAPITAL:,.0f})"))
    print(_sub())

    # Semáforo
    checks = [
        ("Profit Factor > 1.3",         pf > 1.3),
        ("Sharpe > 0.5",                 sh > 0.5),
        ("Max Drawdown < 5%",            dd < 5.0),
        ("Win Rate > 50%",               wr > 50.0),
        ("Alpha positivo vs IBOV",       alpha > 0),
        (f"Ruina < 2% ({ruin_pct:.1f}%)", ruin_pct < 2.0),
    ]
    ok  = sum(1 for _, v in checks if v)
    tot = len(checks)
    print(_line(f"  AVALIACAO QUALITATIVA ({ok}/{tot} criterios OK)"))
    for label_c, passed in checks:
        status = "[OK]     " if passed else "[ATENCAO]"
        print(_line(f"    {status}  {label_c}"))
    print(_sep())


if __name__ == "__main__":
    main()
