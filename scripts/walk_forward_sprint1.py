"""Walk-forward validation do Sprint-1 completo.

Metodologia:
    1. Gera ~2 anos de dados diarios sinteticos (502 barras, seed fixo).
    2. Divide em 5 folds nao sobrepostos.
    3. Em cada fold: 70%% treino / 30%% teste.
    4. Treino: grid search sobre os parametros do Sprint-1.
       Metrica de ranqueamento: sharpe_ratio (com min_trades >= 3).
    5. Teste: aplica MELHORES parametros OOS (fora-da-amostra).
    6. Agrega: media/std das metricas out-of-sample; estabilidade dos params.

Grid explorado (8 combos):
    use_partial_exit       : [False, True]
    partial_exit_fraction  : [0.3, 0.5, 0.7]  (so com partial)
    cooldown_bars          : [0, 4]

Baseline: todos OFF (cooldown=0, sem partial) para comparacao honesta.
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


# ─────────────────────────────────────────────────────────────────────────────
# Dados sinteticos
# ─────────────────────────────────────────────────────────────────────────────

def make_synthetic_daily(n: int, daily_vol: float, start: float,
                          seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    log_ret = rng.normal(0, daily_vol, size=n)
    close = start * np.exp(np.cumsum(log_ret))
    intra = np.abs(rng.normal(0, daily_vol * 0.6, size=n))
    high = close * (1 + intra)
    low  = close * (1 - intra)
    open_ = np.concatenate(([start], close[:-1]))
    idx = pd.date_range('2023-01-02', periods=n, freq='B')
    return pd.DataFrame({
        'Open':   open_,
        'High':   np.maximum(high, np.maximum(open_, close)),
        'Low':    np.minimum(low,  np.minimum(open_, close)),
        'Close':  close,
        'Volume': rng.integers(1_000_000, 5_000_000, size=n).astype(float),
    }, index=idx)


# ─────────────────────────────────────────────────────────────────────────────
# Grid e execucao
# ─────────────────────────────────────────────────────────────────────────────

def build_grid() -> list[dict]:
    combos: list[dict] = []
    # Sem partial
    for cd in [0, 4]:
        combos.append({
            'use_partial_exit': False,
            'partial_exit_fraction': 0.5,   # ignorado
            'cooldown_bars': cd,
        })
    # Com partial
    for frac, cd in itertools.product([0.3, 0.5, 0.7], [0, 4]):
        combos.append({
            'use_partial_exit': True,
            'partial_exit_fraction': frac,
            'cooldown_bars': cd,
        })
    return combos


def run_bt(data: pd.DataFrame, ticker: str, params: dict) -> dict:
    strat = CombinedStrategy(ticker, name="wf")
    strat.set_data(data.copy())
    strat.params.update({
        'use_partial_exit':       params['use_partial_exit'],
        'partial_exit_r':         1.0,
        'partial_exit_fraction':  params['partial_exit_fraction'],
        'breakeven_offset_atr':   0.1,
    })
    bt = Backtester(strat, initial_capital=100_000.0,
                    cooldown_bars=params['cooldown_bars'])
    return bt.run()


def _safe(m: dict, key: str, default: float = 0.0) -> float:
    v = m.get(key, default)
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return default
    return float(v)


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward(data: pd.DataFrame, ticker: str, n_folds: int,
                  train_pct: float, grid: list[dict],
                  baseline_params: dict, asset_label: str) -> dict:
    n = len(data)
    fold_size = n // n_folds
    rows: list[dict[str, Any]] = []

    print(f"\n  === {asset_label} — {n} barras, {n_folds} folds "
          f"({int(train_pct*100)}%%/{100 - int(train_pct*100)}%%) ===")
    print(f"  {'fold':>4} {'train':>6} {'test':>5} "
          f"{'IS Sharpe':>10} {'OOS PF':>7} {'OOS Sharpe':>11} "
          f"{'OOS Ret':>8} {'OOS DD':>7} {'trades':>7} "
          f"{'best params':<50}")
    print("  " + "-" * 120)

    for k in range(n_folds):
        start = k * fold_size
        end   = start + fold_size if k < n_folds - 1 else n
        fold  = data.iloc[start:end]
        if len(fold) < 60:
            continue
        split = int(len(fold) * train_pct)
        train = fold.iloc[:split]
        test  = fold.iloc[split:]

        # Grid search in-sample
        best_sr = -float('inf')
        best_params = None
        for params in grid:
            m = run_bt(train, ticker, params)
            sr = _safe(m, 'sharpe_ratio', -999)
            trades = m.get('trade_count', 0)
            if trades >= 3 and sr > best_sr:
                best_sr = sr
                best_params = params

        if best_params is None:
            # Fallback: pega o primeiro combo que rodou
            best_params = grid[0]
            best_sr = 0.0

        # OOS eval
        m_oos = run_bt(test, ticker, best_params)
        # Baseline OOS (sem Sprint-1) para referencia
        m_base_oos = run_bt(test, ticker, baseline_params)

        rows.append({
            'fold': k,
            'train_size': len(train),
            'test_size': len(test),
            'is_sharpe': best_sr,
            'oos_pf':    _safe(m_oos, 'profit_factor'),
            'oos_sr':    _safe(m_oos, 'sharpe_ratio'),
            'oos_ret':   _safe(m_oos, 'return_pct'),
            'oos_dd':    _safe(m_oos, 'max_drawdown'),
            'oos_trades': int(m_oos.get('trade_count', 0)),
            'base_pf':   _safe(m_base_oos, 'profit_factor'),
            'base_sr':   _safe(m_base_oos, 'sharpe_ratio'),
            'base_ret':  _safe(m_base_oos, 'return_pct'),
            'best_params': best_params,
        })

        p = best_params
        pstr = (f"partial={p['use_partial_exit']},"
                f"frac={p['partial_exit_fraction']:.1f},"
                f"cd={p['cooldown_bars']}")
        print(f"  {k:>4d} {len(train):>6d} {len(test):>5d} "
              f"{best_sr:>+10.3f} {rows[-1]['oos_pf']:>7.3f} "
              f"{rows[-1]['oos_sr']:>+11.3f} "
              f"{rows[-1]['oos_ret']:>+8.2%} "
              f"{rows[-1]['oos_dd']:>6.2f}% "
              f"{rows[-1]['oos_trades']:>7d} "
              f"{pstr:<50}")

    # Aggregate
    def mean_std(key: str) -> tuple[float, float]:
        vals = [r[key] for r in rows]
        if not vals:
            return 0.0, 0.0
        return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)

    summary = {}
    for k in ['oos_pf', 'oos_sr', 'oos_ret', 'oos_dd', 'oos_trades',
              'base_pf', 'base_sr', 'base_ret']:
        mu, sd = mean_std(k)
        summary[f'{k}_mean'] = mu
        summary[f'{k}_std']  = sd

    # Param stability
    param_counts: dict = {}
    for r in rows:
        key = (r['best_params']['use_partial_exit'],
               r['best_params']['partial_exit_fraction'],
               r['best_params']['cooldown_bars'])
        param_counts[key] = param_counts.get(key, 0) + 1
    summary['param_stability'] = param_counts

    return {'rows': rows, 'summary': summary}


def print_summary(asset: str, res: dict) -> None:
    s = res['summary']
    print(f"\n  {asset} — agregado OOS ({len(res['rows'])} folds):")
    print(f"  {'metrica':<18} {'Sprint-1 OOS':>18} {'baseline OOS':>18} {'delta':>12}")
    print(f"  {'-'*18} {'-'*18} {'-'*18} {'-'*12}")
    rows_fmt = [
        ('Profit Factor',  'oos_pf_mean',  'base_pf_mean',  '.3f', False),
        ('Sharpe Ratio',   'oos_sr_mean',  'base_sr_mean',  '+.3f', False),
        ('Retorno (%)',    'oos_ret_mean', 'base_ret_mean', '+.2%', False),
    ]
    for lbl, new_k, base_k, fmt, _ in rows_fmt:
        new = s[new_k]; base = s[base_k]
        delta = new - base
        std_key = new_k.replace('_mean', '_std')
        std = s.get(std_key, 0.0)
        print(f"  {lbl:<18} {format(new, fmt):>13}±{std:.2f}  "
              f"{format(base, fmt):>18}  {format(delta, fmt):>12}")
    print(f"  DD medio (%)       {s['oos_dd_mean']:>17.2f}  "
          f"(nao disponivel no baseline separado)")
    print(f"  Trades/fold medio  {s['oos_trades_mean']:>17.1f}")
    print(f"  Estabilidade (best-params mais frequente):")
    sorted_counts = sorted(res['summary']['param_stability'].items(),
                           key=lambda x: -x[1])
    for (p_on, frac, cd), cnt in sorted_counts[:3]:
        print(f"    partial={p_on}, frac={frac:.1f}, cd={cd} -> {cnt}/{len(res['rows'])} folds")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 80)
    print("  WALK-FORWARD VALIDATION — Sprint-1 completo")
    print("  Dados diarios sinteticos (filtro de horario = no-op em diario)")
    print("=" * 80)

    grid = build_grid()
    print(f"\n  Grid: {len(grid)} combos")
    for g in grid:
        print(f"    {g}")

    baseline = {
        'use_partial_exit': False,
        'partial_exit_fraction': 0.5,
        'cooldown_bars': 0,
    }

    # 2 anos (502 barras uteis), 5 folds de ~100 barras (70 train / 30 test)
    scenarios = [
        ('Mini Indice (^BVSP)', '^BVSP',    0.012, 120_000.0, 42),
        ('Mini Dolar (USDBRL)', 'USDBRL=X', 0.007,    5.20,   17),
    ]

    all_res = {}
    for asset, ticker, vol, start, seed in scenarios:
        data = make_synthetic_daily(n=502, daily_vol=vol, start=start, seed=seed)
        res = walk_forward(data, ticker, n_folds=5, train_pct=0.7,
                            grid=grid, baseline_params=baseline,
                            asset_label=asset)
        all_res[asset] = res
        print_summary(asset, res)

    print("\n" + "=" * 80)
    print("  Interpretacao:")
    print("  - OOS >> baseline => otimizacao generalizou.")
    print("  - OOS ~= baseline => overfitting possivel ou Sprint-1 nao ajuda esse ativo.")
    print("  - Estabilidade alta (params repetidos) => mesma configuracao venceu")
    print("    em multiplos folds, indica robustez.")
    print("=" * 80)


if __name__ == '__main__':
    main()
