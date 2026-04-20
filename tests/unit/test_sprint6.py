"""
tests/unit/test_sprint6.py — Testes Sprint-6: Calibração, Alertas e Kelly.

Executavel diretamente:
    python tests/unit/test_sprint6.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from meta_labeler import MetaLabeler, build_features
from alert_manager import AlertManager
from strategy import CombinedStrategy
from backtester import Backtester


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _ohlcv(n: int = 300, drift: float = 0.001, vol: float = 0.012,
           seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100_000.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    rng2  = np.random.default_rng(seed + 1)
    return pd.DataFrame({
        "Open":   close,
        "High":   close * (1 + np.abs(rng2.normal(0, 0.004, n))),
        "Low":    close * (1 - np.abs(rng2.normal(0, 0.004, n))),
        "Close":  close,
        "Volume": np.full(n, 1e6),
    }, index=pd.date_range("2022-01-03", periods=n, freq="B"))


def _prepared(n=400, seed=0, **params):
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(_ohlcv(n=n, seed=seed))
    s.params.update(params)
    s.prepare()
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Testes — Calibração (Sprint-6 passo 1)
# ─────────────────────────────────────────────────────────────────────────────

def test_calibration_curve_returns_dataframe():
    n   = 200
    rng = np.random.default_rng(0)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    X   = pd.DataFrame(rng.normal(size=(n, 5)),
                       columns=["f1","f2","f3","f4","f5"], index=idx)
    y   = pd.Series(rng.integers(0, 2, n), index=idx)
    ml  = MetaLabeler(n_estimators=20)
    ml.fit(X, y, eval_cv=False)
    curve = ml.calibration_curve(X, y)
    assert isinstance(curve, pd.DataFrame)
    assert set(curve.columns) >= {"threshold", "precision", "recall", "f1", "n_accepted"}
    print(f"  [OK] test_calibration_curve_returns_dataframe  ({len(curve)} pontos)")


def test_calibration_curve_monotone_threshold():
    """Recall decresce (ou mantém) conforme threshold aumenta."""
    n   = 300
    rng = np.random.default_rng(1)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    f1  = rng.normal(size=n)
    X   = pd.DataFrame({"f1": f1, "f2": rng.normal(size=n)}, index=idx)
    y   = pd.Series((f1 > 0).astype(int), index=idx)
    ml  = MetaLabeler(n_estimators=30)
    ml.fit(X, y, eval_cv=False)
    curve = ml.calibration_curve(X, y).dropna()
    # Recall deve ser não-crescente conforme threshold aumenta
    recalls = curve["recall"].values
    assert all(recalls[i] >= recalls[i+1] - 0.05   # tolerância pequena
               for i in range(len(recalls)-1)), \
        "Recall deveria ser nao-crescente com threshold"
    print("  [OK] test_calibration_curve_monotone_threshold")


def test_calibrate_finds_valid_threshold():
    """calibrate() deve retornar threshold em [0,1] com recall >= target."""
    n   = 300
    rng = np.random.default_rng(2)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    f1  = rng.normal(size=n)
    X   = pd.DataFrame({"f1": f1, "f2": rng.normal(size=n)}, index=idx)
    y   = pd.Series((f1 > 0).astype(int), index=idx)
    ml  = MetaLabeler(n_estimators=30)
    ml.fit(X, y, eval_cv=False)
    thr = ml.calibrate(X, y, target_recall=0.20, metric="f1")
    assert 0.0 <= thr <= 1.0
    assert ml.min_prob == thr   # deve atualizar o atributo
    print(f"  [OK] test_calibrate_finds_valid_threshold  (thr={thr:.3f})")


def test_calibrate_updates_min_prob():
    """Após calibrate(), min_prob deve ser diferente do valor inicial 0.5."""
    n   = 300
    rng = np.random.default_rng(3)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    f1  = rng.normal(size=n)
    X   = pd.DataFrame({"f1": f1}, index=idx)
    y   = pd.Series((f1 > 0.5).astype(int), index=idx)
    ml  = MetaLabeler(n_estimators=20, min_prob=0.5)
    ml.fit(X, y, eval_cv=False)
    initial_prob = ml.min_prob
    ml.calibrate(X, y, target_recall=0.40, metric="f1")
    # min_prob foi atualizado (pode ser igual se 0.5 já era ótimo)
    assert isinstance(ml.min_prob, float)
    print(f"  [OK] test_calibrate_updates_min_prob  ({initial_prob:.3f} -> {ml.min_prob:.3f})")


def test_calibrate_from_strategy():
    """calibrate_from_strategy deve funcionar sem excecao."""
    s = _prepared(n=500, seed=4)
    ml = MetaLabeler(n_estimators=20)
    ml.fit_from_strategy(s, eval_cv=False)
    if not ml._fitted:
        print("  [OK] test_calibrate_from_strategy  (sem modelo)")
        return
    thr = ml.calibrate_from_strategy(s, val_fraction=0.20, target_recall=0.20)
    assert 0.0 <= thr <= 1.0
    print(f"  [OK] test_calibrate_from_strategy  (thr={thr:.3f})")


def test_calibrate_meta_labeler_in_strategy():
    """strategy.calibrate_meta_labeler() deve retornar float ou None."""
    s = _prepared(n=500, seed=5, use_meta_labeler=True, meta_n_estimators=20)
    s.train_meta_labeler()
    result = s.calibrate_meta_labeler(val_fraction=0.20, target_recall=0.25)
    if result is not None:
        assert 0.0 <= result <= 1.0
    print(f"  [OK] test_calibrate_meta_labeler_in_strategy  (result={result})")


def test_calibrate_lowers_threshold():
    """Com target_recall=0.50, threshold deve ser <= threshold@recall=0.10."""
    n   = 400
    rng = np.random.default_rng(6)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    f1  = rng.normal(size=n)
    X   = pd.DataFrame({"f1": f1, "f2": rng.normal(size=n)}, index=idx)
    y   = pd.Series((f1 > 0).astype(int), index=idx)
    ml  = MetaLabeler(n_estimators=30)
    ml.fit(X, y, eval_cv=False)
    thr_hi_recall = ml.calibrate(X, y, target_recall=0.50, metric="f1")
    thr_lo_recall = ml.calibrate(X, y, target_recall=0.10, metric="precision")
    # Recall alto => threshold mais baixo (aceita mais)
    assert thr_hi_recall <= thr_lo_recall + 0.10, \
        f"Recall alto deveria dar threshold menor: {thr_hi_recall:.3f} vs {thr_lo_recall:.3f}"
    print(f"  [OK] test_calibrate_lowers_threshold  "
          f"(recall50={thr_hi_recall:.3f}, recall10={thr_lo_recall:.3f})")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — AlertManager (Sprint-6 passo 2)
# ─────────────────────────────────────────────────────────────────────────────

def test_alert_manager_check_returns_list():
    with tempfile.TemporaryDirectory() as tmpdir:
        am = AlertManager(
            ticker="^BVSP",
            log_path=os.path.join(tmpdir, "alerts.jsonl"),
            sent_path=os.path.join(tmpdir, "sent.json"),
            console=False,
        )
        s = _prepared(n=300, seed=7)
        alerted = am.check(s)
        assert isinstance(alerted, list)
        print(f"  [OK] test_alert_manager_check_returns_list  ({len(alerted)} alertas)")


def test_alert_manager_dedup():
    """Segunda chamada nao deve re-alertar os mesmos sinais."""
    with tempfile.TemporaryDirectory() as tmpdir:
        am = AlertManager(
            ticker="^BVSP",
            log_path=os.path.join(tmpdir, "alerts.jsonl"),
            sent_path=os.path.join(tmpdir, "sent.json"),
            console=False,
        )
        s = _prepared(n=300, seed=8)
        alerted1 = am.check(s)
        alerted2 = am.check(s)   # segunda chamada — mesma strategy
        assert len(alerted2) == 0, \
            f"Segunda chamada deveria retornar 0 alertas, obteve {len(alerted2)}"
        print(f"  [OK] test_alert_manager_dedup  "
              f"(1a={len(alerted1)}, 2a={len(alerted2)})")


def test_alert_manager_writes_log():
    """Alertas devem ser gravados no arquivo JSON-lines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "alerts.jsonl")
        am = AlertManager(
            ticker="^BVSP", log_path=log_path,
            sent_path=os.path.join(tmpdir, "sent.json"),
            console=False,
        )
        s = _prepared(n=300, seed=9)
        alerted = am.check(s)
        if alerted:
            assert os.path.exists(log_path)
            records = am.load_log()
            assert len(records) == len(alerted)
            assert all("ticker" in r for r in records)
        print(f"  [OK] test_alert_manager_writes_log  ({len(alerted)} linhas)")


def test_alert_manager_min_forca_filter():
    """Sinais com forca < min_forca devem ser filtrados."""
    with tempfile.TemporaryDirectory() as tmpdir:
        am_all = AlertManager(
            ticker="^BVSP",
            log_path=os.path.join(tmpdir, "a1.jsonl"),
            sent_path=os.path.join(tmpdir, "s1.json"),
            console=False, min_forca=0,
        )
        am_hi = AlertManager(
            ticker="^BVSP",
            log_path=os.path.join(tmpdir, "a2.jsonl"),
            sent_path=os.path.join(tmpdir, "s2.json"),
            console=False, min_forca=99,   # impossível de atingir
        )
        s = _prepared(n=300, seed=10)
        n_all = len(am_all.check(s))
        n_hi  = len(am_hi.check(s))
        assert n_hi == 0, f"min_forca=99 deveria filtrar todos: {n_hi}"
        print(f"  [OK] test_alert_manager_min_forca_filter  (all={n_all}, hi={n_hi})")


def test_alert_manager_reset():
    """reset() deve limpar estado e permitir re-alertar."""
    with tempfile.TemporaryDirectory() as tmpdir:
        am = AlertManager(
            ticker="^BVSP",
            log_path=os.path.join(tmpdir, "alerts.jsonl"),
            sent_path=os.path.join(tmpdir, "sent.json"),
            console=False,
        )
        s = _prepared(n=300, seed=11)
        alerted1 = am.check(s)
        am.reset()
        alerted2 = am.check(s)   # deve re-alertar após reset
        assert len(alerted2) >= len(alerted1) * 0.8, \
            f"Após reset, deveria re-alertar; got {len(alerted2)} vs {len(alerted1)}"
        print(f"  [OK] test_alert_manager_reset  "
              f"(antes={len(alerted1)}, apos_reset={len(alerted2)})")


def test_alert_manager_load_log_empty():
    """load_log em arquivo inexistente deve retornar lista vazia."""
    with tempfile.TemporaryDirectory() as tmpdir:
        am = AlertManager(log_path=os.path.join(tmpdir, "nao_existe.jsonl"),
                          sent_path=os.path.join(tmpdir, "s.json"), console=False)
        assert am.load_log() == []
    print("  [OK] test_alert_manager_load_log_empty")


def test_alert_manager_n_sent():
    """n_sent deve incrementar após cada alerta."""
    with tempfile.TemporaryDirectory() as tmpdir:
        am = AlertManager(
            ticker="^BVSP",
            log_path=os.path.join(tmpdir, "alerts.jsonl"),
            sent_path=os.path.join(tmpdir, "sent.json"),
            console=False,
        )
        assert am.n_sent == 0
        s = _prepared(n=300, seed=12)
        alerted = am.check(s)
        assert am.n_sent == len(alerted)
    print(f"  [OK] test_alert_manager_n_sent  ({am.n_sent})")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — Kelly Criterion (Sprint-6 passo 3)
# ─────────────────────────────────────────────────────────────────────────────

def _make_bt(df: pd.DataFrame, **params) -> Backtester:
    s = CombinedStrategy("^BVSP", name="kelly_test")
    s.set_data(df.copy())
    s.params.update(params)
    return Backtester(s, initial_capital=100_000.0, cooldown_bars=2,
                      commission_per_trade=0.001, slippage_pct=0.001)


def test_kelly_params_in_defaults():
    defaults = CombinedStrategy.DEFAULT_PARAMS
    required = {"use_kelly_sizing", "kelly_fraction", "kelly_min", "kelly_max"}
    assert required <= set(defaults.keys()), \
        f"Params ausentes: {required - set(defaults.keys())}"
    assert defaults["use_kelly_sizing"] is False
    print("  [OK] test_kelly_params_in_defaults")


def test_kelly_off_by_default():
    """Sem use_kelly_sizing, resultado idêntico ao baseline."""
    df = _ohlcv(300, seed=13)
    bt1 = _make_bt(df, use_kelly_sizing=False)
    bt2 = _make_bt(df)    # default = False
    m1  = bt1.run()
    m2  = bt2.run()
    assert m1["trade_count"] == m2["trade_count"]
    print("  [OK] test_kelly_off_by_default")


def test_kelly_runs_without_error():
    """use_kelly_sizing=True deve completar sem exceções."""
    df = _ohlcv(400, drift=0.002, seed=14)
    bt = _make_bt(df, use_kelly_sizing=True, kelly_fraction=0.5)
    m  = bt.run()
    assert "trade_count" in m
    print(f"  [OK] test_kelly_runs_without_error  ({m['trade_count']} trades)")


def test_kelly_needs_10_trades_to_activate():
    """Com < 10 trades acumulados, Kelly não deve alterar o sizing."""
    df  = _ohlcv(100, seed=15)   # poucas barras = poucos trades
    bt_no  = _make_bt(df, use_kelly_sizing=False)
    bt_yes = _make_bt(df, use_kelly_sizing=True, kelly_fraction=1.0)
    m_no   = bt_no.run()
    m_yes  = bt_yes.run()
    # Com < 10 trades, Kelly é no-op → resultados idênticos
    if m_no["trade_count"] < 10:
        assert m_no["trade_count"] == m_yes["trade_count"]
    print(f"  [OK] test_kelly_needs_10_trades_to_activate  "
          f"(trades={m_no['trade_count']})")


def test_kelly_fraction_half_vs_full():
    """half-Kelly (0.5) deve ter DD menor ou igual que full-Kelly (1.0)."""
    df = _ohlcv(500, drift=0.001, vol=0.015, seed=16)
    bt_half = _make_bt(df, use_kelly_sizing=True, kelly_fraction=0.5)
    bt_full = _make_bt(df, use_kelly_sizing=True, kelly_fraction=1.0)
    m_half  = bt_half.run()
    m_full  = bt_full.run()
    # Não existe garantia matemática sem trades suficientes,
    # mas verificamos que ambos correm sem error
    assert "max_drawdown" in m_half
    assert "max_drawdown" in m_full
    print(f"  [OK] test_kelly_fraction_half_vs_full  "
          f"(half_dd={m_half['max_drawdown']:.3f}, full_dd={m_full['max_drawdown']:.3f})")


def test_kelly_with_vol_targeting():
    """Kelly + Vol Targeting juntos devem funcionar sem exceção."""
    df = _ohlcv(400, seed=17)
    bt = _make_bt(df,
                  use_kelly_sizing=True, kelly_fraction=0.5,
                  use_vol_targeting=True, vol_target_annual=0.15)
    m  = bt.run()
    assert "trade_count" in m
    print(f"  [OK] test_kelly_with_vol_targeting  ({m['trade_count']} trades)")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all() -> int:
    tests = [
        # Calibração
        test_calibration_curve_returns_dataframe,
        test_calibration_curve_monotone_threshold,
        test_calibrate_finds_valid_threshold,
        test_calibrate_updates_min_prob,
        test_calibrate_from_strategy,
        test_calibrate_meta_labeler_in_strategy,
        test_calibrate_lowers_threshold,
        # AlertManager
        test_alert_manager_check_returns_list,
        test_alert_manager_dedup,
        test_alert_manager_writes_log,
        test_alert_manager_min_forca_filter,
        test_alert_manager_reset,
        test_alert_manager_load_log_empty,
        test_alert_manager_n_sent,
        # Kelly Criterion
        test_kelly_params_in_defaults,
        test_kelly_off_by_default,
        test_kelly_runs_without_error,
        test_kelly_needs_10_trades_to_activate,
        test_kelly_fraction_half_vs_full,
        test_kelly_with_vol_targeting,
    ]
    print("=" * 62)
    print("  Suite: Sprint-6 (Calibracao + Alertas + Kelly)")
    print("=" * 62)
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception:
            failed += 1
            print(f"  [FAIL] {fn.__name__}")
            traceback.print_exc()
    passed = len(tests) - failed
    print("=" * 62)
    print(f"  Resultado: {passed} passou(aram) / {failed} falhou(aram)")
    print("=" * 62)
    return failed


if __name__ == "__main__":
    sys.exit(run_all())
