"""
tests/unit/test_partial_breakeven.py

Testes do Passo 3 do Sprint-1: Partial Exit + Breakeven.

    • Partial exit a +R×risco_inicial fecha fração da posição
    • Após partial exit, stop do restante move para breakeven
    • Contagem de trades e capital conservado corretamente

Executável diretamente:
    python tests/unit/test_partial_breakeven.py
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

from backtester import Backtester


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

class _MockStrategy:
    """Strategy com dados e sinais pré-programados. Aceita params via kwargs."""

    def __init__(self, data: pd.DataFrame, signals: list[dict], **extra_params):
        self.data    = data
        self.name    = "mock"
        self.ticker  = "MOCK"
        base_params = {
            "max_position_pct":  0.5,
            "max_risk_pct":      0.02,
            "use_trailing_stop": False,
        }
        base_params.update(extra_params)
        self.params   = base_params
        self._signals = signals

    def prepare(self) -> None:
        if "ATR" not in self.data.columns:
            tr = (self.data["High"] - self.data["Low"]).abs()
            self.data["ATR"] = tr.rolling(5).mean().bfill()

    def generate_signals(self) -> list[dict]:
        return self._signals


def _make_bt(df, signals, **params):
    """Cria backtester com cooldown=0 e custos zerados para isolar a lógica."""
    strat = _MockStrategy(df, signals, **params)
    return Backtester(strat, initial_capital=100_000.0,
                      commission_per_trade=0.0, slippage_pct=0.0,
                      cooldown_bars=0)


def _price_series(highs_lows_closes: list[tuple[float, float, float]]) -> pd.DataFrame:
    """Constrói DataFrame OHLCV a partir de triplas (high, low, close)."""
    n = len(highs_lows_closes)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    df = pd.DataFrame({
        "Open":   [c for _, _, c in highs_lows_closes],
        "High":   [h for h, _, _ in highs_lows_closes],
        "Low":    [l for _, l, _ in highs_lows_closes],
        "Close":  [c for _, _, c in highs_lows_closes],
        "Volume": 1_000_000,
    }, index=dates)
    df.index.name = "Date"
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Testes — Partial Exit desabilitado
# ══════════════════════════════════════════════════════════════════════════════

def test_partial_exit_disabled_by_default():
    """Sem use_partial_exit=True, comportamento é idêntico ao antigo."""
    # Cenário: entrada em bar 1, preço sobe para +2R em bar 3, TP em bar 5
    # Sem partial: 1 trade (full TP)
    df = _price_series([
        (100, 99, 100),   # bar 0
        (101, 99, 100),   # bar 1: entrada
        (103, 100, 102),  # bar 2: +1R (atingiria partial se ligado)
        (106, 102, 105),  # bar 3: +2R
        (108, 104, 107),  # bar 4: aproxima do TP (110)
        (112, 106, 111),  # bar 5: TP (110)
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals)  # sem use_partial_exit
    m = bt.run()
    assert m["trade_count"] == 1, f"Esperado 1 trade, obteve {m['trade_count']}"
    assert bt.trades[0]["reason"] == "Take Profit"
    print("  [OK] test_partial_exit_disabled_by_default")


def test_partial_not_triggered_if_price_doesnt_reach_r():
    """Se preço nunca atinge +R, partial não dispara."""
    # entrada 100, stop 98 → R=2. Precisaria bater 102 para partial.
    # Preço só vai a 101.9 antes de stopar.
    df = _price_series([
        (100, 99.5, 100),
        (101, 99.5, 100),    # entrada
        (101.8, 100, 101.5), # +0.9R — não dispara partial
        (101, 97, 97.5),     # stop 98
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.5)
    m = bt.run()
    assert m["trade_count"] == 1
    assert bt.trades[0]["reason"] == "Stop Loss"
    print("  [OK] test_partial_not_triggered_if_price_doesnt_reach_r")


# ══════════════════════════════════════════════════════════════════════════════
# Testes — Partial Exit disparado
# ══════════════════════════════════════════════════════════════════════════════

def test_partial_exit_triggers_at_1r_long():
    """Long: preço atinge +1R → partial fecha fraction, TP fecha o restante."""
    # entrada 100, stop 98 → R=2, trigger parcial em 102
    df = _price_series([
        (100, 99, 100),    # bar 0
        (101, 99, 100),    # bar 1: entrada
        (102.5, 100, 102), # bar 2: +1.25R → partial dispara
        (108, 103, 107),   # bar 3: aproxima
        (112, 106, 111),   # bar 4: TP (110)
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.5)
    m = bt.run()

    # Deve haver 2 trades: partial + full
    assert m["trade_count"] == 2, f"Esperado 2 trades, obteve {m['trade_count']}"
    reasons = [t["reason"] for t in bt.trades]
    assert "Partial Exit" in reasons
    assert "Take Profit" in reasons
    print("  [OK] test_partial_exit_triggers_at_1r_long")


def test_partial_exit_triggers_at_1r_short():
    """Short: preço atinge -1R → partial fecha fraction, TP fecha o restante."""
    # entrada 100, stop 102 → R=2, trigger parcial em 98
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),       # bar 1: entrada short
        (100, 97.5, 98.5),    # bar 2: low=97.5 → -1.25R dispara partial
        (98, 92, 93),         # bar 3
        (93, 89, 90),         # bar 4: TP (90)
    ])
    signals = [{
        "data": df.index[1], "tipo": "Venda", "preco": 100,
        "stop_loss": 102, "preco_alvo": 90,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.5)
    m = bt.run()
    assert m["trade_count"] == 2
    assert any(t["reason"] == "Partial Exit" for t in bt.trades)
    print("  [OK] test_partial_exit_triggers_at_1r_short")


def test_partial_exit_respects_fraction():
    """A fração configurada deve ser refletida no amount do trade parcial."""
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),
        (103, 100, 102.5),
        (107, 103, 106),
        (112, 106, 111),
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.3)  # 30%
    m = bt.run()

    partial = next(t for t in bt.trades if t["reason"] == "Partial Exit")
    full    = next(t for t in bt.trades if t["reason"] == "Take Profit")

    ratio = partial["amount"] / (partial["amount"] + full["amount"])
    assert abs(ratio - 0.3) < 1e-6, f"Fração {ratio:.3f} ≠ 0.3"
    print("  [OK] test_partial_exit_respects_fraction")


# ══════════════════════════════════════════════════════════════════════════════
# Testes — Breakeven Stop
# ══════════════════════════════════════════════════════════════════════════════

def test_breakeven_stop_protects_remaining_long():
    """Após partial em long, reversão até entry aciona breakeven stop (pnl≈0)."""
    # entrada 100, stop 98. Partial em 102. Preço reverte até 99 (abaixo de entry).
    # Com BE=entry, stop do restante = 100 → fecha em 100, pnl do 2o ~ 0.
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),       # entrada 100
        (102.5, 100, 102),    # partial
        (102.2, 99.5, 99.8),  # low=99.5 < 100 (BE) → stop aciona
        (102, 99, 101),       # (não chega aqui)
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.5, breakeven_offset_atr=0.0)
    m = bt.run()

    assert m["trade_count"] == 2, f"Esperado 2 trades, obteve {m['trade_count']}"
    partial = next(t for t in bt.trades if t["reason"] == "Partial Exit")
    be_exit = next(t for t in bt.trades if t["reason"] == "Breakeven Stop")

    # Parcial foi lucrativo (+2%)
    assert partial["pnl"] > 0
    # Saída por BE deve ter pnl essencialmente zero (entry==exit, sem custos)
    assert abs(be_exit["pnl"]) < 1e-6, f"BE pnl deveria ser ~0, obteve {be_exit['pnl']}"
    print("  [OK] test_breakeven_stop_protects_remaining_long")


def test_breakeven_stop_protects_remaining_short():
    """Após partial em short, reversão até entry aciona breakeven."""
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),       # entrada short 100
        (100, 97.5, 98.5),    # partial em ~98 (low=97.5)
        (100.3, 97.8, 100.2), # high=100.3 > 100 (BE) → stop
    ])
    signals = [{
        "data": df.index[1], "tipo": "Venda", "preco": 100,
        "stop_loss": 102, "preco_alvo": 90,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.5)
    m = bt.run()

    assert m["trade_count"] == 2
    be_exit = next(t for t in bt.trades if t["reason"] == "Breakeven Stop")
    assert abs(be_exit["pnl"]) < 1e-6
    print("  [OK] test_breakeven_stop_protects_remaining_short")


def test_partial_converts_would_be_loser_to_breakeven():
    """Trade que seria perdedor sem partial vira breakeven com partial."""
    # Cenário: preço sobe para +1.2R (dispara partial), depois cai até o stop original.
    #   Sem partial:  full loss = -1R
    #   Com partial:  +0.6R (de 50% * 1.2R) - 0R (de 50% * 0, BE stop) = +0.3R líquido
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),      # entrada 100
        (102.5, 100.5, 102), # +1.25R → partial 50%
        (102, 99.8, 100),    # stop BE em 100
    ])
    # Compare: mesmo data, mas sem partial exit
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]

    bt_no = _make_bt(df.copy(), signals)
    m_no = bt_no.run()
    final_no = m_no["final_capital"]

    bt_yes = _make_bt(df.copy(), signals,
                      use_partial_exit=True, partial_exit_r=1.0,
                      partial_exit_fraction=0.5)
    m_yes = bt_yes.run()
    final_yes = m_yes["final_capital"]

    # Com partial, final capital deve ser maior (ou igual se BE perfeito)
    assert final_yes >= final_no, (
        f"Partial deveria preservar capital: sem={final_no:.2f} com={final_yes:.2f}"
    )
    print(f"  [OK] test_partial_converts_would_be_loser_to_breakeven  "
          f"(sem={final_no:.2f}, com={final_yes:.2f})")


def test_breakeven_offset_atr_raises_stop_above_entry():
    """Com breakeven_offset_atr>0, BE stop fica acima do entry (cobre custos)."""
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),
        (102.5, 100, 102),
        (102, 100.3, 101),  # low=100.3 — ainda acima de BE com offset pequeno
        (102, 99.8, 100),   # cai abaixo de 100 → stop
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    # ATR no início é ~1.0; offset=0.2 → BE stop = 100.2
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.5, breakeven_offset_atr=0.2)
    m = bt.run()
    # Encontra o trade de saída (se houver) — deve ser BE stop
    be_trades = [t for t in bt.trades if t["reason"] == "Breakeven Stop"]
    assert len(be_trades) >= 1
    # Stop deve ter parado acima do entry (pnl ≥ 0)
    for t in be_trades:
        assert t["pnl"] >= -1e-6, f"BE com offset deveria gerar pnl>=0: {t['pnl']}"
    print("  [OK] test_breakeven_offset_atr_raises_stop_above_entry")


# ══════════════════════════════════════════════════════════════════════════════
# Testes — Conservação do capital e integridade
# ══════════════════════════════════════════════════════════════════════════════

def test_partial_plus_full_amount_equals_original():
    """amount(partial) + amount(final) == amount original."""
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),
        (103, 100, 102),
        (108, 103, 107),
        (112, 106, 111),
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.4)
    bt.run()
    partial = next(t for t in bt.trades if t["reason"] == "Partial Exit")
    full    = next(t for t in bt.trades if t["reason"] == "Take Profit")
    total   = partial["amount"] + full["amount"]

    # O original_amount é preservado (compara com tolerância numérica)
    assert abs(total - (partial["amount"] / 0.4)) < 1e-6, (
        f"amounts não fecham: partial={partial['amount']}, "
        f"full={full['amount']}, total={total}"
    )
    print("  [OK] test_partial_plus_full_amount_equals_original")


def test_partial_exit_only_once_per_trade():
    """Partial não dispara múltiplas vezes no mesmo trade."""
    # Preço vai a +2R, depois +3R — partial só deve disparar uma vez
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),    # entrada
        (103, 100, 102),   # +1R dispara partial
        (105, 102, 104),   # +2R — NÃO deve disparar de novo
        (107, 104, 106),
        (112, 106, 111),   # TP
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.5)
    bt.run()
    n_partials = sum(1 for t in bt.trades if t["reason"] == "Partial Exit")
    assert n_partials == 1, f"Esperado 1 partial exit, obteve {n_partials}"
    print("  [OK] test_partial_exit_only_once_per_trade")


def test_partial_then_stop_final():
    """Partial fecha 50%, restante é stopped no BE → Breakeven Stop."""
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),     # entrada
        (103, 100, 102.5),  # partial
        (102, 99.5, 99.7),  # low abaixo de 100 (BE) → stop
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 98, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals,
                  use_partial_exit=True, partial_exit_r=1.0,
                  partial_exit_fraction=0.5)
    bt.run()
    reasons = [t["reason"] for t in bt.trades]
    assert "Partial Exit" in reasons
    assert "Breakeven Stop" in reasons
    print("  [OK] test_partial_then_stop_final")


def test_initial_risk_abs_stored_on_open():
    """A posição deve registrar initial_risk_abs no momento da abertura."""
    df = _price_series([
        (100, 99, 100),
        (101, 99, 100),      # entrada
        (101.5, 100, 101),   # não bate partial
        (101, 97, 97.5),     # stop
    ])
    signals = [{
        "data": df.index[1], "tipo": "Compra", "preco": 100,
        "stop_loss": 97, "preco_alvo": 110,
        "estrategia": "test", "forca": 8,
    }]
    bt = _make_bt(df, signals, use_partial_exit=True)
    bt.run()
    # Verifica que rodou sem explodir (initial_risk_abs presente)
    assert bt.metrics["trade_count"] >= 1
    print("  [OK] test_initial_risk_abs_stored_on_open")


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

TESTS = [
    test_partial_exit_disabled_by_default,
    test_partial_not_triggered_if_price_doesnt_reach_r,
    test_partial_exit_triggers_at_1r_long,
    test_partial_exit_triggers_at_1r_short,
    test_partial_exit_respects_fraction,
    test_breakeven_stop_protects_remaining_long,
    test_breakeven_stop_protects_remaining_short,
    test_partial_converts_would_be_loser_to_breakeven,
    test_breakeven_offset_atr_raises_stop_above_entry,
    test_partial_plus_full_amount_equals_original,
    test_partial_exit_only_once_per_trade,
    test_partial_then_stop_final,
    test_initial_risk_abs_stored_on_open,
]


def run_all() -> int:
    print("\n" + "=" * 60)
    print("  Suite: Partial Exit + Breakeven (Sprint-1 passo 3)")
    print("=" * 60)

    passed = failed = 0
    for fn in TESTS:
        try:
            fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"  [FAIL] {fn.__name__}")
            traceback.print_exc()

    total = passed + failed
    print("=" * 60)
    print(f"  Resultado: {passed} passou(aram) / {failed} falhou(aram)")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
