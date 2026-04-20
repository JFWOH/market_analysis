# stress_test.py — Sprint-7 passo 1: Stress Testing via Monte Carlo Bootstrap
"""
Análise de risco sob cenários extremos usando três métodos complementares:

1. Bootstrap de retornos de trades
   Reamostra os retornos realizados (com reposição) N vezes para estimar a
   distribuição de equity curves alternativas. Produz:
     - VaR(95%) / CVaR(95%) da equity final
     - Distribuição de MDD (Maximum Drawdown)
     - Percentis de retorno total (5%, 25%, 50%, 75%, 95%)

2. Simulação de retornos sintéticos (GBM com jump diffusion)
   Gera N trajetórias de preço com deriva + vol + saltos (eventos extremos).
   Útil para testar o sistema em regimes nunca vistos nos dados históricos.

3. Cenários de stress paramétrico
   Aplica choques ao sistema: vol × 2, drift × -1 (crash), correlação
   adversária. Reporta degradação de PF e DD em cada cenário.

Uso:
    st = StressTester(trades=backtester.trades, equity=equity_curve)
    report = st.run(n_sim=1000)
    st.print_report(report)
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

try:
    from backtester import Backtester
except ImportError:  # permite importar stress_test sem backtester no PATH
    Backtester = None  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _max_drawdown(equity: np.ndarray) -> float:
    """MDD fracionário de uma equity curve."""
    peak = np.maximum.accumulate(equity)
    dd   = (equity - peak) / np.where(peak > 0, peak, 1)
    return float(abs(dd.min()))


def _cvar(returns: np.ndarray, alpha: float = 0.05) -> float:
    """CVaR (Expected Shortfall) no nível alpha."""
    cutoff = np.quantile(returns, alpha)
    tail   = returns[returns <= cutoff]
    return float(tail.mean()) if len(tail) > 0 else float(cutoff)


# ─────────────────────────────────────────────────────────────────────────────
# StressTester
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StressReport:
    """Resultados de um stress test."""
    # Bootstrap
    bootstrap_final_ret_pct: dict = field(default_factory=dict)   # percentis
    bootstrap_var95:          float = 0.0    # VaR 95% (perda)
    bootstrap_cvar95:         float = 0.0    # CVaR 95% (Expected Shortfall)
    bootstrap_mdd_median:     float = 0.0
    bootstrap_mdd_p95:        float = 0.0
    bootstrap_n_ruin:         int   = 0      # simulações que zeraram capital

    # GBM com jumps
    gbm_ret_p05:              float = 0.0
    gbm_ret_p50:              float = 0.0
    gbm_ret_p95:              float = 0.0
    gbm_mdd_median:           float = 0.0
    gbm_mdd_p95:              float = 0.0

    # Cenários paramétricos
    scenarios:                dict  = field(default_factory=dict)

    # Meta
    n_trades_original:        int   = 0
    n_simulations:            int   = 0
    initial_capital:          float = 100_000.0


class StressTester:
    """
    Executa stress tests sobre resultados de backtesting.

    Parameters
    ----------
    trades          : lista de dicts de trades (output de Backtester.trades).
    equity          : pd.Series ou np.ndarray com a equity curve.
    initial_capital : capital inicial (default 100_000).
    """

    def __init__(
        self,
        trades: list[dict],
        equity: pd.Series | np.ndarray | None = None,
        initial_capital: float = 100_000.0,
    ) -> None:
        self.trades          = trades or []
        self.initial_capital = initial_capital

        if equity is not None:
            self._equity = np.asarray(equity, dtype=float)
        else:
            self._equity = self._reconstruct_equity()

    # ──────────────────────────────────────────────────────────────────────────

    def _reconstruct_equity(self) -> np.ndarray:
        """Reconstrói equity curve a partir da lista de trades."""
        cap = self.initial_capital
        eq  = [cap]
        for t in self.trades:
            cap += t.get("pnl", 0)
            eq.append(cap)
        return np.array(eq)

    def _trade_returns(self) -> np.ndarray:
        """Retornos fracionários por trade: pnl / amount."""
        rets = []
        for t in self.trades:
            amt = t.get("amount", t.get("original_amount", 0))
            pnl = t.get("pnl", 0)
            if amt and amt > 0:
                rets.append(pnl / amt)
        return np.array(rets) if rets else np.zeros(1)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Bootstrap
    # ──────────────────────────────────────────────────────────────────────────

    def bootstrap(self, n_sim: int = 1000, rng: np.random.Generator | None = None
                  ) -> dict[str, Any]:
        """Bootstrap de retornos de trades com reposição."""
        rng   = rng or np.random.default_rng(42)
        rets  = self._trade_returns()
        n     = max(len(rets), 1)
        cap0  = self.initial_capital

        final_rets: list[float] = []
        mdds:       list[float] = []
        n_ruin = 0

        for _ in range(n_sim):
            sample = rng.choice(rets, size=n, replace=True)
            # Equity simulada
            capital = cap0
            eq = [capital]
            ruin = False
            for r in sample:
                # Assume alocação de 10% do capital por trade (simplificação)
                pnl = capital * 0.10 * r
                capital = max(capital + pnl, 0.0)
                eq.append(capital)
                if capital <= cap0 * 0.20:   # ruin = perdeu 80%
                    ruin = True
                    break
            if ruin:
                n_ruin += 1

            eq_arr = np.array(eq)
            final_ret = (eq_arr[-1] / cap0 - 1.0) * 100
            final_rets.append(final_ret)
            mdds.append(_max_drawdown(eq_arr) * 100)

        fr  = np.array(final_rets)
        mdd = np.array(mdds)
        return {
            "final_ret_pct": {
                "p05": float(np.percentile(fr, 5)),
                "p25": float(np.percentile(fr, 25)),
                "p50": float(np.percentile(fr, 50)),
                "p75": float(np.percentile(fr, 75)),
                "p95": float(np.percentile(fr, 95)),
            },
            "var95":      float(-np.percentile(fr, 5)),    # VaR como perda positiva
            "cvar95":     float(-_cvar(fr, alpha=0.05)),
            "mdd_median": float(np.median(mdd)),
            "mdd_p95":    float(np.percentile(mdd, 95)),
            "n_ruin":     n_ruin,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 2. GBM com Jump Diffusion
    # ──────────────────────────────────────────────────────────────────────────

    def gbm_jump(
        self,
        n_sim: int = 1000,
        n_steps: int = 252,
        mu: float | None = None,
        sigma: float | None = None,
        jump_intensity: float = 5.0,    # saltos/ano esperados
        jump_mean: float = -0.03,       # média do salto (neg = crash)
        jump_std: float = 0.04,
        rng: np.random.Generator | None = None,
    ) -> dict[str, Any]:
        """
        Simula N trajetórias de preço via GBM + Poisson jumps.

        Se mu/sigma não fornecidos, estima a partir dos retornos de trades.
        """
        rng = rng or np.random.default_rng(42)
        rets = self._trade_returns()

        # Estima parâmetros se não fornecidos
        if mu is None:
            mu = float(rets.mean()) * n_steps
        if sigma is None:
            sigma = max(float(rets.std()) * np.sqrt(n_steps), 0.05)

        dt          = 1.0 / n_steps
        jump_prob   = jump_intensity * dt
        cap0        = self.initial_capital

        final_rets: list[float] = []
        mdds:       list[float] = []

        for _ in range(n_sim):
            capital = cap0
            eq = [capital]
            for _ in range(n_steps):
                # Difusão
                z     = rng.standard_normal()
                drift = (mu - 0.5 * sigma**2) * dt
                diffusion = sigma * np.sqrt(dt) * z
                # Salto
                if rng.random() < jump_prob:
                    jump = rng.normal(jump_mean, jump_std)
                else:
                    jump = 0.0
                ret = drift + diffusion + jump
                capital = max(capital * np.exp(ret), 0.0)
                eq.append(capital)

            eq_arr = np.array(eq)
            final_rets.append((eq_arr[-1] / cap0 - 1.0) * 100)
            mdds.append(_max_drawdown(eq_arr) * 100)

        fr  = np.array(final_rets)
        mdd = np.array(mdds)
        return {
            "ret_p05":    float(np.percentile(fr, 5)),
            "ret_p50":    float(np.percentile(fr, 50)),
            "ret_p95":    float(np.percentile(fr, 95)),
            "mdd_median": float(np.median(mdd)),
            "mdd_p95":    float(np.percentile(mdd, 95)),
            "sigma_used": sigma,
            "mu_used":    mu,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Cenários paramétricos
    # ──────────────────────────────────────────────────────────────────────────

    def parametric_scenarios(
        self, strategy_class, data: pd.DataFrame, base_params: dict,
        ticker: str = "^BVSP",
    ) -> dict[str, dict]:
        """
        Aplica choques paramétricos aos dados e reporta degradação.

        Cenários:
          - vol_2x    : multiplica High-Low por 2 (regime de alta vol)
          - crash_20  : aplica drawdown de -20% nos últimos 20% dos dados
          - thin_vol  : reduz Volume para 10% (iliquidez extrema)
          - rally_20  : aplica rali de +20% nos últimos 20% (bull trap)
        """
        def _run(df_mod: pd.DataFrame) -> dict:
            s = strategy_class(ticker, name="stress")
            s.set_data(df_mod.copy())
            s.params.update(base_params)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return Backtester(s, initial_capital=self.initial_capital,
                                  cooldown_bars=2,
                                  commission_per_trade=0.001,
                                  slippage_pct=0.001).run()

        # Baseline
        m_base = _run(data)

        results: dict[str, dict] = {"baseline": {
            "pf": m_base.get("profit_factor", 0) or 0,
            "ret_pct": (m_base.get("return_pct", 0) or 0) * 100,
            "mdd": m_base.get("max_drawdown", 0) or 0,
            "trades": m_base.get("trade_count", 0) or 0,
        }}

        scenarios = {}

        # vol_2x
        df_v2 = data.copy()
        mid   = (df_v2["High"] + df_v2["Low"]) / 2
        df_v2["High"] = mid + (df_v2["High"] - mid) * 2
        df_v2["Low"]  = mid - (mid - df_v2["Low"])  * 2
        df_v2["Low"]  = df_v2["Low"].clip(lower=0.01)
        scenarios["vol_2x"] = df_v2

        # crash_20
        df_cr = data.copy()
        n     = len(df_cr)
        tail  = int(n * 0.20)
        decay = np.linspace(1.0, 0.80, tail)
        for col in ["Open", "High", "Low", "Close"]:
            df_cr.loc[df_cr.index[-tail:], col] = df_cr[col].iloc[-tail:].values * decay
        scenarios["crash_20pct"] = df_cr

        # thin_vol
        df_tv = data.copy()
        df_tv["Volume"] = df_tv["Volume"] * 0.10
        scenarios["thin_vol_10pct"] = df_tv

        # rally_20
        df_rl = data.copy()
        rally = np.linspace(1.0, 1.20, tail)
        for col in ["Open", "High", "Low", "Close"]:
            df_rl.loc[df_rl.index[-tail:], col] = df_rl[col].iloc[-tail:].values * rally
        scenarios["rally_20pct"] = df_rl

        for name, df_s in scenarios.items():
            m = _run(df_s)
            pf  = m.get("profit_factor", 0) or 0
            ret = (m.get("return_pct",   0) or 0) * 100
            mdd = m.get("max_drawdown",  0) or 0
            tc  = m.get("trade_count",   0) or 0
            base_pf = results["baseline"]["pf"]
            results[name] = {
                "pf":      pf,
                "ret_pct": ret,
                "mdd":     mdd,
                "trades":  tc,
                "dpf":     pf - base_pf,
            }

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Orquestrador
    # ──────────────────────────────────────────────────────────────────────────

    def run(
        self,
        n_sim: int = 1000,
        include_gbm: bool = True,
        strategy_class=None,
        data: pd.DataFrame | None = None,
        base_params: dict | None = None,
        ticker: str = "^BVSP",
    ) -> StressReport:
        """Executa todos os stress tests e retorna StressReport."""
        rng  = np.random.default_rng(42)
        boot = self.bootstrap(n_sim=n_sim, rng=rng)

        report = StressReport(
            bootstrap_final_ret_pct = boot["final_ret_pct"],
            bootstrap_var95         = boot["var95"],
            bootstrap_cvar95        = boot["cvar95"],
            bootstrap_mdd_median    = boot["mdd_median"],
            bootstrap_mdd_p95       = boot["mdd_p95"],
            bootstrap_n_ruin        = boot["n_ruin"],
            n_trades_original       = len(self.trades),
            n_simulations           = n_sim,
            initial_capital         = self.initial_capital,
        )

        if include_gbm:
            gbm = self.gbm_jump(n_sim=n_sim, rng=rng)
            report.gbm_ret_p05    = gbm["ret_p05"]
            report.gbm_ret_p50    = gbm["ret_p50"]
            report.gbm_ret_p95    = gbm["ret_p95"]
            report.gbm_mdd_median = gbm["mdd_median"]
            report.gbm_mdd_p95    = gbm["mdd_p95"]

        if strategy_class is not None and data is not None:
            report.scenarios = self.parametric_scenarios(
                strategy_class, data, base_params or {}, ticker=ticker,
            )

        return report

    @staticmethod
    def print_report(report: StressReport) -> None:
        """Imprime o StressReport formatado no terminal."""
        W = 66
        def _box(t):  return "+" + "-"*((W-len(t)-2)//2) + f" {t} " + "-"*((W-len(t)-1)//2) + "+"
        def _line(t): return f"| {t:<{W-2}} |"
        def _sep():   return "+" + "-"*W + "+"

        print(_sep())
        print(_line(f"STRESS TEST REPORT  ({report.n_simulations} simulacoes, "
                    f"{report.n_trades_original} trades)"))
        print(_sep())

        # Bootstrap
        print(_box("Bootstrap de Retornos de Trades"))
        p = report.bootstrap_final_ret_pct
        print(_line(f"  Retorno final (%): p05={p.get('p05',0):+.1f}  "
                    f"p25={p.get('p25',0):+.1f}  p50={p.get('p50',0):+.1f}  "
                    f"p75={p.get('p75',0):+.1f}  p95={p.get('p95',0):+.1f}"))
        print(_line(f"  VaR 95%   (perda max esperada): {report.bootstrap_var95:.2f}%"))
        print(_line(f"  CVaR 95%  (Expected Shortfall): {report.bootstrap_cvar95:.2f}%"))
        print(_line(f"  MDD median: {report.bootstrap_mdd_median:.2f}%   "
                    f"MDD p95: {report.bootstrap_mdd_p95:.2f}%"))
        print(_line(f"  Simulacoes em ruina (perda >80%): {report.bootstrap_n_ruin} "
                    f"({report.bootstrap_n_ruin/report.n_simulations*100:.1f}%)"))
        print(_sep())

        # GBM
        if report.gbm_ret_p50 != 0 or report.gbm_mdd_p95 != 0:
            print(_box("GBM + Jump Diffusion (cenarios sinteticos)"))
            print(_line(f"  Retorno (%) p05={report.gbm_ret_p05:+.1f}  "
                        f"p50={report.gbm_ret_p50:+.1f}  "
                        f"p95={report.gbm_ret_p95:+.1f}"))
            print(_line(f"  MDD median: {report.gbm_mdd_median:.2f}%   "
                        f"MDD p95: {report.gbm_mdd_p95:.2f}%"))
            print(_sep())

        # Cenários paramétricos
        if report.scenarios:
            print(_box("Cenarios Parametricos"))
            print(_line(f"  {'Cenario':<20} {'PF':>6} {'dPF':>6} {'Ret%':>7} {'MDD%':>7} {'Trades':>7}"))
            print(_line("  " + "-" * 52))
            for name, m in report.scenarios.items():
                mark = "  [BASE]" if name == "baseline" else ""
                print(_line(f"  {name:<20} {m['pf']:>6.3f} "
                             f"{m.get('dpf',0):>+6.3f} "
                             f"{m['ret_pct']:>7.2f} {m['mdd']:>7.3f} "
                             f"{m['trades']:>7}{mark}"))
            print(_sep())
