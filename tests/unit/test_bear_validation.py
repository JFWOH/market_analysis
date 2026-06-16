"""
tests/unit/test_bear_validation.py — Sprint 22 (E4).

Testa o núcleo de validação de bears (scripts/bear_market_validation_v2.py):
schema do YAML, run_scenario, bootstrap_sharpe_ci, classify_status, forest_plot,
e o caminho data_unavailable de run_all.

Determinístico e SEM rede: usa o seam `strategy_factory` (MockStrategy com sinais
controlados, padrão do test_cost_sensitivity) e o seam `fetcher` de run_all.
"""
from __future__ import annotations

import os
import sys
from collections import Counter

import numpy as np
import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.bear_market_validation_v2 import (  # noqa: E402
    CSV_COLUMNS,
    Scenario,
    bootstrap_sharpe_ci,
    classify_status,
    forest_plot,
    load_scenarios,
    run_all,
    run_scenario,
    summarize_coverage,
)

_P = 100_000.0


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures sintéticas (sem rede) — espelham o padrão do test_cost_sensitivity
# ──────────────────────────────────────────────────────────────────────────────

class _MockStrategy:
    """Estratégia mínima: sinais fixos, sem rede."""

    def __init__(self, data, signals, params=None):
        self.data = data
        self._signals = signals
        self.params = params or {"max_position_pct": 0.5, "max_risk_pct": 0.01}
        self.name = "MOCK"

    def prepare(self):
        pass

    def generate_signals(self):
        return list(self._signals)


def _series(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    arr = np.array(closes, dtype=float)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open": arr * 0.999, "High": arr * 1.005, "Low": arr * 0.995,
        "Close": arr, "Volume": np.full(n, 10_000.0), "ATR": arr * 0.02,
    }, index=idx)


def _build(specs):
    """specs: lista de (kind, stop_m[, target_m]); kind in {'win','loss'}.
    Retorna (data, strategy_factory). Cada trade ocupa 4 barras."""
    closes = [_P, _P]
    meta = []
    for spec in specs:
        kind, stop_m = spec[0], spec[1]
        target_m = spec[2] if len(spec) > 2 else stop_m
        entry_bar = len(closes)
        stop_off = _P * stop_m
        if kind == "win":
            spike = _P * (1.0 + target_m + 0.01)
            target_off = _P * target_m
        else:
            spike = _P * (1.0 - stop_m - 0.01)
            target_off = _P * 0.03
        closes += [_P, spike, _P, _P]
        meta.append((entry_bar, stop_off, target_off))
    closes += [_P, _P]

    data = _series(closes)
    signals = []
    for entry_bar, stop_off, target_off in meta:
        pp = float(data["Close"].iloc[entry_bar])
        signals.append({
            "data": data.index[entry_bar], "tipo": "Compra", "preco": pp,
            "stop_loss": pp - stop_off, "preco_alvo": pp + target_off,
            "estrategia": "mock",
        })

    def factory(d):
        return _MockStrategy(d, signals)

    return data, factory


def _scenario_for(data: pd.DataFrame, category: str = "mean_reverting_brutal") -> Scenario:
    return Scenario(
        id="t", name="t", ticker="MOCK",
        start=str(data.index[0].date()), end=str(data.index[-1].date()),
        category=category,
    )


_VALID_YAML = """\
scenarios:
  - id: a
    name: A
    ticker: "^BVSP"
    start: "2008-06-01"
    end: "2009-06-30"
    category: crash_linear
  - id: b
    name: B
    ticker: "BRL=X"
    start: "2020-07-01"
    end: "2020-12-31"
    category: forex
"""


# ──────────────────────────────────────────────────────────────────────────────
# E4 #1 — Schema do YAML
# ──────────────────────────────────────────────────────────────────────────────

def test_yaml_schema_valid(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(_VALID_YAML, encoding="utf-8")
    scs = load_scenarios(str(p))
    assert len(scs) == 2
    assert scs[0].category == "crash_linear"
    assert scs[1].category == "forex"
    assert scs[0].start == "2008-06-01"  # normalizado p/ str ISO


def test_real_yaml_loads_expected_categories():
    """O bears_v2.yaml versionado: 15 cenários, 5 categorias, contagens da decisão C."""
    scs = load_scenarios(os.path.join(_ROOT, "scenarios", "bears_v2.yaml"))
    assert len(scs) == 15
    cats = Counter(s.category for s in scs)
    assert cats["crash_linear"] == 6
    assert cats["regional"] == 4
    assert cats["mean_reverting_brutal"] == 3
    assert cats["lost_decade"] == 1
    assert cats["forex"] == 1


@pytest.mark.parametrize("mutate", [
    "missing_field", "bad_category", "bad_date", "start_after_end", "dup_id", "no_key",
])
def test_yaml_schema_rejects_bad(tmp_path, mutate):
    docs = {
        "missing_field": "scenarios:\n  - id: a\n    name: A\n    ticker: X\n    start: \"2020-01-01\"\n    category: regional\n",
        "bad_category": "scenarios:\n  - id: a\n    name: A\n    ticker: X\n    start: \"2020-01-01\"\n    end: \"2020-02-01\"\n    category: bananas\n",
        "bad_date": "scenarios:\n  - id: a\n    name: A\n    ticker: X\n    start: \"01/2020\"\n    end: \"2020-02-01\"\n    category: regional\n",
        "start_after_end": "scenarios:\n  - id: a\n    name: A\n    ticker: X\n    start: \"2020-03-01\"\n    end: \"2020-02-01\"\n    category: regional\n",
        "dup_id": "scenarios:\n  - id: a\n    name: A\n    ticker: X\n    start: \"2020-01-01\"\n    end: \"2020-02-01\"\n    category: regional\n  - id: a\n    name: B\n    ticker: Y\n    start: \"2020-01-01\"\n    end: \"2020-02-01\"\n    category: regional\n",
        "no_key": "foo: bar\n",
    }
    p = tmp_path / "s.yaml"
    p.write_text(docs[mutate], encoding="utf-8")
    with pytest.raises(ValueError):
        load_scenarios(str(p))


# ──────────────────────────────────────────────────────────────────────────────
# E4 #2 — crash sintético → drawdown
# ──────────────────────────────────────────────────────────────────────────────

def test_synthetic_crash_expected_mdd():
    data, factory = _build([("loss", 0.05), ("loss", 0.05)])
    sc = _scenario_for(data, "crash_linear")
    out = run_scenario(data, sc, {}, strategy_factory=factory)
    assert out["num_trades"] >= 1
    assert out["return_pct"] < 0                 # perdas realizadas
    assert out["mdd_equity_pct"] > 0             # houve drawdown de equity
    assert np.isnan(out["mdd_car_pct"]) or out["mdd_car_pct"] >= 0  # não quebra


# ──────────────────────────────────────────────────────────────────────────────
# E4 #3 — mean-reversion sintético → sistema opera (num_trades > N)
# ──────────────────────────────────────────────────────────────────────────────

def test_synthetic_meanrev_system_trades():
    data, factory = _build([("win", 0.02), ("loss", 0.02), ("win", 0.02), ("loss", 0.02)])
    sc = _scenario_for(data, "mean_reverting_brutal")
    out = run_scenario(data, sc, {}, strategy_factory=factory)
    assert out["num_trades"] >= 2


# ──────────────────────────────────────────────────────────────────────────────
# E4 #4 — bootstrap CI determinístico
# ──────────────────────────────────────────────────────────────────────────────

def test_bootstrap_ci_deterministic_seed():
    # entrada agora = retornos DIÁRIOS da janela (b-coerente); ponto = Sharpe anualizado.
    daily = np.array([0.02, -0.01, 0.03, -0.02, 0.015, 0.01, -0.005, 0.025, -0.012, 0.018])
    a = bootstrap_sharpe_ci(daily, n_samples=500, rng=np.random.default_rng(7))
    b = bootstrap_sharpe_ci(daily, n_samples=500, rng=np.random.default_rng(7))
    assert a == b                                   # mesma seed → idêntico
    lo, pt, hi = a
    assert lo <= pt <= hi                           # ponto (= headline) DENTRO do IC
    assert all(np.isfinite([lo, pt, hi]))
    # < 2 retornos finitos → NaN
    assert all(np.isnan(x) for x in bootstrap_sharpe_ci(np.array([0.01])))


# ──────────────────────────────────────────────────────────────────────────────
# E4 #5 — data_unavailable não quebra; marca a linha
# ──────────────────────────────────────────────────────────────────────────────

def test_data_unavailable_marks_row_no_crash(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(_VALID_YAML, encoding="utf-8")

    def fake_fetch(ticker, start, end):
        return pd.DataFrame({"Close": [1.0, 2.0, 3.0]}), "synthetic"

    df = run_all(yaml_path=str(p), output_dir=str(tmp_path / "out"),
                 base_params={}, fetcher=fake_fetch, make_plots=False)
    assert len(df) == 2
    assert (df["status"] == "data_unavailable").all()
    assert (df["num_trades"] == 0).all()
    assert (tmp_path / "out" / "bears_complete.csv").exists()


# ──────────────────────────────────────────────────────────────────────────────
# E4 #6 — forest plot gera PNG sem erro
# ──────────────────────────────────────────────────────────────────────────────

def test_forest_plot_generates(tmp_path):
    rows = [
        {"scenario_id": "a", "category": "crash_linear",
         "sharpe_ci_point": 0.5, "sharpe_ci_low": 0.2, "sharpe_ci_high": 0.8},
        {"scenario_id": "b", "category": "regional",
         "sharpe_ci_point": -0.3, "sharpe_ci_low": -0.6, "sharpe_ci_high": 0.1},
        {"scenario_id": "c", "category": "mean_reverting_brutal",
         "sharpe_ci_point": 0.1, "sharpe_ci_low": -0.2, "sharpe_ci_high": 0.4},
    ]
    out = tmp_path / "forest.png"
    forest_plot(rows, "sharpe_ci_point", str(out),
                ci_low_key="sharpe_ci_low", ci_high_key="sharpe_ci_high")
    assert out.exists() and out.stat().st_size > 0


# ──────────────────────────────────────────────────────────────────────────────
# Extras (cobertura) — não contam no mínimo 6 da spec
# ──────────────────────────────────────────────────────────────────────────────

def test_classify_status_faixas():
    assert classify_status(0.5, 5.0) == "aprovado"
    assert classify_status(-0.5, 5.0) == "reprovado"
    assert classify_status(0.5, 20.0) == "reprovado"
    assert classify_status(0.5, 12.0) == "inconclusivo"
    assert classify_status(float("nan"), float("nan")) == "inconclusivo"


def test_alpha_vs_bh_two_legs_eval():
    """Alpha = retorno_estrategia(eval) - retorno_B&H(eval), ambas as pernas na janela.
    Estrategia flat (sem sinais) + B&H em alta -> return_pct ~ 0 e alpha < 0."""
    closes = list(np.linspace(100_000.0, 130_000.0, 60))   # B&H sobe ~30%
    data = _series(closes)
    sc = _scenario_for(data, "crash_linear")
    out = run_scenario(data, sc, {}, strategy_factory=lambda d: _MockStrategy(d, []))
    assert out["num_trades"] == 0
    assert abs(out["return_pct"]) < 1e-6           # estrategia ficou flat
    assert out["alpha_vs_bh_pp"] < 0               # ficou de fora da alta do B&H


def test_forex_excluded_from_tally():
    rows = [
        {"scenario_id": "c1", "category": "crash_linear", "status": "aprovado"},
        {"scenario_id": "mrb", "category": "mean_reverting_brutal", "status": "reprovado"},
        {"scenario_id": "fx", "category": "forex", "status": "aprovado"},
        {"scenario_id": "na", "category": "regional", "status": "data_unavailable"},
    ]
    cov = summarize_coverage(rows)
    assert cov["executed"] == 3                       # exclui data_unavailable
    assert cov["mean_reverting_brutal_present"] is True
    assert "fx" in cov["forex"]
    assert cov["tally_core"]["aprovado"] == 1         # forex 'aprovado' NÃO entra
    assert cov["tally_core"]["reprovado"] == 1


def test_run_all_end_to_end_offline(tmp_path):
    """run_all completo offline: fetcher+factory injetados → CSV + 5 plots."""
    data, factory = _build([("win", 0.02), ("loss", 0.02)] * 3 + [("win", 0.02)])
    d0, d1 = str(data.index[0].date()), str(data.index[-1].date())
    yaml_txt = (
        "scenarios:\n"
        f"  - id: x\n    name: X\n    ticker: MOCK\n    start: \"{d0}\"\n"
        f"    end: \"{d1}\"\n    category: mean_reverting_brutal\n"
        f"  - id: f\n    name: F\n    ticker: MOCK\n    start: \"{d0}\"\n"
        f"    end: \"{d1}\"\n    category: forex\n"
    )
    p = tmp_path / "s.yaml"
    p.write_text(yaml_txt, encoding="utf-8")

    def fetch(ticker, start, end):
        return data.copy(), "yfinance"

    out_dir = tmp_path / "out"
    df = run_all(yaml_path=str(p), output_dir=str(out_dir), base_params={},
                 fetcher=fetch, strategy_factory=factory, n_bootstrap=100, make_plots=True)
    assert list(df.columns) == CSV_COLUMNS
    assert len(df) == 2
    assert (out_dir / "bears_complete.csv").exists()
    assert (out_dir / "plots" / "forest_sharpe.png").exists()
    assert (out_dir / "plots" / "category_medians.png").exists()
    cov = summarize_coverage(df.to_dict("records"))
    assert cov["executed"] == 2
    assert "f" in cov["forex"]


if __name__ == "__main__":   # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
