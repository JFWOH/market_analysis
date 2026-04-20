#!/usr/bin/env python
# dashboard.py — Sprint-5 passo 3: Dashboard CLI de monitoramento em tempo real
"""
Dashboard de monitoramento em texto puro (sem dependências externas além do
core do projeto). Exibe:

  1. Status do mercado atual: preço, tendência, ADX, Hurst, vol realizada
  2. Estado do meta-labeler: treinado?, ROC-AUC, importância top-5
  3. Sinais ativos (os últimos N dias): tipo, estratégia, forca, meta_prob
  4. Métricas de qualidade dos últimos 90 dias (backtester rápido)
  5. Feature importance (microestrutura + técnico)

Uso:
    python dashboard.py                        # BVSP com configuração padrão
    python dashboard.py --ticker BRL=X         # outro ticker
    python dashboard.py --optimized            # usa params Optuna
    python dashboard.py --refresh 60           # atualiza a cada 60s
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.fetch_real_data import download
from strategy import CombinedStrategy
from backtester import Backtester
from meta_labeler import build_features

# ─────────────────────────────────────────────────────────────────────────────
# Configuração "otimizada" (Sprint-4 Optuna)
# ─────────────────────────────────────────────────────────────────────────────

OPTUNA_PARAMS = dict(
    use_regime_filter        = True,  adx_threshold=18.49, hurst_threshold=0.508,
    use_vol_targeting        = True,  vol_target_annual=0.173,
    use_ensemble             = True,  ensemble_ema_cross=True, ensemble_breakout=True,
    ensemble_breakout_window = 21,
    use_meta_labeler         = True,  meta_min_prob=0.675, meta_n_estimators=200,
    atr_stop_multiplier      = 1.40,  atr_target_multiplier=3.30,
)

# ─────────────────────────────────────────────────────────────────────────────
# Formatação
# ─────────────────────────────────────────────────────────────────────────────

W = 72   # largura da caixa

def _box(title: str) -> str:
    inner = f" {title} "
    pad_l = (W - len(inner)) // 2
    pad_r = W - pad_l - len(inner)
    return "+" + "-" * pad_l + inner + "-" * pad_r + "+"

def _line(text: str = "") -> str:
    return f"| {text:<{W - 2}} |"

def _sep() -> str:
    return "+" + "-" * W + "+"

def _bar(val: float, max_val: float = 1.0, width: int = 20) -> str:
    filled = int(round(val / max_val * width)) if max_val > 0 else 0
    filled = max(0, min(filled, width))
    return "[" + "#" * filled + "." * (width - filled) + "]"


# ─────────────────────────────────────────────────────────────────────────────
# Seções do dashboard
# ─────────────────────────────────────────────────────────────────────────────

def _section_market(s: CombinedStrategy) -> list[str]:
    """Status de mercado atual."""
    lines = [_box("MERCADO ATUAL"), _sep()]
    data = s.data
    if data is None or data.empty:
        return lines + [_line("(sem dados)"), _sep()]

    last = data.iloc[-1]
    prev = data.iloc[-2] if len(data) > 1 else last

    close = float(last.get("Close", 0))
    chg   = (close / float(prev.get("Close", close)) - 1) * 100

    adx   = last.get("ADX",          np.nan)
    hurst = last.get("Hurst",        np.nan)
    rv    = last.get("Realized_Vol", np.nan)
    rsi   = last.get("RSI",         np.nan)
    di_p  = last.get("DI_Plus",     np.nan)
    di_m  = last.get("DI_Minus",    np.nan)

    # Regime
    if not np.isnan(adx) and not np.isnan(hurst):
        trend_ok = adx >= 18.0 and hurst >= 0.50
        regime   = "TRENDING  " if trend_ok else "RANGING   "
    else:
        regime = "UNKNOWN   "

    # Vol scalar (se vol targeting)
    rv_val = float(rv) if not np.isnan(rv) else None
    scalar = round(min(2.0, max(0.25, 0.173 / rv_val)), 2) if rv_val else 1.0

    lines += [
        _line(f"Ticker   : {s.ticker:<10}  Data: {data.index[-1].strftime('%Y-%m-%d')}"),
        _line(f"Preco    : {close:>12,.2f}   Variacao: {chg:+.2f}%"),
        _line(f"Regime   : {regime}   ADX: {adx:5.1f}   Hurst: {hurst:.3f}"),
        _line(f"Vol Real : {rv:.4f}        Vol Scalar: {scalar:.2f}x"),
        _line(f"RSI      : {rsi:5.1f}      DI+: {di_p:5.1f}   DI-: {di_m:5.1f}"),
        _sep(),
    ]
    return lines


def _section_signals(signals: list[dict], n_show: int = 8) -> list[str]:
    """Sinais recentes."""
    lines = [_box(f"SINAIS RECENTES (ultimos {n_show})"), _sep()]
    if not signals:
        return lines + [_line("  Nenhum sinal gerado."), _sep()]

    recent = signals[-n_show:]
    header = f"  {'Data':<12} {'Tipo':<8} {'Estrategia':<16} {'Preco':>10} {'Forca':>5} {'MetaP':>6}"
    lines.append(_line(header))
    lines.append(_line("  " + "-" * 62))
    for sg in reversed(recent):
        ts    = str(sg.get("data", ""))[:10]
        tipo  = sg.get("tipo", "")[:7]
        estr  = str(sg.get("estrategia", ""))[:14]
        preco = sg.get("preco", 0) or 0
        forca = sg.get("forca", 0) or 0
        mprob = sg.get("meta_prob", None)
        mp    = f"{mprob:.2f}" if mprob is not None else "  N/A"
        lines.append(_line(f"  {ts:<12} {tipo:<8} {estr:<16} {preco:>10,.0f} {forca:>5} {mp:>6}"))
    lines.append(_sep())
    return lines


def _section_meta(s: CombinedStrategy) -> list[str]:
    """Estado do meta-labeler."""
    lines = [_box("META-LABELER"), _sep()]
    ml = s._meta_labeler
    if ml is None or not ml._fitted:
        lines += [_line("  Nao treinado."), _sep()]
        return lines

    roc  = ml.cv_roc_auc
    fi   = ml.feature_importance()
    prob = ml.min_prob

    lines.append(_line(f"  Treinado: Sim   min_prob: {prob:.2f}   CV ROC-AUC: "
                       f"{roc:.3f}" if roc else f"  Treinado: Sim   min_prob: {prob:.2f}"))

    if fi is not None:
        lines.append(_line("  Top-5 features:"))
        for feat, imp in fi.head(5).items():
            bar = _bar(imp, fi.iloc[0], width=15)
            lines.append(_line(f"    {feat:<28} {imp:.3f}  {bar}"))
    lines.append(_sep())
    return lines


def _section_perf(ticker: str, df_90: pd.DataFrame, params: dict) -> list[str]:
    """Performance rápida nos últimos 90 dias."""
    lines = [_box("PERFORMANCE — ultimos 90 dias"), _sep()]
    if df_90 is None or len(df_90) < 20:
        return lines + [_line("  Dados insuficientes."), _sep()]

    s = CombinedStrategy(ticker)
    s.set_data(df_90.copy())
    s.params.update(params)
    m = Backtester(s, initial_capital=100_000.0, cooldown_bars=2,
                   commission_per_trade=0.001, slippage_pct=0.001).run()

    tc  = m.get("trade_count",  0) or 0
    pf  = m.get("profit_factor",0) or 0
    ret = (m.get("return_pct",  0) or 0) * 100
    dd  = m.get("max_drawdown", 0) or 0
    wr  = (m.get("win_rate",    0) or 0) * 100
    sh  = m.get("sharpe_ratio", 0) or 0

    pf_bar  = _bar(min(pf, 2.0), 2.0)
    wr_bar  = _bar(wr, 100.0)

    lines += [
        _line(f"  Trades  : {tc}"),
        _line(f"  PF      : {pf:.3f}  {pf_bar}"),
        _line(f"  Retorno : {ret:+.2f}%"),
        _line(f"  Max DD  : {dd:.3f}%"),
        _line(f"  Win Rate: {wr:.1f}%  {wr_bar}"),
        _line(f"  Sharpe  : {sh:.3f}"),
        _sep(),
    ]
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Render completo
# ─────────────────────────────────────────────────────────────────────────────

def render(ticker: str, use_optimized: bool = False) -> None:
    """Busca dados, computa e imprime o dashboard."""
    now   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    end   = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    start_90 = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()

    df, src = download(ticker, start=start, end=end, interval="1d")
    if df is None or df.empty:
        print(f"[ERRO] Sem dados para {ticker}"); return

    params = OPTUNA_PARAMS if use_optimized else {}

    # Estratégia principal (ano completo)
    s = CombinedStrategy(ticker)
    s.set_data(df.copy())
    s.params.update(params)
    s.prepare()
    if use_optimized:
        s.train_meta_labeler()
    signals = s.generate_signals()

    # Janela 90 dias
    df_90, _ = download(ticker, start=start_90, end=end, interval="1d")
    base_params = {k: v for k, v in params.items() if k != "use_meta_labeler"}

    # Renderiza
    out: list[str] = []
    out.append(_sep())
    out.append(_line(f"DASHBOARD — {ticker}   [{now}]   fonte: {src}"))
    out.append(_line(f"Modo: {'Otimizado (Optuna)' if use_optimized else 'Padrao'}  "
                     f"| {len(df)} barras (1 ano)"))
    out.append(_sep())

    out += _section_market(s)
    out += _section_signals(signals, n_show=6)
    out += _section_meta(s)
    out += _section_perf(ticker, df_90, base_params)

    print("\n".join(out))


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard CLI de monitoramento")
    parser.add_argument("--ticker",    default="^BVSP", help="Ticker (default ^BVSP)")
    parser.add_argument("--optimized", action="store_true",
                        help="Usar params Optuna (Sprint-4)")
    parser.add_argument("--refresh",   type=int, default=0,
                        help="Intervalo de atualizacao em segundos (0 = uma vez)")
    args = parser.parse_args()

    if args.refresh > 0:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            render(args.ticker, use_optimized=args.optimized)
            print(f"\n  (Atualizando em {args.refresh}s — Ctrl+C para sair)")
            try:
                time.sleep(args.refresh)
            except KeyboardInterrupt:
                print("\n  Dashboard encerrado.")
                break
    else:
        render(args.ticker, use_optimized=args.optimized)


if __name__ == "__main__":
    main()
