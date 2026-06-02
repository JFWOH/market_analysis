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


# ──────────────────────────────────────────────────────────────────────────────
# E4 — Execução real (CLI). Dados reais (gate S18), split IS/OOS 70/30. Importa
# rede/motor tarde para manter o núcleo-biblioteca acima livre de side-effects. Toda
# esta camada é ``# pragma: no cover`` (orquestração/rede), validada pela corrida real
# do CP3 — coerente com ``cost_sensitivity.run_ticker`` (S19).
# ──────────────────────────────────────────────────────────────────────────────

TICKER = "^BVSP"                    # ticker principal do sistema (spec §3/E4)
TICKER_SLUG = "bvsp"
HISTORY_START = "2000-01-01"        # histórico longo (auto-aquecimento dos indicadores)
IS_FRACTION = 0.70                  # split 70/30: IS = primeiros 70% das barras
CONFIG_FILE_LABEL = "sprint_13"     # rótulo nos nomes de PNG (casa com S19)
BASELINE_COMM = 0.001               # 0.1% — comissão (CLAUDE.md §6.6)
BASELINE_SLIP = 0.001               # 0.1% — slippage do baseline

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(_REPO_ROOT, "findings", "sprint_20_data")


def _load_config(config_name: str) -> dict:   # pragma: no cover
    """Carrega o dict de params da config (DRY com bear_market_validation/cost_sensitivity).

    Único registro é ``sprint_13_reference`` → ``SPRINT13_PARAMS``. Registry YAML fica p/ S21+.
    """
    try:
        from scripts.bear_market_validation import SPRINT13_PARAMS
    except ImportError:  # execução direta (sys.path já tem a raiz)
        from bear_market_validation import SPRINT13_PARAMS
    registry = {"sprint_13_reference": SPRINT13_PARAMS}
    if config_name not in registry:
        raise KeyError(
            f"config desconhecida: {config_name!r}. Disponíveis: {list(registry)}")
    return dict(registry[config_name])


def build_system_returns(   # pragma: no cover — roda o motor; validado pela corrida real
    data: pd.DataFrame,
    config: dict,
    initial_capital: float = 100_000.0,
) -> pd.Series:
    """Roda o sistema COMPLETO (Sprint-13) e devolve a série de retornos DIÁRIOS.

    Reusa o padrão canônico de ``bear_market_validation`` (CombinedStrategy → set_data →
    params.update → Backtester). ``system_returns`` = ``pct_change`` da curva de equity
    (R$ 0 de retorno nas barras flat). Custos: comissão/slippage 0.1% (CLAUDE.md §6.6).
    """
    from backtester import Backtester
    from strategy import CombinedStrategy

    strat = CombinedStrategy(TICKER)
    strat.set_data(data.copy())
    strat.params.update(dict(config))
    bt = Backtester(
        strat, initial_capital=initial_capital,
        commission_per_trade=BASELINE_COMM, slippage_pct=BASELINE_SLIP, cooldown_bars=2)
    bt.run()
    eq = pd.Series(bt.equity, index=pd.to_datetime(bt.equity_dates))
    eq = eq[~eq.index.duplicated(keep="first")]
    return eq.pct_change().dropna().rename("system")


def _sharpe_annualized(returns: pd.Series) -> float:   # pragma: no cover
    """Sharpe anualizado simples (rf=0) da série de retornos diários."""
    sd = float(np.std(returns, ddof=1))
    if sd == 0.0 or not np.isfinite(sd):
        return float("nan")
    return float(np.mean(returns) / sd * np.sqrt(ANNUALIZATION))


def _emit_model_viz(   # pragma: no cover — geração de PNGs (gitignored)
    y: pd.Series, X: pd.DataFrame, scatter_col: str,
    out_dir: str, prefix: str, title: str,
) -> None:
    """Scatter (system vs fator primário) + resíduos + Q-Q de UM modelo (3 PNGs)."""
    Xc = sm.add_constant(X, has_constant="add")
    res = sm.OLS(np.asarray(y, float), np.asarray(Xc, float)).fit()
    plot_regression_scatter(
        X[scatter_col], y, os.path.join(out_dir, f"{prefix}.png"),
        title=title, xlabel=f"Retorno do fator ({scatter_col})")
    plot_residuals(res.fittedvalues, res.resid, os.path.join(out_dir, f"{prefix}_residual.png"),
                   title=f"Resíduos — {title}")
    plot_qq(res.resid, os.path.join(out_dir, f"{prefix}_qq.png"), title=f"Q-Q — {title}")


_SUMMARY_COLUMNS = [
    "segment", "model", "segment_start", "segment_end", "n_obs",
    "alpha_annualized_pct", "beta_primary", "r_squared", "alpha_pvalue",
    "significant_alpha", "beta_momentum", "beta_momentum_pvalue",
    "vif_market", "vif_momentum", "minimal_total_return_pct", "minimal_n_active_bars",
]


def _summary_row(seg: str, model_label: str, res: dict) -> dict:   # pragma: no cover
    """Linha consolidada (formato longo) para o decomposition_summary.csv."""
    return {
        "segment": seg.upper(),
        "model": model_label,
        "segment_start": res["segment_start"],
        "segment_end": res["segment_end"],
        "n_obs": res["n_obs"],
        "alpha_annualized_pct": res["alpha_annualized"],
        "beta_primary": res["beta"],
        "r_squared": res["r_squared"],
        "alpha_pvalue": res["alpha_pvalue"],
        "significant_alpha": res["significant_alpha"],
        "beta_momentum": res.get("beta_momentum", float("nan")),
        "beta_momentum_pvalue": res.get("beta_momentum_pvalue", float("nan")),
        "vif_market": res.get("vif_market", float("nan")),
        "vif_momentum": res.get("vif_momentum", float("nan")),
        "minimal_total_return_pct": res.get("minimal_total_return", float("nan")),
        "minimal_n_active_bars": res.get("minimal_n_active_bars", float("nan")),
    }


def run_decomposition(   # pragma: no cover — orquestração/rede; validada pela corrida real
    config_name: str = "sprint_13_reference",
    output_dir: str = OUTPUT_DIR,
    history_start: str = HISTORY_START,
    history_end: str | None = None,
) -> dict:
    """Baixa ^BVSP (gate S18), roda o sistema continuamente, particiona IS/OOS (70/30)
    e ajusta os 3 modelos em cada segmento.

    Disciplina do S18: ABORTA se a fonte for sintética — nunca fabricar números.

    Saídas: 6 JSONs (3 modelos × {IS, OOS}), ``decomposition_summary.csv`` e 18 PNGs
    (gitignored). Returns dict com as linhas de resumo + Sharpe bruto por segmento.
    """
    import json

    from scripts.fetch_real_data import download  # lazy: rede só no caminho de execução

    if history_end is None:
        history_end = pd.Timestamp.today().strftime("%Y-%m-%d")

    df, source = download(TICKER, history_start, history_end, interval="1d")
    if source == "synthetic":
        raise RuntimeError(
            f"{TICKER}: download retornou dados SINTÉTICOS (yfinance indisponível). "
            f"Abortado — disciplina do Sprint 18: não fabricar números.")

    config = _load_config(config_name)
    os.makedirs(output_dir, exist_ok=True)

    # O sistema roda CONTINUAMENTE sobre todo o histórico; particionamos o FLUXO de
    # retornos em IS (primeiros 70%) / OOS (últimos 30%). Os fatores (mercado, momentum,
    # sistema mínimo) são calculados no histórico completo e ALINHADOS a cada segmento —
    # momentum é público e backward-looking; não se "reinicia" num corte arbitrário.
    system_returns = build_system_returns(df, config)
    market_returns = df["Close"].pct_change().dropna().rename("market")
    market_prices = df["Close"].rename("price")

    split_date = df.index[int(len(df) * IS_FRACTION)]
    segments = {
        "is": system_returns[system_returns.index < split_date],
        "oos": system_returns[system_returns.index >= split_date],
    }

    summary_rows = []
    sharpe_by_seg = {}
    for seg, sys_ret in segments.items():
        seg_start, seg_end = str(sys_ret.index[0].date()), str(sys_ret.index[-1].date())
        sharpe_by_seg[seg] = round(_sharpe_annualized(sys_ret), 4)

        m1 = fit_capm_local(sys_ret, market_returns)
        m2 = fit_capm_plus_momentum(sys_ret, market_returns, market_prices)
        m3 = fit_vs_minimal_system(sys_ret, df)

        models = [("1-CAPM", "model1_capm", m1),
                  ("2-Momentum", "model2_momentum", m2),
                  ("3-Minimal", "model3_minimal", m3)]
        for label, tag, res in models:
            res_out = dict(res)
            res_out.update({"ticker": TICKER, "segment": seg.upper(),
                            "segment_start": seg_start, "segment_end": seg_end})
            json_path = os.path.join(output_dir, f"{tag}_{TICKER_SLUG}_{seg}.json")
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(res_out, fh, indent=2, ensure_ascii=False)
            summary_rows.append(_summary_row(seg, label, res_out))

        # Visualizações (PNGs gitignored): designs alinhados de cada modelo.
        a1 = _align(system=sys_ret, market=market_returns)
        _emit_model_viz(a1["system"], a1[["market"]], "market", output_dir,
                        f"model1_{CONFIG_FILE_LABEL}_{TICKER_SLUG}_{seg}",
                        f"M1 CAPM — {TICKER} {seg.upper()} ({seg_start}→{seg_end})")
        mom = _momentum_factor(market_prices, 252, 21)
        a2 = _align(system=sys_ret, market=market_returns, mom=mom)
        _emit_model_viz(a2["system"], a2[["market", "mom"]], "market", output_dir,
                        f"model2_{CONFIG_FILE_LABEL}_{TICKER_SLUG}_{seg}",
                        f"M2 +Momentum — {TICKER} {seg.upper()} ({seg_start}→{seg_end})")
        minimal, _ = build_minimal_system_returns(df)
        a3 = _align(system=sys_ret, minimal=minimal)
        _emit_model_viz(a3["system"], a3[["minimal"]], "minimal", output_dir,
                        f"model3_{CONFIG_FILE_LABEL}_{TICKER_SLUG}_{seg}",
                        f"M3 vs Mínimo — {TICKER} {seg.upper()} ({seg_start}→{seg_end})")

    summary_path = os.path.join(output_dir, "decomposition_summary.csv")
    pd.DataFrame(summary_rows, columns=_SUMMARY_COLUMNS).to_csv(summary_path, index=False)

    return {"rows": summary_rows, "sharpe_by_segment": sharpe_by_seg,
            "split_date": str(split_date.date()), "n_total_bars": int(len(df)),
            "summary_path": summary_path}


def main(argv: list[str] | None = None) -> int:   # pragma: no cover — CLI/rede
    import argparse

    parser = argparse.ArgumentParser(
        description="Sprint 20 — decomposição fatorial do alpha (3 modelos OLS/HAC, IS+OOS).")
    parser.add_argument("--ticker", default=TICKER,
                        help=f"ticker (default: {TICKER}; só ^BVSP é oficial neste sprint)")
    parser.add_argument("--config", default="sprint_13_reference",
                        help="config de params (default: sprint_13_reference)")
    args = parser.parse_args(argv)

    if args.ticker != TICKER:
        print(f"  [nota] --ticker {args.ticker} ignorado: este sprint roda o oficial {TICKER}.")

    print("=" * 96)
    print(" Sprint 20 — Decomposição fatorial do alpha (CAPM / +Momentum / vs Mínimo)")
    print(" Split IS/OOS = 70/30 sobre o fluxo de retornos do sistema completo")
    print("=" * 96)
    try:
        out = run_decomposition(config_name=args.config)
    except RuntimeError as e:
        print(f"  [ABORT] {e}")
        return 1

    print(f"\n  Histórico: {out['n_total_bars']} barras | split em {out['split_date']} "
          f"(IS<split | OOS>=split)")
    print(f"  Sharpe bruto do sistema: IS={out['sharpe_by_segment']['is']} | "
          f"OOS={out['sharpe_by_segment']['oos']}")
    print("\n  " + "-" * 92)
    print(f"  {'SEG':<4} {'MODELO':<12} {'alpha_ann%':>11} {'beta':>8} {'R²':>7} "
          f"{'p(alpha)':>10} {'sig?':>5}")
    print("  " + "-" * 92)
    for r in out["rows"]:
        print(f"  {r['segment']:<4} {r['model']:<12} {r['alpha_annualized_pct']:>11.4f} "
              f"{r['beta_primary']:>8.4f} {r['r_squared']:>7.4f} "
              f"{r['alpha_pvalue']:>10.4g} {('SIM' if r['significant_alpha'] else 'não'):>5}")
    print("  " + "-" * 92)
    print(f"\n  Resumo: {out['summary_path']}")
    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
