# scripts/bear_market_validation_v2.py — Sprint 22: bears não-canônicos (validação expandida)
"""Valida a config **base auditada Sprint-13** (decisão A do S22 — `SPRINT13_PARAMS`,
registry `sprint_13_reference`; "validada" = base que passou pela auditoria, NÃO "a que
foi aprovada — o S21 mostrou que nenhuma config tem edge OOS) em 15 cenários de bear
não-canônicos lidos de ``scenarios/bears_v2.yaml``.

Natureza (padrão S19): apesar de viver em ``scripts/``, o núcleo é **biblioteca** —
``load_scenarios``, ``run_scenario``, ``bootstrap_sharpe_ci``, ``classify_status`` e os
plots são funções puras/testáveis (sem rede; ``strategy_factory`` e ``fetcher`` são *seams*
de teste). Só ``_default_fetcher`` e ``main`` tocam a rede.

Reuso (DRY, confirmado no plano CP1):
  • MDD dual (S18): ``metrics.compute_drawdown_dual`` sobre as curvas recortadas à janela
    de eval — mesmo idioma de ``scripts/rerun_bear_validation_dual_mdd.py``.
  • Custos (S19): ``Backtester(commission_pct=, slippage_pct=)`` em duas bases (0.1% e 0.3%).
  • ``SPRINT13_PARAMS``/``CAPITAL``/``_bh_metrics`` de ``scripts/bear_market_validation.py``.

Métrica de Sharpe: a coluna ``sharpe`` é o Sharpe **anualizado** do backtester (headline,
comparável a S18/S21). O IC (``sharpe_ci_*``) é **trade-level** — bootstrap dos retornos por
trade — uma banda de dispersão/robustez, distinta do headline (documentado no finding).

Uso:
    python scripts/bear_market_validation_v2.py
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtester import Backtester
from metrics import compute_drawdown_dual

try:  # execução como pacote (testes: from scripts.bear_market_validation_v2 import ...)
    from scripts.bear_market_validation import CAPITAL, _bh_metrics
    from scripts.cost_sensitivity import _load_config
except ImportError:  # execução direta do script (sys.path já tem a raiz)
    from bear_market_validation import CAPITAL, _bh_metrics
    from cost_sensitivity import _load_config

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────

ALLOWED_CATEGORIES = {
    "crash_linear", "regional", "mean_reverting_brutal", "lost_decade", "forex",
}
# Categorias-núcleo entram no placar aprovado/reprovado; forex é sanity-check à parte (decisão C).
CORE_CATEGORIES = {"crash_linear", "regional", "mean_reverting_brutal", "lost_decade"}
REQUIRED_FIELDS = ("id", "name", "ticker", "start", "end", "category")

BASELINE_SLIP = 0.001   # 0.1% (S19 / CLAUDE.md §6.6)
STRESS_SLIP = 0.003     # 0.3% (pessimista realista)
BASELINE_COMM = 0.001   # 0.1% comissão fracionária por perna
COOLDOWN_BARS = 2
WARMUP_CALENDAR_DAYS = 180   # buffer antes de scenario.start p/ aquecer indicadores
MIN_BARS = 30                # mínimo p/ considerar o cenário executável

# Status: aprovado (sharpe>0 e mdd_car<10) | reprovado (sharpe<0 ou mdd_car>15) | inconclusivo.
MDD_CAR_OK = 10.0
MDD_CAR_FAIL = 15.0

CSV_COLUMNS = [
    "scenario_id", "name", "ticker", "category", "start", "end", "source", "n_bars",
    "num_trades", "sharpe", "sharpe_ci_low", "sharpe_ci_point", "sharpe_ci_high",
    "profit_factor", "win_rate", "return_pct", "alpha_vs_bh_pp",
    "mdd_equity_pct", "mdd_car_pct", "time_in_market_pct",
    "sharpe_slip03", "pf_slip03", "status",
]

CATEGORY_ORDER = ["crash_linear", "regional", "mean_reverting_brutal", "lost_decade", "forex"]
CATEGORY_COLORS = {
    "crash_linear": "#2196F3",          # azul
    "regional": "#FF9800",              # laranja
    "mean_reverting_brutal": "#F44336", # vermelho
    "lost_decade": "#9E9E9E",           # cinza
    "forex": "#9C27B0",                 # roxo
}


def _num(x) -> float:
    """Converte para float, mapeando None/ausente → NaN (preserva inf)."""
    if x is None:
        return float("nan")
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


# ──────────────────────────────────────────────────────────────────────────────
# E1 — Schema + validação manual (sem pydantic; decisão de reuso §2.4)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Scenario:
    """Um cenário de bear. Datas em ISO 'YYYY-MM-DD' (str)."""
    id: str
    name: str
    ticker: str
    start: str
    end: str
    category: str
    notes: str = ""


def _validate_date(value, field: str, sid: str) -> str:
    """Aceita str ISO ou datetime.date (PyYAML pode parsear data não-quotada).
    Normaliza para 'YYYY-MM-DD' e valida o formato. Levanta ValueError."""
    s = value.isoformat() if hasattr(value, "isoformat") else str(value)
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"cenário {sid!r}: campo {field!r} não é data ISO YYYY-MM-DD: {value!r}") from e
    return s


def load_scenarios(yaml_path: str) -> list[Scenario]:
    """Carrega + valida ``bears_v2.yaml`` (pyyaml, sem pydantic).

    Levanta ``ValueError`` com mensagem clara em: arquivo sem chave ``scenarios``,
    campo obrigatório ausente, ``category`` fora do enum, data não-ISO, ``start >= end``,
    ou ``id`` duplicado.
    """
    with open(yaml_path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)

    if not isinstance(doc, dict) or "scenarios" not in doc:
        raise ValueError(f"{yaml_path}: faltando a chave de topo 'scenarios'")
    raw = doc["scenarios"]
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{yaml_path}: 'scenarios' deve ser uma lista não-vazia")

    seen_ids: set[str] = set()
    scenarios: list[Scenario] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"cenário #{i}: esperado mapeamento, veio {type(item).__name__}")
        missing = [f for f in REQUIRED_FIELDS if f not in item or item[f] in (None, "")]
        if missing:
            raise ValueError(f"cenário #{i} ({item.get('id', '?')}): campos obrigatórios "
                             f"ausentes: {missing}")
        sid = str(item["id"])
        if sid in seen_ids:
            raise ValueError(f"id duplicado: {sid!r}")
        seen_ids.add(sid)

        cat = str(item["category"])
        if cat not in ALLOWED_CATEGORIES:
            raise ValueError(f"cenário {sid!r}: category {cat!r} fora do enum "
                             f"{sorted(ALLOWED_CATEGORIES)}")

        start = _validate_date(item["start"], "start", sid)
        end = _validate_date(item["end"], "end", sid)
        if start >= end:
            raise ValueError(f"cenário {sid!r}: start ({start}) deve ser < end ({end})")

        scenarios.append(Scenario(
            id=sid, name=str(item["name"]), ticker=str(item["ticker"]),
            start=start, end=end, category=cat, notes=str(item.get("notes", "")),
        ))
    return scenarios


def load_base_config(name: str = "sprint_13_reference") -> dict:
    """Config 'base auditada' do S22 (decisão A). Reusa o registry de
    ``cost_sensitivity._load_config`` — "validada" = base que passou pela auditoria,
    NÃO "aprovada" (S21: nenhuma config tem edge OOS)."""
    return _load_config(name)


# ──────────────────────────────────────────────────────────────────────────────
# E2 — Núcleo de execução por cenário (puro; sem rede)
# ──────────────────────────────────────────────────────────────────────────────

def run_scenario(
    df: pd.DataFrame,
    scenario: Scenario,
    base_params: dict,
    capital: float = CAPITAL,
    slippage_pct: float = BASELINE_SLIP,
    commission_pct: float = BASELINE_COMM,
    cooldown_bars: int = COOLDOWN_BARS,
    strategy_factory=None,
) -> dict:
    """Roda UM cenário sobre ``df`` in-memory (já com warmup antes de ``scenario.start``).

    Backtest com a base Sprint-13 → métricas. MDD dual + time-in-market via
    ``compute_drawdown_dual`` nas curvas RECORTADAS à janela de eval ``[start, end]``
    (fiel ao S18). ``sharpe``/``pf``/``win_rate``/``return``/``num_trades`` vêm da rodada
    completa. Alpha vs B&H via ``_bh_metrics`` no eval.

    ``strategy_factory`` é um *seam* de teste: ``(df) -> strategy``. None no uso de produção
    (constrói ``CombinedStrategy`` + base_params). Não interfere no caminho de produção.

    Returns
    -------
    dict com num_trades, sharpe, profit_factor, win_rate, return_pct, mdd_equity_pct,
    mdd_car_pct (NaN se nunca houve posição), time_in_market_pct, alpha_vs_bh_pp e
    trade_returns (np.ndarray de pnl/amount por trade, para o bootstrap).
    """
    if strategy_factory is not None:
        strat = strategy_factory(df)
    else:
        from strategy import CombinedStrategy  # lazy: caminho de produção
        strat = CombinedStrategy(scenario.ticker)
        strat.set_data(df.copy())
        strat.params.update(base_params)

    bt = Backtester(
        strat, initial_capital=capital, cooldown_bars=cooldown_bars,
        commission_per_trade=0.0, commission_pct=commission_pct, slippage_pct=slippage_pct,
    )
    m = bt.run()

    start_ts, end_ts = pd.Timestamp(scenario.start), pd.Timestamp(scenario.end)
    eq = pd.Series(bt.equity, index=bt.equity_dates)
    pv = pd.Series(bt.position_value, index=bt.equity_dates)
    win = (eq.index >= start_ts) & (eq.index <= end_ts)
    eq_e, pv_e = eq[win], pv[win]

    if len(eq_e) >= 2:
        dual = compute_drawdown_dual(eq_e, pv_e)
        mdd_eq = _num(dual["total_equity_mdd"])
        mdd_car = _num(dual["capital_at_risk_mdd"])
        tim = _num(dual["time_in_market_pct"])
    else:  # janela curtíssima — cai p/ métricas da rodada completa
        mdd_eq = _num(m.get("max_drawdown_total_equity_pct"))
        mdd_car = _num(m.get("max_drawdown_capital_at_risk_pct"))
        tim = float("nan")

    ret_pct = _num(m.get("return_pct")) * 100.0
    closes_e = df["Close"][(df.index >= start_ts) & (df.index <= end_ts)]
    bh_ret = _bh_metrics(closes_e, capital)["ret_pct"] if len(closes_e) >= 1 else float("nan")
    alpha_pp = ret_pct - bh_ret

    trade_returns = np.array(
        [t["pnl"] / t["amount"] for t in bt.trades if t.get("amount")], dtype=float
    )

    return {
        "num_trades": int(m.get("trade_count", len(bt.trades)) or 0),
        "sharpe": _num(m.get("sharpe_ratio")),
        "profit_factor": _num(m.get("profit_factor")),
        "win_rate": _num(m.get("win_rate")),
        "return_pct": ret_pct,
        "mdd_equity_pct": mdd_eq,
        "mdd_car_pct": mdd_car,
        "time_in_market_pct": tim,
        "alpha_vs_bh_pp": alpha_pp,
        "trade_returns": trade_returns,
    }


def bootstrap_sharpe_ci(
    trade_returns, n_samples: int = 1000,
    rng: np.random.Generator | None = None, ci: float = 0.95,
) -> tuple[float, float, float]:
    """IC bootstrap (trade-level) do Sharpe por reamostragem com reposição dos
    retornos por trade. Retorna ``(low, point, high)``.

    Determinístico para uma dada ``rng`` (``np.random.default_rng(42)`` default).
    ``(NaN, NaN, NaN)`` se houver < 2 trades finitos.
    """
    rng = rng if rng is not None else np.random.default_rng(42)
    rets = np.asarray(trade_returns, dtype=float)
    rets = rets[np.isfinite(rets)]
    if rets.size < 2:
        return (float("nan"), float("nan"), float("nan"))

    def _sharpe(a: np.ndarray) -> float:
        sd = a.std(ddof=1)
        return float(a.mean() / sd) if sd > 1e-12 else 0.0

    point = _sharpe(rets)
    n = rets.size
    samples = np.empty(n_samples, dtype=float)
    for i in range(n_samples):
        samples[i] = _sharpe(rng.choice(rets, size=n, replace=True))
    alpha = (1.0 - ci) / 2.0 * 100.0
    lo = float(np.percentile(samples, alpha))
    hi = float(np.percentile(samples, 100.0 - alpha))
    return (lo, point, hi)


def classify_status(sharpe, mdd_car_pct) -> str:
    """'aprovado' (sharpe>0 e mdd_car<10) | 'reprovado' (sharpe<0 ou mdd_car>15) |
    'inconclusivo' (resto, incl. faixa 10-15% ou sharpe NaN)."""
    s = _num(sharpe)
    m = _num(mdd_car_pct)
    if not np.isnan(m) and m > MDD_CAR_FAIL:
        return "reprovado"
    if not np.isnan(s) and s < 0:
        return "reprovado"
    if not np.isnan(s) and s > 0 and (np.isnan(m) or m < MDD_CAR_OK):
        return "aprovado"
    return "inconclusivo"


# ──────────────────────────────────────────────────────────────────────────────
# E3 — Visualizações (matplotlib Agg; import tardio)
# ──────────────────────────────────────────────────────────────────────────────

def _sorted_for_plot(rows: list[dict], value_key: str) -> list[dict]:
    """Filtra linhas com value_key finito e ordena por categoria (CATEGORY_ORDER) e valor."""
    def _ok(r):
        return np.isfinite(_num(r.get(value_key)))
    kept = [r for r in rows if _ok(r)]
    return sorted(kept, key=lambda r: (CATEGORY_ORDER.index(r.get("category", "forex"))
                                       if r.get("category") in CATEGORY_ORDER else 99,
                                       _num(r.get(value_key))))


def forest_plot(
    rows: list[dict], value_key: str, out_path: str, title: str = "", xlabel: str = "",
    ci_low_key: str | None = None, ci_high_key: str | None = None,
    zero_line: bool = True, ref_lines=None,
) -> str:
    """Forest plot horizontal de ``value_key`` por cenário, cor por categoria, ordenado
    por categoria. ``ci_*_key`` desenham barras de erro; ``ref_lines`` traça verticais."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    data = _sorted_for_plot(rows, value_key)
    labels = [r.get("scenario_id", "?") for r in data]
    vals = [_num(r.get(value_key)) for r in data]
    cats = [r.get("category", "forex") for r in data]
    colors = [CATEGORY_COLORS.get(c, "#000000") for c in cats]
    y = np.arange(len(data))

    fig, ax = plt.subplots(figsize=(10, max(4, 0.45 * len(data) + 2)))
    if ci_low_key and ci_high_key:
        lows = np.array([_num(r.get(ci_low_key)) for r in data])
        highs = np.array([_num(r.get(ci_high_key)) for r in data])
        v = np.array(vals)
        xerr = np.vstack([np.clip(v - lows, 0, None), np.clip(highs - v, 0, None)])
        ax.errorbar(vals, y, xerr=xerr, fmt="none", ecolor="#777777", capsize=3, zorder=1)
    ax.scatter(vals, y, c=colors, s=60, zorder=2, edgecolors="black", linewidths=0.5)

    if zero_line:
        ax.axvline(0.0, color="black", linestyle="-", alpha=0.5)
    for rl in (ref_lines or []):
        ax.axvline(rl, color="red", linestyle="--", alpha=0.5)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel(xlabel or value_key)
    ax.set_title(title or value_key)
    ax.grid(True, axis="x", alpha=0.3)
    present = [c for c in CATEGORY_ORDER if c in set(cats)]
    ax.legend(handles=[Patch(color=CATEGORY_COLORS[c], label=c) for c in present],
              fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def scatter_sharpe_tim(rows: list[dict], out_path: str, title: str = "") -> str:
    """Scatter Sharpe x time-in-market %, cor por categoria."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    data = [r for r in rows if np.isfinite(_num(r.get("sharpe")))
            and np.isfinite(_num(r.get("time_in_market_pct")))]
    fig, ax = plt.subplots(figsize=(9, 6))
    for r in data:
        ax.scatter(_num(r["time_in_market_pct"]), _num(r["sharpe"]),
                   c=CATEGORY_COLORS.get(r.get("category"), "#000000"),
                   s=70, edgecolors="black", linewidths=0.5)
    ax.axhline(0.0, color="black", alpha=0.5)
    ax.set_xlabel("Time-in-market (%)")
    ax.set_ylabel("Sharpe (anualizado)")
    ax.set_title(title or "Sharpe x Time-in-market")
    ax.grid(True, alpha=0.3)
    present = [c for c in CATEGORY_ORDER if c in {r.get("category") for r in data}]
    ax.legend(handles=[Patch(color=CATEGORY_COLORS[c], label=c) for c in present],
              fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def category_medians_bar(rows: list[dict], out_path: str, value_key: str = "sharpe",
                         title: str = "") -> str:
    """Barras: mediana de ``value_key`` por categoria (ordem CATEGORY_ORDER)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cats, meds, colors = [], [], []
    for c in CATEGORY_ORDER:
        vals = [_num(r.get(value_key)) for r in rows
                if r.get("category") == c and np.isfinite(_num(r.get(value_key)))]
        if vals:
            cats.append(c)
            meds.append(float(np.median(vals)))
            colors.append(CATEGORY_COLORS[c])

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.bar(np.arange(len(cats)), meds, color=colors, edgecolor="black", linewidth=0.5)
    ax.axhline(0.0, color="black", alpha=0.5)
    ax.set_xticks(np.arange(len(cats)))
    ax.set_xticklabels(cats, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel(f"Mediana de {value_key}")
    ax.set_title(title or f"Mediana de {value_key} por categoria")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


# ──────────────────────────────────────────────────────────────────────────────
# Montagem de linhas + sumário
# ──────────────────────────────────────────────────────────────────────────────

def _unavailable_row(sc: Scenario, source: str) -> dict:
    """Linha de cenário com dados indisponíveis (gate S18) — sem números fabricados."""
    row = {c: float("nan") for c in CSV_COLUMNS}
    row.update({
        "scenario_id": sc.id, "name": sc.name, "ticker": sc.ticker, "category": sc.category,
        "start": sc.start, "end": sc.end, "source": source, "n_bars": 0,
        "num_trades": 0, "status": "data_unavailable",
    })
    return row


def _assemble_row(sc: Scenario, source: str, n_bars: int, base: dict, stress: dict,
                  ci: tuple[float, float, float], status: str) -> dict:
    lo, point, hi = ci
    return {
        "scenario_id": sc.id, "name": sc.name, "ticker": sc.ticker, "category": sc.category,
        "start": sc.start, "end": sc.end, "source": source, "n_bars": int(n_bars),
        "num_trades": int(base["num_trades"]),
        "sharpe": round(base["sharpe"], 4),
        "sharpe_ci_low": round(lo, 4), "sharpe_ci_point": round(point, 4),
        "sharpe_ci_high": round(hi, 4),
        "profit_factor": round(base["profit_factor"], 4),
        "win_rate": round(base["win_rate"], 4),
        "return_pct": round(base["return_pct"], 4),
        "alpha_vs_bh_pp": round(base["alpha_vs_bh_pp"], 4),
        "mdd_equity_pct": round(base["mdd_equity_pct"], 4),
        "mdd_car_pct": round(base["mdd_car_pct"], 4),
        "time_in_market_pct": round(base["time_in_market_pct"], 2),
        "sharpe_slip03": round(stress["sharpe"], 4),
        "pf_slip03": round(stress["profit_factor"], 4),
        "status": status,
    }


def summarize_coverage(rows: list[dict]) -> dict:
    """Sumário de cobertura para o piso B: executados, categorias-núcleo presentes,
    mean_reverting_brutal presente, e contagem aprovado/reprovado (forex à parte)."""
    executed = [r for r in rows if r.get("status") != "data_unavailable"]
    core = [r for r in executed if r.get("category") in CORE_CATEGORIES]
    cats_present = {r.get("category") for r in core}
    tally = {"aprovado": 0, "reprovado": 0, "inconclusivo": 0}
    for r in core:
        tally[r.get("status", "inconclusivo")] = tally.get(r.get("status"), 0) + 1
    return {
        "total": len(rows),
        "executed": len(executed),
        "core_categories_present": sorted(cats_present),
        "mean_reverting_brutal_present": "mean_reverting_brutal" in cats_present,
        "tally_core": tally,
        "forex": [r["scenario_id"] for r in executed if r.get("category") == "forex"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Execução (orquestração) — testável via seams ``fetcher`` e ``strategy_factory``
# ──────────────────────────────────────────────────────────────────────────────

def run_all(
    yaml_path: str = "scenarios/bears_v2.yaml",
    output_dir: str = "findings/sprint_22_data",
    base_params: dict | None = None,
    base_slip: float = BASELINE_SLIP, stress_slip: float = STRESS_SLIP,
    commission_pct: float = BASELINE_COMM,
    warmup_calendar_days: int = WARMUP_CALENDAR_DAYS,
    n_bootstrap: int = 1000, seed: int = 42,
    fetcher=None, strategy_factory=None, make_plots: bool = True,
) -> pd.DataFrame:
    """Roda os cenários do YAML, escreve ``bears_complete.csv`` e os 5 plots.

    ``fetcher(ticker, start, end) -> (df, source)``: default = download real (lazy).
    Gate S18: ``source=='synthetic'`` (ou df curto) → linha ``data_unavailable``, sem fabricar.
    ``strategy_factory`` repassado a ``run_scenario`` (seam de teste; None em produção).
    """
    scenarios = load_scenarios(yaml_path)
    base_params = base_params if base_params is not None else load_base_config()
    fetch = fetcher if fetcher is not None else _default_fetcher
    rng = np.random.default_rng(seed)

    rows: list[dict] = []
    for sc in scenarios:
        warm_start = (pd.Timestamp(sc.start) - pd.Timedelta(days=warmup_calendar_days)
                      ).strftime("%Y-%m-%d")
        df, source = fetch(sc.ticker, warm_start, sc.end)
        if source == "synthetic" or df is None or len(df) < MIN_BARS:
            rows.append(_unavailable_row(sc, "synthetic" if source == "synthetic" else source))
            continue
        base = run_scenario(df, sc, base_params, slippage_pct=base_slip,
                            commission_pct=commission_pct, strategy_factory=strategy_factory)
        stress = run_scenario(df, sc, base_params, slippage_pct=stress_slip,
                              commission_pct=commission_pct, strategy_factory=strategy_factory)
        ci = bootstrap_sharpe_ci(base["trade_returns"], n_samples=n_bootstrap, rng=rng)
        status = classify_status(base["sharpe"], base["mdd_car_pct"])
        rows.append(_assemble_row(sc, source, len(df), base, stress, ci, status))

    os.makedirs(output_dir, exist_ok=True)
    df_out = pd.DataFrame(rows, columns=CSV_COLUMNS)
    df_out.to_csv(os.path.join(output_dir, "bears_complete.csv"), index=False)

    if make_plots:
        plots_dir = os.path.join(output_dir, "plots")
        os.makedirs(plots_dir, exist_ok=True)
        forest_plot(rows, "sharpe_ci_point", os.path.join(plots_dir, "forest_sharpe.png"),
                    title="Sharpe por cenário (IC95% bootstrap, trade-level)",
                    xlabel="Sharpe (trade-level)",
                    ci_low_key="sharpe_ci_low", ci_high_key="sharpe_ci_high")
        forest_plot(rows, "mdd_car_pct", os.path.join(plots_dir, "forest_mdd_car.png"),
                    title="MDD capital-at-risk por cenário", xlabel="MDD-CAR (%)",
                    zero_line=False, ref_lines=[MDD_CAR_OK, MDD_CAR_FAIL])
        forest_plot(rows, "alpha_vs_bh_pp", os.path.join(plots_dir, "forest_alpha.png"),
                    title="Alpha vs Buy&Hold por cenário", xlabel="Alpha (pp)")
        scatter_sharpe_tim(rows, os.path.join(plots_dir, "scatter_sharpe_tim.png"))
        category_medians_bar(rows, os.path.join(plots_dir, "category_medians.png"))

    return df_out


def _default_fetcher(ticker: str, start: str, end: str):   # pragma: no cover — rede
    from scripts.fetch_real_data import download
    return download(ticker, start, end, interval="1d")


def main(argv: list[str] | None = None) -> int:   # pragma: no cover — CLI/rede
    import argparse

    parser = argparse.ArgumentParser(
        description="Sprint 22 — validação em bears não-canônicos (15 cenários, base Sprint-13).")
    parser.add_argument("--yaml", default="scenarios/bears_v2.yaml")
    parser.add_argument("--output-dir", default="findings/sprint_22_data")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args(argv)

    print("=" * 96)
    print(" Sprint 22 — Bears não-canônicos (config base auditada Sprint-13)")
    print("=" * 96)

    df = run_all(yaml_path=args.yaml, output_dir=args.output_dir, make_plots=not args.no_plots)
    cov = summarize_coverage(df.to_dict("records"))

    print(f"\n  Executados: {cov['executed']}/{cov['total']} | "
          f"categorias-núcleo: {cov['core_categories_present']}")
    print(f"  mean_reverting_brutal presente: {cov['mean_reverting_brutal_present']}")
    print(f"  Placar (núcleo, forex à parte): {cov['tally_core']}")
    if not cov["mean_reverting_brutal_present"]:
        print("  [ALERTA] mean_reverting_brutal NÃO representada — finding inválido (piso B).")
    print(f"\n  CSV: {os.path.join(args.output_dir, 'bears_complete.csv')}")
    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main())
