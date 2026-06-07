# walkforward_honest.py — Sprint 21: walk-forward com re-otimização honesta
"""Walk-forward *honesto*: re-otimiza os hiperparâmetros DENTRO de cada janela IS e
aplica esses params — específicos daquela janela — na janela OOS seguinte. A degradação
IS→OOS observada é a estimativa não-enviesada do overfitting de seleção de parâmetros.

Contraste com o walk-forward "antigo" (params fixos selecionados uma vez no histórico
inteiro): ver ``scripts/compare_walkforward_methods.py`` (E5).

Natureza: o núcleo (``generate_folds``, ``optimize_window``, ``walk_forward_with_reopt``,
``compute_degradation``, ``param_stability_score``) é **biblioteca** — determinístico e
testável via um *seam* ``evaluator`` (default = caminho real). A camada de execução real
(download + ``run_ticker``/``main``) baixa dados e fica em ``# pragma: no cover``.

Reuso (DRY, como S19/S20):
    - ``optimizer._eval_combo`` — avalia (params, janela) in-memory (CombinedStrategy →
      Backtester). NÃO reimplementa o loop de avaliação.
    - ``Backtester.deflated_sharpe_ratio`` — DSR (Bailey & López de Prado 2014) para a
      seleção deflada (``metric_to_optimize='sharpe_dsr'``). NÃO reimplementa o DSR.

Escopo do "full system" (continuidade S19/S20): base ``SPRINT13_PARAMS`` SEM meta-labeler
nem Fibonacci. O param_space otimiza 6 knobs de regime+saída sobre essa base.
"""
from __future__ import annotations

import itertools
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtester import Backtester

logger = logging.getLogger(__name__)

ANNUALIZATION = 252
IS_WINDOW_BARS = 252 * 2        # 2 anos IS (decisão CP1)
OOS_WINDOW_BARS = 252           # 1 ano OOS
EMBARGO_BARS = 20               # gap IS→OOS (anti-leakage)
N_TRIALS_OPTUNA = 100
SEED = 42

# param_space proposto (CP1, aprovado): 6 knobs regime+saída, discretos.
DEFAULT_PARAM_SPACE: dict[str, list] = {
    "adx_threshold":            [20.0, 25.0, 30.0],   # regime: força da tendência
    "hurst_threshold":          [0.50, 0.55, 0.60],   # regime: persistência
    "macro_direction_ret_min":  [0.05, 0.08, 0.12],   # regime: gatilho macro-lock
    "atr_stop_multiplier":      [1.0, 1.5, 2.0],       # saída: largura do stop
    "atr_target_multiplier":    [2.0, 3.0, 4.0],       # saída: alvo
    "chandelier_atr_mult":      [2.0, 3.0, 4.0],       # saída: trailing pós-breakeven
}

# Limiares de interpretação da degradação (spec §3/E2).
_DEG_ROBUST = 20.0
_DEG_MODERATE = 50.0
_DEG_SEVERE = 80.0


# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class WalkForwardFold:
    fold_id: int
    is_start: pd.Timestamp
    is_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp
    best_params: dict
    is_metrics: dict
    oos_metrics: dict
    top_k_params: list[dict] = field(default_factory=list)  # p/ Jaccard (E3)


@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold]
    is_sharpe_mean: float
    oos_sharpe_mean: float
    is_pf_mean: float
    oos_pf_mean: float
    degradation_pct: float
    param_stability_score: float

    def to_dataframe(self) -> pd.DataFrame:
        """Uma linha por fold (datas, sharpe/PF IS e OOS, best_params)."""
        rows = []
        for f in self.folds:
            rows.append({
                "fold_id": f.fold_id,
                "is_start": str(f.is_start.date()), "is_end": str(f.is_end.date()),
                "oos_start": str(f.oos_start.date()), "oos_end": str(f.oos_end.date()),
                "is_sharpe": round(_g(f.is_metrics, "sharpe_ratio"), 6),
                "oos_sharpe": round(_g(f.oos_metrics, "sharpe_ratio"), 6),
                "is_pf": round(_g(f.is_metrics, "profit_factor"), 6),
                "oos_pf": round(_g(f.oos_metrics, "profit_factor"), 6),
                "oos_return_pct": round(_g(f.oos_metrics, "return_pct") * 100.0, 4),
                "oos_trades": int(f.oos_metrics.get("trade_count", 0) or 0),
                "best_params": f.best_params,
            })
        return pd.DataFrame(rows)

    def to_dict(self) -> dict:
        """Serializável p/ JSON (timestamps → str)."""
        return {
            "is_sharpe_mean": round(self.is_sharpe_mean, 6),
            "oos_sharpe_mean": round(self.oos_sharpe_mean, 6),
            "is_pf_mean": round(self.is_pf_mean, 6),
            "oos_pf_mean": round(self.oos_pf_mean, 6),
            "degradation_pct": round(self.degradation_pct, 4),
            "param_stability_score": round(self.param_stability_score, 6),
            "n_folds": len(self.folds),
            "folds": [
                {
                    "fold_id": f.fold_id,
                    "is_start": str(f.is_start.date()), "is_end": str(f.is_end.date()),
                    "oos_start": str(f.oos_start.date()), "oos_end": str(f.oos_end.date()),
                    "best_params": f.best_params,
                    "is_metrics": _slim(f.is_metrics),
                    "oos_metrics": _slim(f.oos_metrics),
                    "top_k_params": f.top_k_params,
                }
                for f in self.folds
            ],
        }


def _g(m: dict, key: str) -> float:
    """Float seguro de um dict de métricas (None/inf/nan → nan, exceto valores finitos)."""
    v = m.get(key, float("nan"))
    try:
        v = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return v


def _slim(m: dict) -> dict:
    """Subconjunto serializável das métricas para o JSON do fold."""
    keys = ("sharpe_ratio", "profit_factor", "return_pct", "trade_count",
            "max_drawdown", "win_rate", "n_return_obs")
    out = {}
    for k in keys:
        v = m.get(k)
        if isinstance(v, (int, float)):
            out[k] = (None if (isinstance(v, float) and not np.isfinite(v)) else
                      (int(v) if k == "trade_count" else round(float(v), 6)))
        else:
            out[k] = v
    return out


# ──────────────────────────────────────────────────────────────────────────────
# E2 — degradação
# ──────────────────────────────────────────────────────────────────────────────

def _interpret(is_metric: float, oos_metric: float) -> tuple[float, str]:
    """Retorna (drop_pct, interpretação). drop_pct = % do IS perdido no OOS (positivo = pior).

    Para ``is_metric <= 0`` a razão relativa é não-interpretável (não há performance
    positiva a degradar): retorna drop=nan e rótulo de caveat.
    """
    if not np.isfinite(is_metric) or not np.isfinite(oos_metric):
        return float("nan"), "indeterminado"
    if is_metric <= 0:
        return float("nan"), "is_nao_positivo"
    drop = (is_metric - oos_metric) / is_metric * 100.0
    if drop < _DEG_ROBUST:
        return drop, "robusto"
    if drop < _DEG_MODERATE:
        return drop, "moderado overfitting"
    if drop < _DEG_SEVERE:
        return drop, "severo overfitting"
    return drop, "estrategia essencialmente artefato de fitting"


def compute_degradation(is_metric: float, oos_metric: float,
                        metric_type: str = "sharpe") -> dict:
    """Degradação IS→OOS interpretável.

    Returns
    -------
    dict
        absolute_degradation : oos - is  (negativo = pior)
        relative_degradation_pct : (oos - is)/is*100  (fórmula da spec; sinal preservado)
        is_significant : bool — drop > 20% (overfitting não-desprezível)
        interpretation : str — robusto / moderado / severo / artefato / caveats
    """
    is_m = float(is_metric)
    oos_m = float(oos_metric)
    abs_deg = oos_m - is_m
    rel = (oos_m - is_m) / is_m * 100.0 if (is_m != 0 and np.isfinite(is_m)) else float("nan")
    drop, interp = _interpret(is_m, oos_m)
    is_significant = bool(np.isfinite(drop) and drop > _DEG_ROBUST)
    return {
        "absolute_degradation": abs_deg,
        "relative_degradation_pct": rel,
        "is_significant": is_significant,
        "interpretation": interp,
        "metric_type": metric_type,
    }


# ──────────────────────────────────────────────────────────────────────────────
# E3 — estabilidade de parâmetros (Jaccard top-K)
# ──────────────────────────────────────────────────────────────────────────────

def _param_key(params: dict) -> frozenset:
    """Identidade hashable de um conjunto de parâmetros (para interseção/união)."""
    return frozenset((k, params[k]) for k in sorted(params))


def param_stability_score(folds: list[WalkForwardFold], top_k: int = 3) -> float:
    """Média da Jaccard similarity entre os top-K param sets de folds consecutivos.

    1.0 = top-K idêntico entre folds (params estáveis = robusto);
    0.0 = top-K disjunto (params variam = overfitting).
    Menos de 2 folds → 1.0 (sem par a comparar; trivialmente estável).
    """
    if len(folds) < 2:
        return 1.0
    scores: list[float] = []
    for a, b in itertools.pairwise(folds):
        set_a = {_param_key(p) for p in a.top_k_params[:top_k]}
        set_b = {_param_key(p) for p in b.top_k_params[:top_k]}
        if not set_a and not set_b:
            scores.append(1.0)
            continue
        union = len(set_a | set_b)
        inter = len(set_a & set_b)
        scores.append(inter / union if union else 0.0)
    return float(np.mean(scores)) if scores else 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Geração de folds
# ──────────────────────────────────────────────────────────────────────────────

def generate_folds(
    n_bars: int,
    n_folds: int,
    is_window_bars: int = IS_WINDOW_BARS,
    oos_window_bars: int = OOS_WINDOW_BARS,
    embargo_bars: int = EMBARGO_BARS,
    anchored: bool = True,
) -> list[tuple[int, int, int, int]]:
    """Posições inteiras (is_start, is_end, oos_start, oos_end) por fold.

    anchored : is_start=0 fixo; IS expande (is_end = is_window + k·oos_window).
    sliding  : IS desliza (is_start = k·oos_window; is_end = is_start + is_window).
    Sempre há ``embargo_bars`` de gap entre is_end e oos_start (anti-leakage).

    ValueError se ``n_bars`` não comporta os ``n_folds`` solicitados.
    """
    if n_folds < 1:
        raise ValueError(f"n_folds deve ser >= 1, recebido {n_folds}")
    folds: list[tuple[int, int, int, int]] = []
    for k in range(n_folds):
        if anchored:
            is_start = 0
            is_end = is_window_bars + k * oos_window_bars
        else:
            is_start = k * oos_window_bars
            is_end = is_start + is_window_bars
        oos_start = is_end + embargo_bars
        oos_end = oos_start + oos_window_bars
        if oos_end > n_bars:
            break
        folds.append((is_start, is_end, oos_start, oos_end))
    if len(folds) < n_folds:
        raise ValueError(
            f"dados insuficientes: {n_bars} barras geram {len(folds)} folds < "
            f"n_folds={n_folds} (IS={is_window_bars}, OOS={oos_window_bars}, "
            f"embargo={embargo_bars}, anchored={anchored}).")
    return folds


# ──────────────────────────────────────────────────────────────────────────────
# Avaliação (seam) + seleção
# ──────────────────────────────────────────────────────────────────────────────

def _default_evaluator(
    data: pd.DataFrame, params: dict, ticker: str,
    base_params: dict | None, capital: float = 100_000.0,
) -> dict | None:
    """Caminho real: reusa ``optimizer._eval_combo`` (CombinedStrategy → Backtester).

    Mescla ``base_params`` (SPRINT13) com os ``params`` do param_space (estes prevalecem).
    """
    from optimizer import _eval_combo  # lazy: evita custo no import do módulo
    full = dict(base_params or {})
    full.update(params)
    return _eval_combo(ticker, ticker, full, data, capital)


def _selection_metric(m: dict, metric_to_optimize: str, n_trials: int) -> float:
    """Valor a maximizar na seleção. 'sharpe_dsr' → DSR deflado; 'sharpe' → Sharpe cru."""
    if metric_to_optimize == "sharpe_dsr":
        return Backtester.deflated_sharpe_ratio(
            sharpe_obs=float(m.get("sharpe_per_period", 0.0) or 0.0),
            n_obs=int(m.get("n_return_obs", 0) or 0),
            n_trials=max(int(n_trials), 1),
            skew=float(m.get("return_skew", 0.0) or 0.0),
            kurt=float(m.get("return_kurt", 3.0) or 3.0),
        )
    if metric_to_optimize == "sharpe":
        return _g(m, "sharpe_ratio")
    return _g(m, metric_to_optimize)


def _passes_min_trades(m: dict, min_trades: int) -> bool:
    """True se o combo tem trades suficientes (ou se a métrica não reporta trades — mocks)."""
    if "trade_count" not in m:
        return True
    return int(m.get("trade_count", 0) or 0) >= min_trades


def optimize_window(
    data: pd.DataFrame,
    param_space: dict[str, list],
    ticker: str = "^BVSP",
    base_params: dict | None = None,
    optimizer: str = "optuna",
    n_trials_optuna: int = N_TRIALS_OPTUNA,
    metric_to_optimize: str = "sharpe_dsr",
    seed: int = SEED,
    min_trades: int = 3,
    top_k: int = 3,
    capital: float = 100_000.0,
    evaluator: Callable | None = None,
) -> tuple[dict, dict, list[dict]]:
    """Otimiza UMA janela (in-memory). Returns (best_params, best_metrics, top_k_params).

    ``optimizer='grid'`` varre ``itertools.product`` do param_space; ``'optuna'`` usa
    ``suggest_categorical`` sobre as mesmas listas (TPESampler(seed)). Seleção por
    ``metric_to_optimize`` (default DSR deflado, ``n_trials`` = nº de configs avaliadas).
    Memo por (params, janela) evita reavaliar repetições (cache).
    """
    evaluator = evaluator or _default_evaluator
    memo: dict = {}
    win_id = (data.index[0], data.index[-1]) if len(data) else (None, None)

    def _cached(cand: dict) -> dict | None:
        key = (_param_key(cand), win_id)
        if key not in memo:
            memo[key] = evaluator(data, cand, ticker, base_params, capital)
        return memo[key]

    if optimizer == "grid":
        keys = list(param_space)
        combos = [dict(zip(keys, vals, strict=True))
                  for vals in itertools.product(*[param_space[k] for k in keys])]
        n_trials = len(combos)
        scored: list[tuple[float, dict, dict]] = []
        for cand in combos:
            m = _cached(cand)
            if m is None or not _passes_min_trades(m, min_trades):
                continue
            scored.append((_selection_metric(m, metric_to_optimize, n_trials), cand, m))
    elif optimizer == "optuna":
        scored = _optuna_search(
            param_space, _cached, n_trials_optuna, metric_to_optimize,
            seed, min_trades)
    else:
        raise ValueError(f"optimizer desconhecido: {optimizer!r} (use 'grid' ou 'optuna')")

    if not scored:
        raise ValueError("nenhum combo válido na janela (todos None ou < min_trades).")

    # Dedup por param_key mantendo o melhor; ordena desc por métrica de seleção.
    best_by_key: dict = {}
    for val, cand, m in scored:
        k = _param_key(cand)
        if k not in best_by_key or val > best_by_key[k][0]:
            best_by_key[k] = (val, cand, m)
    ranked = sorted(best_by_key.values(),
                    key=lambda t: (t[0] if np.isfinite(t[0]) else float("-inf")),
                    reverse=True)
    _best_val, best_params, best_metrics = ranked[0]
    top_k_params = [cand for _, cand, _ in ranked[:top_k]]
    return best_params, best_metrics, top_k_params


def _optuna_search(
    param_space: dict[str, list], cached_eval: Callable, n_trials: int,
    metric_to_optimize: str, seed: int, min_trades: int,
) -> list[tuple[float, dict, dict]]:
    """Busca TPE sobre param_space discreto (suggest_categorical). Determinística (seed)."""
    import optuna
    from optuna.samplers import TPESampler
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    records: list[tuple[float, dict, dict]] = []

    def objective(trial) -> float:
        cand = {k: trial.suggest_categorical(k, list(param_space[k])) for k in param_space}
        m = cached_eval(cand)
        if m is None or not _passes_min_trades(m, min_trades):
            return float("-1e9")
        val = _selection_metric(m, metric_to_optimize, n_trials)
        if not np.isfinite(val):
            return float("-1e9")
        records.append((val, cand, m))
        return val

    study = optuna.create_study(direction="maximize", sampler=TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return records


# ──────────────────────────────────────────────────────────────────────────────
# E1 — walk-forward com re-otimização
# ──────────────────────────────────────────────────────────────────────────────

def _mean_finite(values: list[float]) -> float:
    arr = [v for v in values if isinstance(v, (int, float)) and np.isfinite(v)]
    return float(np.mean(arr)) if arr else float("nan")


def walk_forward_with_reopt(
    data: pd.DataFrame,
    param_space: dict[str, list],
    ticker: str = "^BVSP",
    n_folds: int = 5,
    is_window_bars: int = IS_WINDOW_BARS,
    oos_window_bars: int = OOS_WINDOW_BARS,
    embargo_bars: int = EMBARGO_BARS,
    anchored: bool = True,
    optimizer: str = "optuna",
    n_trials_optuna: int = N_TRIALS_OPTUNA,
    metric_to_optimize: str = "sharpe_dsr",
    base_params: dict | None = None,
    seed: int = SEED,
    top_k: int = 3,
    capital: float = 100_000.0,
    evaluator: Callable | None = None,
    verbose: bool = False,
) -> WalkForwardResult:
    """Walk-forward anchored com re-otimização em cada janela IS.

    Para cada fold: otimiza no IS (``optimize_window``) → aplica best_params no OOS →
    registra IS/OOS metrics + top-K. ``base_params`` = base SPRINT13 (os knobs do
    param_space prevalecem). Determinístico (TPESampler(seed), sem ``random`` global).
    """
    fold_pos = generate_folds(len(data), n_folds, is_window_bars,
                              oos_window_bars, embargo_bars, anchored)
    evaluator = evaluator or _default_evaluator
    folds: list[WalkForwardFold] = []

    for fid, (is_s, is_e, oos_s, oos_e) in enumerate(fold_pos):
        is_df = data.iloc[is_s:is_e]
        oos_df = data.iloc[oos_s:oos_e]

        best_params, is_metrics, top_k_params = optimize_window(
            is_df, param_space, ticker=ticker, base_params=base_params,
            optimizer=optimizer, n_trials_optuna=n_trials_optuna,
            metric_to_optimize=metric_to_optimize, seed=seed, top_k=top_k,
            capital=capital, evaluator=evaluator)

        oos_metrics = evaluator(oos_df, best_params, ticker, base_params, capital) or {}

        folds.append(WalkForwardFold(
            fold_id=fid,
            is_start=data.index[is_s], is_end=data.index[is_e - 1],
            oos_start=data.index[oos_s], oos_end=data.index[oos_e - 1],
            best_params=best_params, is_metrics=is_metrics, oos_metrics=oos_metrics,
            top_k_params=top_k_params))

        if verbose:   # pragma: no cover — logging de execução
            deg = compute_degradation(_g(is_metrics, "sharpe_ratio"),
                                      _g(oos_metrics, "sharpe_ratio"))
            print(f"  fold {fid}: IS Sharpe={_g(is_metrics,'sharpe_ratio'):+.3f} | "
                  f"OOS Sharpe={_g(oos_metrics,'sharpe_ratio'):+.3f} | "
                  f"{deg['interpretation']} | best={best_params}")

    is_sharpe_mean = _mean_finite([_g(f.is_metrics, "sharpe_ratio") for f in folds])
    oos_sharpe_mean = _mean_finite([_g(f.oos_metrics, "sharpe_ratio") for f in folds])
    is_pf_mean = _mean_finite([_g(f.is_metrics, "profit_factor") for f in folds])
    oos_pf_mean = _mean_finite([_g(f.oos_metrics, "profit_factor") for f in folds])
    deg = compute_degradation(is_sharpe_mean, oos_sharpe_mean)

    return WalkForwardResult(
        folds=folds,
        is_sharpe_mean=is_sharpe_mean, oos_sharpe_mean=oos_sharpe_mean,
        is_pf_mean=is_pf_mean, oos_pf_mean=oos_pf_mean,
        degradation_pct=(deg["relative_degradation_pct"]
                         if np.isfinite(deg["relative_degradation_pct"]) else float("nan")),
        param_stability_score=param_stability_score(folds, top_k=top_k))


# ──────────────────────────────────────────────────────────────────────────────
# Base SPRINT13 (escopo do full system — sem meta-labeler/Fibonacci)
# ──────────────────────────────────────────────────────────────────────────────

def sprint13_base_params() -> dict:   # pragma: no cover — usado só no caminho de execução real
    """Base do 'full system' (DRY com bear_market_validation; sem meta-labeler/Fibonacci)."""
    try:
        from scripts.bear_market_validation import SPRINT13_PARAMS
    except ImportError:
        from bear_market_validation import SPRINT13_PARAMS
    return dict(SPRINT13_PARAMS)


# ──────────────────────────────────────────────────────────────────────────────
# CLI / execução real (E6, CP4) — rede; fora da cobertura.
# ──────────────────────────────────────────────────────────────────────────────

def run_ticker(   # pragma: no cover — execução real (rede); validada no CP4
    ticker: str, n_folds: int = 5, history_start: str = "2010-01-01",
    history_end: str | None = None, optimizer: str = "optuna",
    n_trials_optuna: int = N_TRIALS_OPTUNA,
) -> WalkForwardResult:
    """Baixa dados reais (gate S18: aborta se sintético) e roda o WF honesto."""
    from scripts.fetch_real_data import download
    if history_end is None:
        history_end = pd.Timestamp.today().strftime("%Y-%m-%d")
    df, source = download(ticker, history_start, history_end, interval="1d")
    if source == "synthetic":
        raise RuntimeError(
            f"{ticker}: download retornou dados SINTÉTICOS — abortado (disciplina S18).")
    return walk_forward_with_reopt(
        df, DEFAULT_PARAM_SPACE, ticker=ticker, n_folds=n_folds,
        optimizer=optimizer, n_trials_optuna=n_trials_optuna,
        base_params=sprint13_base_params(), verbose=True)


def main(argv: list[str] | None = None) -> int:   # pragma: no cover — CLI/rede
    import argparse
    parser = argparse.ArgumentParser(
        description="Sprint 21 — walk-forward honesto (re-otimização por fold).")
    parser.add_argument("--ticker", default="^BVSP")
    parser.add_argument("--n_folds", type=int, default=5)
    parser.add_argument("--optimizer", default="optuna", choices=["optuna", "grid"])
    parser.add_argument("--n_trials", type=int, default=N_TRIALS_OPTUNA)
    args = parser.parse_args(argv)
    print(f"Walk-forward honesto — {args.ticker} ({args.n_folds} folds, {args.optimizer})")
    try:
        res = run_ticker(args.ticker, n_folds=args.n_folds,
                         optimizer=args.optimizer, n_trials_optuna=args.n_trials)
    except RuntimeError as e:
        print(f"  [ABORT] {e}")
        return 1
    print(f"\n  IS Sharpe mean={res.is_sharpe_mean:+.3f} | OOS Sharpe mean={res.oos_sharpe_mean:+.3f}")
    print(f"  Degradação={res.degradation_pct:+.1f}% | stability={res.param_stability_score:.3f}")
    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
