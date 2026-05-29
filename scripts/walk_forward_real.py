"""Walk-forward validation com dados reais do Yahoo Finance.

Setup:
  - 2 anos de dados diarios: ^BVSP e USDBRL=X  (2023-01-01 a 2024-12-31)
  - 3 anos de dados 1h para USDBRL=X             (2022-10-01 a 2024-12-31, max free)
  - 5 folds, 70/30 train/test
  - Grid Sprint-1: use_partial_exit x fraction x cooldown_bars (8 combos)
  - Para dados 1h: adiciona use_time_filter ao grid (16 combos)
  - Baseline: todos OFF (sem partial, sem cooldown, sem time filter)
  - Metricas OOS: PF, Sharpe, retorno, DD, trades

Fontes: Yahoo Finance v8 API (com fallback sintetico se indisponivel).
"""
from __future__ import annotations

import os
import sys
import itertools
import statistics
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtester import Backtester
from strategy import CombinedStrategy
from scripts.fetch_real_data import download


# ─────────────────────────────────────────────────────────────────────────────
# Grid
# ─────────────────────────────────────────────────────────────────────────────

def build_daily_grid() -> list[dict]:
    """8 combos: partial(2) x fraction(3) + sem-partial(2) - redundantes(6)."""
    combos: list[dict] = []
    for cd in [0, 4]:
        combos.append({'use_partial_exit': False, 'partial_exit_fraction': 0.5,
                       'cooldown_bars': cd, 'use_time_filter': False})
    for frac, cd in itertools.product([0.3, 0.5, 0.7], [0, 4]):
        combos.append({'use_partial_exit': True, 'partial_exit_fraction': frac,
                       'cooldown_bars': cd, 'use_time_filter': False})
    return combos


def build_intraday_grid() -> list[dict]:
    """16 combos: daily_grid x time_filter(on/off)."""
    combos = []
    for base in build_daily_grid():
        for tf in [False, True]:
            c = dict(base)
            c['use_time_filter'] = tf
            combos.append(c)
    return combos


# ─────────────────────────────────────────────────────────────────────────────
# Backtester wrapper
# ─────────────────────────────────────────────────────────────────────────────

def run_bt(data: pd.DataFrame, ticker: str, params: dict,
           capital: float = 100_000.0) -> dict:
    strat = CombinedStrategy(ticker, name="wf")
    strat.set_data(data.copy())
    strat.params.update({
        'use_partial_exit':       params['use_partial_exit'],
        'partial_exit_r':         1.0,
        'partial_exit_fraction':  params['partial_exit_fraction'],
        'breakeven_offset_atr':   0.1,
        'use_time_filter':        params.get('use_time_filter', False),
        'time_filter_start_hour': 10,
        'time_filter_start_minute': 15,
        'time_filter_end_hour':   16,
        'time_filter_end_minute': 45,
    })
    bt = Backtester(strat, initial_capital=capital,
                    cooldown_bars=params['cooldown_bars'])
    m = bt.run()
    return m


def _safe(m: dict, key: str, default: float = 0.0) -> float:
    v = m.get(key, default)
    if not isinstance(v, (int, float)):
        return default
    if v != v or abs(v) == float('inf'):   # nan or inf
        return default
    return float(v)


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward engine
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward(
    data: pd.DataFrame,
    ticker: str,
    label: str,
    n_folds: int,
    train_pct: float,
    grid: list[dict],
    baseline_params: dict,
) -> dict:
    n = len(data)
    fold_size = n // n_folds
    rows: list[dict[str, Any]] = []
    min_train = 40
    min_test  = 20

    print(f"\n  {'=' * 80}")
    print(f"  {label}  —  {n} barras reais, {n_folds} folds "
          f"({int(train_pct*100)}%%/{100 - int(train_pct*100)}%%)  "
          f"grid={len(grid)} combos")
    print(f"  {'=' * 80}")
    hdr = (f"  {'fold':>4}  {'train':>5}  {'test':>5}  "
           f"{'IS Sharpe':>9}  {'OOS PF':>6}  {'OOS SR':>7}  "
           f"{'OOS Ret':>8}  {'OOS DD':>6}  {'Trades':>6}  "
           f"{'base PF':>7}  {'best combo':<42}")
    print(hdr)
    print("  " + "-" * 125)

    for k in range(n_folds):
        start  = k * fold_size
        end    = start + fold_size if k < n_folds - 1 else n
        fold   = data.iloc[start:end]
        split  = int(len(fold) * train_pct)
        train  = fold.iloc[:split]
        test   = fold.iloc[split:]

        if len(train) < min_train or len(test) < min_test:
            continue

        # ── Grid search IS ─────────────────────────────────────────────────
        best_sr      = -float('inf')
        best_params  = None
        for params in grid:
            m = run_bt(train, ticker, params)
            sr = _safe(m, 'sharpe_ratio', -999)
            if m.get('trade_count', 0) >= 3 and sr > best_sr:
                best_sr     = sr
                best_params = params

        if best_params is None:
            best_params = grid[0]
            best_sr     = 0.0

        # ── OOS eval ───────────────────────────────────────────────────────
        m_oos  = run_bt(test, ticker, best_params)
        m_base = run_bt(test, ticker, baseline_params)

        r = {
            'fold':       k,
            'train_sz':   len(train),
            'test_sz':    len(test),
            'is_sr':      best_sr,
            'oos_pf':     _safe(m_oos,  'profit_factor'),
            'oos_sr':     _safe(m_oos,  'sharpe_ratio'),
            'oos_ret':    _safe(m_oos,  'return_pct'),
            'oos_dd':     _safe(m_oos,  'max_drawdown'),
            'oos_trades': int(m_oos.get('trade_count', 0)),
            'base_pf':    _safe(m_base, 'profit_factor'),
            'base_sr':    _safe(m_base, 'sharpe_ratio'),
            'base_ret':   _safe(m_base, 'return_pct'),
            'best_params': best_params,
        }
        rows.append(r)

        # Formata linha
        p = best_params
        combo_str = (f"partial={str(p['use_partial_exit'])[0]},"
                     f"frac={p['partial_exit_fraction']:.1f},"
                     f"cd={p['cooldown_bars']},"
                     f"tf={str(p.get('use_time_filter', False))[0]}")
        print(f"  {k:>4d}  {len(train):>5d}  {len(test):>5d}  "
              f"{best_sr:>+9.3f}  {r['oos_pf']:>6.3f}  "
              f"{r['oos_sr']:>+7.3f}  "
              f"{r['oos_ret']:>+8.2%}  "
              f"{r['oos_dd']:>5.2f}%%  "
              f"{r['oos_trades']:>6d}  "
              f"{r['base_pf']:>7.3f}  "
              f"{combo_str:<42}")

    # ── Agregados ──────────────────────────────────────────────────────────────
    def agg(key: str) -> tuple[float, float]:
        vals = [r[key] for r in rows]
        if not vals:
            return 0.0, 0.0
        mu = statistics.mean(vals)
        sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        return mu, sd

    summary: dict[str, Any] = {}
    for k in ['oos_pf', 'oos_sr', 'oos_ret', 'oos_dd', 'oos_trades',
               'base_pf', 'base_sr', 'base_ret']:
        mu, sd = agg(k)
        summary[f'{k}_mean'] = mu
        summary[f'{k}_std']  = sd

    # Estabilidade de parametros
    pcounts: dict = {}
    for r in rows:
        p = r['best_params']
        key = (p['use_partial_exit'], p['partial_exit_fraction'],
                p['cooldown_bars'], p.get('use_time_filter', False))
        pcounts[key] = pcounts.get(key, 0) + 1
    summary['param_stability'] = pcounts
    summary['n_folds_valid']   = len(rows)

    return {'rows': rows, 'summary': summary, 'label': label}


# ─────────────────────────────────────────────────────────────────────────────
# Impressao de resultados
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(res: dict) -> None:
    s   = res['summary']
    nf  = s['n_folds_valid']
    lbl = res['label']

    print(f"\n  Agregado OOS ({lbl}, {nf} folds validos):")
    print(f"  {'Metrica':<20} {'Sprint-1':>12}  {'+/-':>7}  "
          f"{'baseline':>10}  {'delta':>10}  {'interpret.'}")
    print("  " + "-" * 80)

    def row(name: str, ok: str, ob: str, fmt: str, reverse=False) -> None:
        new_m = s[f'{ok}_mean']; new_s = s[f'{ok}_std']
        bas_m = s[f'{ob}_mean']
        delta = new_m - bas_m
        sign  = "+" if (delta > 0) != reverse else "-"
        marker = "[OK]" if sign == "+" else "[--]"
        print(f"  {name:<20} {format(new_m, fmt):>12}  "
              f"+-{abs(new_s):.3f}  "
              f"{format(bas_m, fmt):>10}  "
              f"{format(delta, fmt):>10}  "
              f"{marker}")

    row("Profit Factor",  "oos_pf",  "base_pf",  ".3f")
    row("Sharpe Ratio",   "oos_sr",  "base_sr",  "+.3f")
    row("Retorno (%)",    "oos_ret", "base_ret", "+.2%")
    row("Max Drawdown",   "oos_dd",  "oos_dd",   ".2f",  reverse=True)
    print(f"  {'Trades/fold':<20} {s['oos_trades_mean']:>12.1f}  "
          f"(minimo 3 para grid search)")

    print(f"\n  Estabilidade de parametros:")
    sorted_p = sorted(s['param_stability'].items(), key=lambda x: -x[1])
    for (pe, frac, cd, tf), cnt in sorted_p[:4]:
        bar = "#" * cnt + "." * (nf - cnt)
        print(f"    partial={pe},frac={frac:.1f},cd={cd},tf={tf} "
              f"-> {cnt}/{nf} folds  [{bar}]")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("  WALK-FORWARD VALIDATION COM DADOS REAIS — Sprint-1")
    print("  Fonte: Yahoo Finance v8 API (fallback sintetico se indisponivel)")
    print("=" * 80)

    baseline = {'use_partial_exit': False, 'partial_exit_fraction': 0.5,
                'cooldown_bars': 0, 'use_time_filter': False}

    # ── Parte 1: Diario 2 anos ───────────────────────────────────────────────
    print("\n  [1/3] Baixando dados diarios (2023-2024)...")
    df_bvsp_d, src1 = download('^BVSP',    '2023-01-01', '2024-12-31', '1d')
    df_usd_d,  src2 = download('USDBRL=X', '2023-01-01', '2024-12-31', '1d')
    print(f"  Fonte: ^BVSP={src1} ({len(df_bvsp_d)} barras), "
          f"USDBRL=X={src2} ({len(df_usd_d)} barras)")

    grid_d = build_daily_grid()
    res1 = walk_forward(df_bvsp_d, '^BVSP', 'Mini Indice diario',
                         n_folds=5, train_pct=0.70,
                         grid=grid_d, baseline_params=baseline)
    print_summary(res1)

    res2 = walk_forward(df_usd_d, 'USDBRL=X', 'Mini Dolar diario',
                         n_folds=5, train_pct=0.70,
                         grid=grid_d, baseline_params=baseline)
    print_summary(res2)

    # ── Parte 2: Intraday 1h para Mini Dolar ────────────────────────────────
    print("\n  [2/3] Baixando dados 1h Mini Dolar (90 dias)...")
    df_usd_h, src3 = download('USDBRL=X', '2024-07-01', '2024-12-31', '1h')
    print(f"  Fonte: USDBRL=X 1h={src3} ({len(df_usd_h)} barras)")

    if len(df_usd_h) >= 200:
        grid_h = build_intraday_grid()
        res3 = walk_forward(df_usd_h, 'USDBRL=X', 'Mini Dolar 1h (Passo 4)',
                             n_folds=4, train_pct=0.70,
                             grid=grid_h, baseline_params=baseline)
        print_summary(res3)
    else:
        print("  [AVISO] Dados 1h insuficientes para WF — pulando Passo 4.")

    # ── Sumario final ────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  SUMARIO FINAL")
    print("=" * 80)
    print(f"  {'Ativo':<28} {'OOS PF':>8}  {'OOS SR':>8}  {'base PF':>8}  "
          f"{'delta PF':>9}  {'#folds':>7}")
    print("  " + "-" * 80)
    for res in [res1, res2]:
        s = res['summary']
        dpf = s['oos_pf_mean'] - s['base_pf_mean']
        print(f"  {res['label']:<28} {s['oos_pf_mean']:>8.3f}  "
              f"{s['oos_sr_mean']:>+8.3f}  "
              f"{s['base_pf_mean']:>8.3f}  "
              f"{dpf:>+9.3f}  "
              f"{s['n_folds_valid']:>7d}")
    print("=" * 80)


if __name__ == '__main__':
    main()
