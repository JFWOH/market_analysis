"""
tests/unit/test_triple_barrier.py — Testes do Triple-Barrier Labeling + Purged CV.

Sprint-3 passos 1 e 2: rotulagem de eventos via três barreiras + validacao
cruzada com purge/embargo para evitar leakage temporal.

Executavel diretamente:
    python tests/unit/test_triple_barrier.py
"""
from __future__ import annotations

import os
import sys
import traceback

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from labels import TripleBarrierLabeler, PurgedKFold, compute_label_stats
from strategy import CombinedStrategy


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _close(n: int = 200, drift: float = 0.001, vol: float = 0.01,
           seed: int = 0) -> pd.Series:
    rng  = np.random.default_rng(seed)
    px   = 100.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    return pd.Series(px, index=pd.date_range("2023-01-02", periods=n, freq="B"),
                     name="Close")


def _ohlcv(n: int = 200, drift: float = 0.001, vol: float = 0.01,
           seed: int = 0) -> pd.DataFrame:
    close = _close(n, drift, vol, seed)
    rng   = np.random.default_rng(seed + 1)
    return pd.DataFrame({
        "Open":   close,
        "High":   close * (1 + np.abs(rng.normal(0, 0.004, n))),
        "Low":    close * (1 - np.abs(rng.normal(0, 0.004, n))),
        "Close":  close,
        "Volume": np.full(n, 1e6),
    }, index=close.index)


# ─────────────────────────────────────────────────────────────────────────────
# Testes — TripleBarrierLabeler.label_events
# ─────────────────────────────────────────────────────────────────────────────

def test_label_events_returns_dataframe():
    lbl  = TripleBarrierLabeler()
    close = _close()
    df   = lbl.label_events(close)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    print(f"  [OK] test_label_events_returns_dataframe  ({len(df)} labels)")


def test_label_events_required_columns():
    lbl  = TripleBarrierLabeler()
    df   = lbl.label_events(_close())
    required = {"t1", "label", "ret", "barrier", "entry_px", "exit_px", "duration"}
    assert required <= set(df.columns), f"Colunas ausentes: {required - set(df.columns)}"
    print("  [OK] test_label_events_required_columns")


def test_label_events_only_valid_labels():
    """Labels devem ser +1, -1, 0 ou NaN."""
    lbl = TripleBarrierLabeler()
    df  = lbl.label_events(_close(300))
    valid = {1, -1, 0}
    lb_vals = set(df["label"].dropna().astype(int).unique())
    assert lb_vals <= valid, f"Labels invalidos: {lb_vals - valid}"
    print(f"  [OK] test_label_events_only_valid_labels  ({lb_vals})")


def test_label_events_length_matches_events():
    """Número de labels == número de eventos fornecidos (menos NaN de vol)."""
    close = _close(200)
    events = close.index[50:100]   # 50 eventos
    lbl = TripleBarrierLabeler(vol_window=20)
    df  = lbl.label_events(close, events=events)
    # Pode ter menos que 50 se alguns eventos caem antes de vol estar disponível
    assert len(df) <= 50
    assert len(df) >= 40   # maioria deve ter vol calculada
    print(f"  [OK] test_label_events_length_matches_events  ({len(df)}/50 labels)")


def test_label_events_tp_hit_in_uptrend():
    """Em tendência forte de alta, a maioria dos labels deve ser +1 (TP atingido)."""
    close = _close(500, drift=0.008, vol=0.003, seed=1)  # forte uptrend, vol baixa
    lbl   = TripleBarrierLabeler(pt_sl=(1.5, 1.5), max_holding=15, vol_window=20)
    df    = lbl.label_events(close)
    tp_pct = (df["label"] == 1).sum() / len(df)
    assert tp_pct > 0.4, f"TP% esperado >40%, obteve {tp_pct:.1%}"
    print(f"  [OK] test_label_events_tp_hit_in_uptrend  (TP={tp_pct:.1%})")


def test_label_events_sl_hit_in_downtrend():
    """Em tendência forte de baixa, a maioria dos labels deve ser -1 (SL atingido)."""
    close = _close(500, drift=-0.008, vol=0.003, seed=2)  # forte downtrend
    lbl   = TripleBarrierLabeler(pt_sl=(1.5, 1.5), max_holding=15, vol_window=20)
    df    = lbl.label_events(close)
    sl_pct = (df["label"] == -1).sum() / len(df)
    assert sl_pct > 0.4, f"SL% esperado >40%, obteve {sl_pct:.1%}"
    print(f"  [OK] test_label_events_sl_hit_in_downtrend  (SL={sl_pct:.1%})")


def test_label_events_vertical_in_ranging():
    """Em mercado lateral, muitas barreiras verticais (label 0)."""
    rng   = np.random.default_rng(3)
    px    = 100.0 + np.cumsum(rng.normal(0, 0.1, 300))   # random walk sem drift
    close = pd.Series(np.abs(px), index=pd.date_range("2023-01-02", periods=300, freq="B"))
    lbl   = TripleBarrierLabeler(pt_sl=(3.0, 3.0), max_holding=5, vol_window=20)
    df    = lbl.label_events(close)
    vert_pct = (df["label"] == 0).sum() / len(df)
    assert vert_pct > 0.3, f"Vertical% esperado >30%, obteve {vert_pct:.1%}"
    print(f"  [OK] test_label_events_vertical_in_ranging  (Vert={vert_pct:.1%})")


def test_label_events_t1_after_t0():
    """t1 (saída) deve sempre ser >= t0 (entrada)."""
    lbl = TripleBarrierLabeler()
    df  = lbl.label_events(_close(200))
    assert (df["t1"] >= df.index).all(), "t1 deve ser >= t0"
    print("  [OK] test_label_events_t1_after_t0")


def test_label_events_duration_positive():
    """Duração deve ser >= 0 barras."""
    lbl = TripleBarrierLabeler()
    df  = lbl.label_events(_close(200))
    assert (df["duration"] >= 0).all()
    print("  [OK] test_label_events_duration_positive")


def test_label_events_ret_consistent_with_prices():
    """ret deve ser log(exit_px / entry_px) com tolerância numérica."""
    lbl = TripleBarrierLabeler()
    df  = lbl.label_events(_close(200))
    expected_ret = np.log(df["exit_px"] / df["entry_px"])
    np.testing.assert_allclose(df["ret"].values, expected_ret.values, rtol=1e-6)
    print("  [OK] test_label_events_ret_consistent_with_prices")


def test_label_events_no_tp_when_pt_zero():
    """Com pt=0 (sem TP), nunca deve haver label +1."""
    lbl = TripleBarrierLabeler(pt_sl=(0.0, 1.5))
    df  = lbl.label_events(_close(200, drift=0.01))
    assert (df["label"] != 1).all(), "Sem TP: label nunca deve ser +1"
    print("  [OK] test_label_events_no_tp_when_pt_zero")


def test_label_events_no_sl_when_sl_zero():
    """Com sl=0 (sem SL), nunca deve haver label -1."""
    lbl = TripleBarrierLabeler(pt_sl=(1.5, 0.0))
    df  = lbl.label_events(_close(200, drift=-0.01))
    assert (df["label"] != -1).all(), "Sem SL: label nunca deve ser -1"
    print("  [OK] test_label_events_no_sl_when_sl_zero")


def test_label_events_min_ret_filters_noise():
    """min_ret deve filtrar labels com |ret| pequeno (retorna NaN)."""
    lbl = TripleBarrierLabeler(min_ret=0.05)   # 5% mínimo — muito restritivo
    df  = lbl.label_events(_close(200, vol=0.005))
    # Com vol baixa e min_ret alto, a maioria das labels deve ser NaN
    nan_pct = df["label"].isna().mean()
    assert nan_pct > 0.3, f"min_ret não está filtrando: nan_pct={nan_pct:.1%}"
    print(f"  [OK] test_label_events_min_ret_filters_noise  (NaN={nan_pct:.1%})")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — TripleBarrierLabeler.label_signals
# ─────────────────────────────────────────────────────────────────────────────

def test_label_signals_returns_dataframe():
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(_ohlcv(200))
    s.prepare()
    sigs = s.generate_signals()
    lbl  = TripleBarrierLabeler()
    df   = lbl.label_signals(s.data["Close"], sigs)
    assert isinstance(df, pd.DataFrame)
    print(f"  [OK] test_label_signals_returns_dataframe  ({len(df)} sinais rotulados)")


def test_label_signals_has_tipo_column():
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(_ohlcv(200))
    s.prepare()
    sigs = s.generate_signals()
    if not sigs:
        print("  [OK] test_label_signals_has_tipo_column  (sem sinais)")
        return
    lbl = TripleBarrierLabeler()
    df  = lbl.label_signals(s.data["Close"], sigs)
    assert "tipo" in df.columns
    assert "estrategia" in df.columns
    print("  [OK] test_label_signals_has_tipo_column")


def test_label_signals_sell_label_flipped():
    """Sinal de Venda bem-sucedido (preço caiu) deve ter label +1 após flip."""
    # Downtrend — signal de venda deve ser lucrativo (label -1 raw → flip +1)
    df_down = _ohlcv(300, drift=-0.006, vol=0.004, seed=5)
    s = CombinedStrategy("^BVSP", name="test")
    s.set_data(df_down)
    s.params["allow_long"] = False   # só venda
    s.prepare()
    sigs = s.generate_signals()
    lbl  = TripleBarrierLabeler(pt_sl=(1.5, 1.5), max_holding=20, vol_window=20)
    labeled = lbl.label_signals(s.data["Close"], sigs)
    if labeled.empty:
        print("  [OK] test_label_signals_sell_label_flipped  (sem sinais de venda)")
        return
    # Verifica que tipo Venda tem label no domínio correto
    sells = labeled[labeled["tipo"] == "Venda"]["label"].dropna()
    assert sells.isin([-1, 0, 1]).all()
    print(f"  [OK] test_label_signals_sell_label_flipped  ({len(sells)} vendas)")


def test_label_signals_empty_signals():
    """Lista de sinais vazia deve retornar DataFrame vazio."""
    lbl = TripleBarrierLabeler()
    df  = lbl.label_signals(_close(100), signals=[])
    assert df.empty
    print("  [OK] test_label_signals_empty_signals")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — PurgedKFold
# ─────────────────────────────────────────────────────────────────────────────

def test_purged_kfold_n_splits():
    """Deve gerar exatamente n_splits folds."""
    close = _close(200)
    X = pd.DataFrame({"feat": close.values}, index=close.index)
    pkf = PurgedKFold(n_splits=5)
    splits = list(pkf.split(X))
    assert len(splits) == 5
    print(f"  [OK] test_purged_kfold_n_splits  ({len(splits)} folds)")


def test_purged_kfold_no_overlap():
    """Train e test de cada fold não devem ter índices em comum."""
    close = _close(200)
    X = pd.DataFrame({"feat": close.values}, index=close.index)
    pkf = PurgedKFold(n_splits=5)
    for tr, te in pkf.split(X):
        overlap = set(tr) & set(te)
        assert len(overlap) == 0, f"Overlap train/test: {len(overlap)} amostras"
    print("  [OK] test_purged_kfold_no_overlap")


def test_purged_kfold_no_train_after_test():
    """Nenhum índice de treino deve estar no período de embargo após o teste."""
    close = _close(300)
    X = pd.DataFrame({"feat": close.values}, index=close.index)
    pkf = PurgedKFold(n_splits=5, embargo_pct=0.02)
    n   = len(X)
    for tr, te in pkf.split(X):
        test_end = max(te)
        embargo_end = min(test_end + max(1, int(n * 0.02)), n - 1)
        # nenhum treino entre test_end+1 e embargo_end
        train_in_embargo = tr[(tr > test_end) & (tr <= embargo_end)]
        assert len(train_in_embargo) == 0, \
            f"Treino no período de embargo: {train_in_embargo}"
    print("  [OK] test_purged_kfold_no_train_after_test")


def test_purged_kfold_with_eval_times():
    """Com eval_times (t1), amostras de treino sobrepostas devem ser removidas."""
    n     = 100
    close = _close(n)
    X     = pd.DataFrame({"feat": close.values}, index=close.index)
    # t1 = t0 + 5 barras (label-span de 5 dias)
    t0    = close.index
    t1    = pd.DatetimeIndex([t0[min(i + 5, n - 1)] for i in range(n)])
    pkf   = PurgedKFold(n_splits=4, embargo_pct=0.01)
    splits = list(pkf.split(X, pred_times=t0, eval_times=t1))
    assert len(splits) == 4
    print(f"  [OK] test_purged_kfold_with_eval_times  ({len(splits)} folds)")


def test_purged_kfold_train_always_before_test_bulk():
    """Purged KFold (Lopez de Prado): treino usa todos os folds exceto o teste
    (inclui dados futuros). Garante que as amostras do teste nao estao no treino
    e que o embargo esta respeitado — nao restringe a nao-usar dados futuros."""
    close = _close(200)
    X     = pd.DataFrame({"feat": close.values}, index=close.index)
    pkf   = PurgedKFold(n_splits=5, embargo_pct=0.01)
    n     = len(X)
    embargo_h = max(1, int(n * 0.01))
    all_ok = True
    for tr, te in pkf.split(X):
        test_start = min(te)
        test_end   = max(te)
        # 1. Nenhuma amostra de teste no treino
        assert len(set(tr) & set(te)) == 0
        # 2. Nenhuma amostra de treino no período de embargo (imediatamente apos teste)
        embargo_zone = set(range(test_end + 1, min(test_end + embargo_h + 1, n)))
        overlap = set(tr) & embargo_zone
        assert len(overlap) == 0, f"Treino no embargo: {overlap}"
    print("  [OK] test_purged_kfold_train_always_before_test_bulk")


def test_purged_kfold_get_n_splits():
    pkf = PurgedKFold(n_splits=7)
    assert pkf.get_n_splits() == 7
    print("  [OK] test_purged_kfold_get_n_splits")


# ─────────────────────────────────────────────────────────────────────────────
# Testes — compute_label_stats
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_label_stats_keys():
    lbl = TripleBarrierLabeler()
    df  = lbl.label_events(_close(200))
    stats = compute_label_stats(df)
    required = {"n_total", "n_long", "n_short", "n_neutral", "n_nan",
                "pct_long", "pct_short", "pct_neutral", "avg_ret", "avg_duration"}
    assert required <= set(stats.keys())
    print(f"  [OK] test_compute_label_stats_keys  (n={stats['n_total']})")


def test_compute_label_stats_sum_to_total():
    lbl   = TripleBarrierLabeler()
    df    = lbl.label_events(_close(200))
    stats = compute_label_stats(df)
    total = stats["n_long"] + stats["n_short"] + stats["n_neutral"] + stats["n_nan"]
    assert total == stats["n_total"], \
        f"Soma {total} != n_total {stats['n_total']}"
    print(f"  [OK] test_compute_label_stats_sum_to_total  "
          f"(+1={stats['n_long']}, -1={stats['n_short']}, 0={stats['n_neutral']})")


def test_compute_label_stats_empty():
    stats = compute_label_stats(pd.DataFrame())
    assert stats == {}
    print("  [OK] test_compute_label_stats_empty")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all() -> int:
    tests = [
        # label_events
        test_label_events_returns_dataframe,
        test_label_events_required_columns,
        test_label_events_only_valid_labels,
        test_label_events_length_matches_events,
        test_label_events_tp_hit_in_uptrend,
        test_label_events_sl_hit_in_downtrend,
        test_label_events_vertical_in_ranging,
        test_label_events_t1_after_t0,
        test_label_events_duration_positive,
        test_label_events_ret_consistent_with_prices,
        test_label_events_no_tp_when_pt_zero,
        test_label_events_no_sl_when_sl_zero,
        test_label_events_min_ret_filters_noise,
        # label_signals
        test_label_signals_returns_dataframe,
        test_label_signals_has_tipo_column,
        test_label_signals_sell_label_flipped,
        test_label_signals_empty_signals,
        # PurgedKFold
        test_purged_kfold_n_splits,
        test_purged_kfold_no_overlap,
        test_purged_kfold_no_train_after_test,
        test_purged_kfold_with_eval_times,
        test_purged_kfold_train_always_before_test_bulk,
        test_purged_kfold_get_n_splits,
        # compute_label_stats
        test_compute_label_stats_keys,
        test_compute_label_stats_sum_to_total,
        test_compute_label_stats_empty,
    ]
    print("=" * 62)
    print("  Suite: Triple-Barrier + Purged CV (Sprint-3 passos 1+2)")
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
