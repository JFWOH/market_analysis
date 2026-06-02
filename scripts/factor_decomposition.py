# scripts/factor_decomposition.py — Sprint 20: decomposição fatorial do alpha
"""Quanto do retorno do sistema é alpha genuíno e quanto é exposição a fatores
replicáveis? Três regressões OLS sucessivas (erros-padrão Newey-West/HAC):

    Modelo 1 — CAPM local:        R_sys = alpha + beta_mkt · R_mkt + eps
    Modelo 2 — + Momentum 12-1:   R_sys = alpha + beta_mkt · R_mkt + beta_mom · MOM + eps
    Modelo 3 — vs Sistema Mínimo: R_sys = alpha + beta · R_minimal + eps

O Modelo 3 é a pergunta dura: o "Sistema Mínimo" (long se Hurst[i-1]>0.55 AND
ADX[i-1]>25, senão flat) reusa EXATAMENTE as features do sistema completo (via
``TechnicalIndicators.compute_all`` — não reimplementa). Se o alpha do Modelo 3 não
é significativo, a sofisticação adicional (ensemble, macro-lock, partial, chandelier)
não adiciona retorno comprovado sobre o filtro de regime puro.

Natureza: núcleo (``fit_*`` e ``build_minimal_system_returns``) é **biblioteca** — funções
puras, determinísticas, testáveis e SEM rede. A CLI de execução (Sprint 20 CP3) baixa
dados reais e fica em ``# pragma: no cover``.

Escopo do "sistema completo" (decisão do Sprint 20, continuidade com o S19): usa
``SPRINT13_PARAMS`` SEM meta-labeler nem Fibonacci. Logo o Modelo 3 mede
ensemble+macro-lock+partial+chandelier vs. regime puro. (Pergunta aberta para o Marco:
meta-labeler+Fibonacci, quando ativados, adicionam alpha?)
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

from indicators import TechnicalIndicators

ANNUALIZATION = 252          # barras/ano (dados diários)
MIN_OBS = 30                 # mínimo para regredir (abaixo disso, ValueError)
ALPHA_SIGNIF = 0.05          # limiar de significância do alpha
DEFAULT_HURST_MIN = 0.55     # macro_direction_hurst_min (spec §3/E1: Hurst>0.55)
DEFAULT_ADX_MIN = 25.0       # adx_threshold (spec: ADX>25)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de regressão
# ──────────────────────────────────────────────────────────────────────────────

def _hac_maxlags(n: int) -> int:
    """Lags de Newey-West: int(4 · (n/100)^(2/9)) (spec §6)."""
    return int(4 * (n / 100) ** (2 / 9))


def _align(**named_series: pd.Series) -> pd.DataFrame:
    """Junta séries por índice (datas) e descarta NaN. Colunas = nomes dos kwargs."""
    df = pd.concat({k: v for k, v in named_series.items()}, axis=1).dropna()
    return df


def _ols_hac(y: pd.Series, X: pd.DataFrame, min_obs: int = MIN_OBS):
    """OLS com cov HAC (Newey-West). X SEM constante (é adicionada aqui).

    Returns (RegressionResults, n_obs, maxlags). ValueError se n_obs < min_obs.
    """
    n = int(len(y))
    if n < min_obs:
        raise ValueError(
            f"n_obs={n} < min_obs={min_obs}: amostra insuficiente para regressão confiável.")
    Xc = sm.add_constant(X, has_constant="add")
    lags = _hac_maxlags(n)
    res = sm.OLS(np.asarray(y, dtype=float), np.asarray(Xc, dtype=float)).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags})
    return res, n, lags


def _base_result(res, n: int, lags: int, alpha_idx: int = 0, beta_idx: int = 1) -> dict:
    """Extrai o bloco comum (alpha, beta, r², p-values) de um resultado OLS.

    As colunas do design são [const, regressor_0, regressor_1, ...]; ``beta_idx`` é o
    índice do regressor principal (o mercado, no M1/M2; o sistema mínimo, no M3).
    """
    params = np.asarray(res.params, dtype=float)
    pvals = np.asarray(res.pvalues, dtype=float)
    alpha_daily = float(params[alpha_idx])
    return {
        "alpha_annualized": round(alpha_daily * ANNUALIZATION * 100.0, 6),
        "beta": round(float(params[beta_idx]), 6),
        "r_squared": round(float(res.rsquared), 6),
        "alpha_pvalue": round(float(pvals[alpha_idx]), 6),
        "beta_pvalue": round(float(pvals[beta_idx]), 6),
        "residual_std": round(float(np.std(res.resid, ddof=1)), 8),
        "n_obs": n,
        "hac_maxlags": lags,
        "significant_alpha": bool(pvals[alpha_idx] < ALPHA_SIGNIF),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Modelo 1 — CAPM local
# ──────────────────────────────────────────────────────────────────────────────

def fit_capm_local(
    system_returns: pd.Series,
    market_returns: pd.Series,
    risk_free_rate: float = 0.0,
) -> dict:
    """R_sys − rf = alpha + beta · (R_mkt − rf) + eps  (HAC errors).

    ``risk_free_rate`` em termos DIÁRIOS (default 0.0 → sem ajuste).

    Returns dict: model, alpha_annualized(%), beta, r_squared, alpha_pvalue,
    beta_pvalue, residual_std, n_obs, hac_maxlags, significant_alpha.
    """
    aligned = _align(sys=system_returns, mkt=market_returns)
    y = aligned["sys"] - risk_free_rate
    X = (aligned[["mkt"]] - risk_free_rate)
    res, n, lags = _ols_hac(y, X)
    out = {"model": "capm_local"}
    out.update(_base_result(res, n, lags, alpha_idx=0, beta_idx=1))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Modelo 2 — CAPM + Momentum 12-1
# ──────────────────────────────────────────────────────────────────────────────

def _momentum_factor(market_prices: pd.Series, lookback: int, skip: int) -> pd.Series:
    """Momentum 12-1: retorno de t-lookback a t-skip = pct_change(lookback-skip).shift(skip)."""
    return market_prices.pct_change(lookback - skip).shift(skip).rename("mom")


def fit_capm_plus_momentum(
    system_returns: pd.Series,
    market_returns: pd.Series,
    market_prices: pd.Series,
    momentum_lookback: int = 252,
    momentum_skip: int = 21,
) -> dict:
    """R_sys = alpha + beta_mkt · R_mkt + beta_mom · MOM + eps  (HAC errors).

    MOM = momentum 12-1 do mercado de referência. Reporta também VIF (mercado e
    momentum) para diagnosticar multicolinearidade.

    Returns: schema do Modelo 1 + beta_momentum, beta_momentum_pvalue,
    vif_market, vif_momentum.
    """
    mom = _momentum_factor(market_prices, momentum_lookback, momentum_skip)
    aligned = _align(sys=system_returns, mkt=market_returns, mom=mom)
    y = aligned["sys"]
    X = aligned[["mkt", "mom"]]
    res, n, lags = _ols_hac(y, X)

    out = {"model": "capm_plus_momentum"}
    out.update(_base_result(res, n, lags, alpha_idx=0, beta_idx=1))  # beta = beta_mkt
    params = np.asarray(res.params, dtype=float)
    pvals = np.asarray(res.pvalues, dtype=float)
    out["beta_momentum"] = round(float(params[2]), 6)
    out["beta_momentum_pvalue"] = round(float(pvals[2]), 6)

    # VIF (design com constante): índices 1=mkt, 2=mom.
    Xc = np.asarray(sm.add_constant(X, has_constant="add"), dtype=float)
    out["vif_market"] = round(float(variance_inflation_factor(Xc, 1)), 4)
    out["vif_momentum"] = round(float(variance_inflation_factor(Xc, 2)), 4)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Modelo 3 — vs Sistema Mínimo (Hurst + ADX)
# ──────────────────────────────────────────────────────────────────────────────

def build_minimal_system_returns(
    market_data: pd.DataFrame,
    hurst_min: float = DEFAULT_HURST_MIN,
    adx_min: float = DEFAULT_ADX_MIN,
    indicator_params: dict | None = None,
) -> tuple[pd.Series, int]:
    """Retornos do "Sistema Mínimo": long(1) se Hurst[i-1]>hurst_min AND ADX[i-1]>adx_min,
    senão flat(0); multiplicado pelo retorno diário do mercado.

    Reusa ``TechnicalIndicators.compute_all`` (mesmas features do sistema completo —
    NÃO reimplementa ADX/Hurst). O ``shift(1)`` garante uso apenas da barra anterior
    (anti-lookahead, CLAUDE.md §2.2).

    Returns (returns_minimal, n_active_bars).
    """
    ind = TechnicalIndicators.compute_all(market_data, indicator_params)
    sig = ((ind["Hurst"].shift(1) > hurst_min) & (ind["ADX"].shift(1) > adx_min)).astype(float)
    mkt_ret = market_data["Close"].pct_change()
    returns_minimal = (sig * mkt_ret).dropna().rename("minimal")
    n_active = int((sig.reindex(returns_minimal.index) > 0).sum())
    return returns_minimal, n_active


def fit_vs_minimal_system(
    system_returns: pd.Series,
    market_data: pd.DataFrame,
    minimal_strategy_params: dict | None = None,
) -> dict:
    """R_sys = alpha + beta · R_minimal + eps  (HAC errors).

    "Sistema Mínimo" = filtro de regime puro (Hurst+ADX). Pergunta: a sofisticação
    do sistema completo adiciona alpha sobre o regime puro?

    ``minimal_strategy_params`` pode conter ``hurst_min``, ``adx_min`` e
    ``indicator_params``. Returns: schema do Modelo 1 + minimal_total_return,
    minimal_n_active_bars, hurst_min, adx_min.
    """
    p = dict(minimal_strategy_params or {})
    hurst_min = float(p.get("hurst_min", DEFAULT_HURST_MIN))
    adx_min = float(p.get("adx_min", DEFAULT_ADX_MIN))
    indicator_params = p.get("indicator_params")

    returns_minimal, n_active = build_minimal_system_returns(
        market_data, hurst_min, adx_min, indicator_params)

    aligned = _align(sys=system_returns, minimal=returns_minimal)
    y = aligned["sys"]
    X = aligned[["minimal"]]
    res, n, lags = _ols_hac(y, X)

    out = {"model": "vs_minimal_system"}
    out.update(_base_result(res, n, lags, alpha_idx=0, beta_idx=1))
    out["minimal_total_return"] = round(float((1.0 + returns_minimal).prod() - 1.0) * 100.0, 6)
    out["minimal_n_active_bars"] = int(n_active)
    out["hurst_min"] = hurst_min
    out["adx_min"] = adx_min
    return out


# ──────────────────────────────────────────────────────────────────────────────
# E2 — Visualizações (matplotlib Agg). Importadas tarde p/ não exigir display.
# ──────────────────────────────────────────────────────────────────────────────

def plot_regression_scatter(
    x: pd.Series, y: pd.Series, out_path: str, title: str = "",
    xlabel: str = "Retorno do fator", ylabel: str = "Retorno do sistema",
) -> str:
    """Scatter y vs x + reta de regressão OLS + banda de confiança 95% da média."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xv = np.asarray(x, dtype=float)
    yv = np.asarray(y, dtype=float)
    res = sm.OLS(yv, sm.add_constant(xv, has_constant="add")).fit()
    grid = np.linspace(float(xv.min()), float(xv.max()), 100)
    pred = res.get_prediction(sm.add_constant(grid, has_constant="add"))
    ci = pred.conf_int(alpha=0.05)

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(xv, yv, s=10, alpha=0.4, color="#2196F3", label="observações")
    ax.plot(grid, pred.predicted_mean, color="#F44336", lw=2, label="reta OLS")
    ax.fill_between(grid, ci[:, 0], ci[:, 1], color="#F44336", alpha=0.18, label="IC 95%")
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
    ax.set_title(title or "Regressão system vs fator")
    ax.legend(); ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_residuals(fitted: np.ndarray, resid: np.ndarray, out_path: str, title: str = "") -> str:
    """Resíduos vs valores ajustados — diagnóstico de não-linearidade/heterocedasticidade."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(np.asarray(fitted, float), np.asarray(resid, float), s=10, alpha=0.4, color="#2196F3")
    ax.axhline(0.0, color="red", lw=1, alpha=0.7)
    ax.set_xlabel("Valores ajustados"); ax.set_ylabel("Resíduos")
    ax.set_title(title or "Resíduos vs ajustados")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_qq(resid: np.ndarray, out_path: str, title: str = "") -> str:
    """Q-Q plot dos resíduos (normalidade) via scipy.stats.probplot."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy import stats

    fig, ax = plt.subplots(figsize=(8, 6))
    stats.probplot(np.asarray(resid, dtype=float), dist="norm", plot=ax)
    ax.set_title(title or "Q-Q plot dos resíduos")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# CLI (E4) — implementada no Checkpoint 3.
if __name__ == "__main__":   # pragma: no cover
    print("CLI de execução (E4) será implementada no Checkpoint 3 do Sprint 20.")
