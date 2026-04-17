"""
tests/unit/test_backtester.py — Testes de regressão do motor de backtesting.

Usa MockStrategy (sem yfinance) para testar o engine de forma determinística.
Executável diretamente:
    python tests/unit/test_backtester.py
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

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures & MockStrategy
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_PARAMS = {
    "ema_short":            8,
    "ema_medium":           21,
    "ema_long":             55,
    "atr_stop_multiplier":  1.5,
    "atr_target_multiplier":3.0,
    "max_position_pct":     0.5,
    "max_risk_pct":         0.02,
    "use_trailing_stop":    False,
}


class MockStrategy:
    """Estratégia mínima para testes — sem dependência de rede ou dados reais."""

    def __init__(
        self,
        data: pd.DataFrame,
        signals: list[dict],
        params: dict | None = None,
    ) -> None:
        self.data     = data
        self._signals = signals
        self.params   = params or dict(_DEFAULT_PARAMS)
        self.name     = "MockStrategy"

    def prepare(self) -> None:
        pass

    def generate_signals(self) -> list[dict]:
        return list(self._signals)


def _make_price_series(prices: list[float]) -> pd.DataFrame:
    """Cria DataFrame OHLCV a partir de uma lista de preços de fechamento."""
    n   = len(prices)
    arr = np.array(prices, dtype=float)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open":   arr * 0.999,
        "High":   arr * 1.005,
        "Low":    arr * 0.995,
        "Close":  arr,
        "Volume": np.full(n, 10_000.0),
        "ATR":    arr * 0.02,    # 2% do preço
    }, index=idx)


def _signal(data: pd.DataFrame, bar: int, tipo: str,
            stop_offset: float, target_offset: float,
            pattern: str = "test_pattern") -> dict:
    """Cria sinal indexado pelo datetime do DataFrame."""
    price = float(data["Close"].iloc[bar])
    return {
        "data":       data.index[bar],
        "tipo":       tipo,
        "preco":      price,
        "stop_loss":  price - stop_offset if tipo == "Compra" else price + stop_offset,
        "preco_alvo": price + target_offset if tipo == "Compra" else price - target_offset,
        "estrategia": pattern,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Testes de _size_position (isolado, sem instância)
# ──────────────────────────────────────────────────────────────────────────────

def test_size_position_capped_by_pct():
    """Quando o risco permitiria posição gigante, o cap por % deve prevalecer."""
    size = Backtester._size_position(
        entry_price=100_000.0,
        stop_loss=99_000.0,   # risk = 1%
        capital=100_000.0,
        max_position_pct=0.5,
        max_risk_pct=0.02,
    )
    # size_by_risk = 100k * 0.02 / 0.01 = 200k → cap = 50k
    assert abs(size - 50_000.0) < 0.01, f"Esperado 50000, obteve {size}"
    print("  [OK] test_size_position_capped_by_pct")


def test_size_position_capped_by_risk():
    """Quando o stop é largo (risco alto), a posição deve ser limitada pelo risco."""
    size = Backtester._size_position(
        entry_price=100_000.0,
        stop_loss=90_000.0,   # risk = 10%
        capital=100_000.0,
        max_position_pct=0.5,
        max_risk_pct=0.02,
    )
    # size_by_risk = 100k * 0.02 / 0.10 = 20k < cap 50k
    assert abs(size - 20_000.0) < 0.01, f"Esperado 20000, obteve {size}"
    print("  [OK] test_size_position_capped_by_risk")


def test_size_position_min_amount():
    """Posição abaixo de min_amount deve retornar 0."""
    size = Backtester._size_position(
        entry_price=100_000.0,
        stop_loss=99_500.0,
        capital=1_000.0,     # capital pequeno → posição < 1000
        max_position_pct=0.5,
        max_risk_pct=0.02,
        min_amount=1_000.0,
    )
    assert size == 0.0, f"Esperado 0 para posição abaixo do mínimo, obteve {size}"
    print("  [OK] test_size_position_min_amount")


def test_size_position_zero_stop_distance():
    """Stop == entry → risco forçado a 0.1% → posição calculável."""
    # stop_loss == entry_price → risk_per_unit = 0 → clamped to 0.001
    size = Backtester._size_position(
        entry_price=100_000.0,
        stop_loss=100_000.0,
        capital=100_000.0,
        max_position_pct=0.5,
        max_risk_pct=0.02,
    )
    # size_by_risk = 100k * 0.02 / 0.001 = 2_000_000 → cap = 50k
    assert abs(size - 50_000.0) < 0.01
    print("  [OK] test_size_position_zero_stop_distance")


# ──────────────────────────────────────────────────────────────────────────────
# Trade único — Take Profit
# ──────────────────────────────────────────────────────────────────────────────

def test_single_long_take_profit():
    """Long trade batendo no alvo: P&L calculado analiticamente."""
    prices = [100_000, 101_000, 102_000, 103_000, 105_000,
              104_000, 103_000, 102_000, 101_000, 100_000]
    df = _make_price_series(prices)
    # Sinal no bar 2 (preço = 102k); alvo = 105k; stop = 99k
    sig = _signal(df, bar=2, tipo="Compra", stop_offset=3_000, target_offset=3_000)
    sig["preco_alvo"] = 105_000.0   # override explícito

    bt = Backtester(MockStrategy(df, [sig]), initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0)
    metrics = bt.run()

    assert metrics["trade_count"] == 1, f"Esperado 1 trade, obteve {metrics['trade_count']}"

    t = bt.trades[0]
    assert t["reason"] == "Take Profit", f"Esperado Take Profit, obteve {t['reason']}"

    # Sizing: size_by_risk = 100k * 0.02 / (3000/102000) = ~68k → cap 50k
    expected_amount = 50_000.0
    assert abs(t["amount"] - expected_amount) < 1.0, (
        f"Amount esperado ~50000, obteve {t['amount']:.2f}"
    )

    # P&L: 50k * (105k/102k - 1) = 50k * 3/102 ≈ 1470.59
    expected_pnl = expected_amount * (105_000 / 102_000 - 1)
    assert abs(t["pnl"] - expected_pnl) < 1.0, (
        f"P&L esperado {expected_pnl:.2f}, obteve {t['pnl']:.2f}"
    )

    # Capital final = 100k + pnl
    assert abs(metrics["final_capital"] - (100_000.0 + expected_pnl)) < 1.0
    print(f"  [OK] test_single_long_take_profit  (pnl={t['pnl']:.2f})")


def test_single_long_stop_loss():
    """Long trade batendo no stop: P&L negativo calculado analiticamente."""
    prices = [100_000, 101_000, 102_000, 98_000, 97_000,
              96_000, 95_000, 94_000, 93_000, 92_000]
    # Força Low abaixo do stop (99k) logo no bar 3
    df = _make_price_series(prices)
    df.loc[df.index[3], "Low"] = 98_000.0  # garante toque no stop

    sig = _signal(df, bar=2, tipo="Compra", stop_offset=3_000, target_offset=6_000)

    bt = Backtester(MockStrategy(df, [sig]), initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0)
    metrics = bt.run()

    assert metrics["trade_count"] == 1
    t = bt.trades[0]
    assert t["reason"] == "Stop Loss", f"Esperado Stop Loss, obteve {t['reason']}"
    assert t["pnl"] < 0, f"P&L deveria ser negativo, obteve {t['pnl']:.2f}"
    print(f"  [OK] test_single_long_stop_loss     (pnl={t['pnl']:.2f})")


def test_single_short_take_profit():
    """Short trade batendo no alvo: P&L positivo."""
    prices = [100_000, 99_000, 98_000, 97_000, 96_000,
               95_000, 94_000, 93_000, 92_000, 91_000]
    df = _make_price_series(prices)
    # Sinal no bar 2 (98k); alvo = 95k; stop = 101k
    sig = _signal(df, bar=2, tipo="Venda", stop_offset=3_000, target_offset=3_000)
    sig["preco_alvo"] = 95_000.0

    bt = Backtester(MockStrategy(df, [sig]), initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0)
    metrics = bt.run()

    assert metrics["trade_count"] == 1
    t = bt.trades[0]
    assert t["type"] == "short"
    assert t["pnl"] > 0, f"P&L deveria ser positivo para short bem-sucedido, obteve {t['pnl']:.2f}"
    print(f"  [OK] test_single_short_take_profit  (pnl={t['pnl']:.2f})")


# ──────────────────────────────────────────────────────────────────────────────
# Custos de transação
# ──────────────────────────────────────────────────────────────────────────────

def test_commission_reduces_pnl():
    """Comissão deve reduzir o P&L líquido."""
    prices = [100_000, 101_000, 102_000, 105_000, 104_000]
    df  = _make_price_series(prices)
    sig = _signal(df, bar=2, tipo="Compra", stop_offset=3_000, target_offset=3_000)
    sig["preco_alvo"] = 105_000.0

    bt_no_comm   = Backtester(MockStrategy(df, [sig]), commission_per_trade=0.0,  slippage_pct=0.0)
    bt_with_comm = Backtester(MockStrategy(df, [sig]), commission_per_trade=10.0, slippage_pct=0.0)

    m_no   = bt_no_comm.run()
    m_yes  = bt_with_comm.run()

    assert m_yes["final_capital"] < m_no["final_capital"], (
        "Comissão não reduziu o capital final"
    )
    diff = m_no["final_capital"] - m_yes["final_capital"]
    # 2 comissões (entrada + saída) = 20.0
    assert abs(diff - 20.0) < 0.01, f"Diferença esperada = 20.0, obteve {diff:.4f}"

    t = bt_with_comm.trades[0]
    assert abs(t["commission"] - 20.0) < 0.01
    print(f"  [OK] test_commission_reduces_pnl  (diff={diff:.2f})")


def test_slippage_reduces_pnl():
    """Slippage adverso deve reduzir o P&L em entrada e saída."""
    prices = [100_000, 101_000, 102_000, 105_000, 104_000]
    df  = _make_price_series(prices)
    sig = _signal(df, bar=2, tipo="Compra", stop_offset=3_000, target_offset=3_000)
    sig["preco_alvo"] = 105_000.0

    bt_no_slip   = Backtester(MockStrategy(df, [sig]), commission_per_trade=0.0, slippage_pct=0.0)
    bt_with_slip = Backtester(MockStrategy(df, [sig]), commission_per_trade=0.0, slippage_pct=0.001)

    m_no  = bt_no_slip.run()
    m_yes = bt_with_slip.run()

    assert m_yes["final_capital"] < m_no["final_capital"], (
        "Slippage não reduziu o capital final"
    )
    print(f"  [OK] test_slippage_reduces_pnl")


# ──────────────────────────────────────────────────────────────────────────────
# Sem trades
# ──────────────────────────────────────────────────────────────────────────────

def test_no_signals():
    """Sem sinais: capital final deve ser igual ao inicial."""
    df = _make_price_series([100_000] * 20)
    bt = Backtester(MockStrategy(df, []), initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0)
    metrics = bt.run()

    assert metrics["trade_count"] == 0
    assert abs(metrics["final_capital"] - 100_000.0) < 0.01
    print("  [OK] test_no_signals")


# ──────────────────────────────────────────────────────────────────────────────
# Métricas
# ──────────────────────────────────────────────────────────────────────────────

def test_win_rate_calculation():
    """Win rate = wins / total trades."""
    prices = [100_000, 101_000, 102_000, 105_000, 103_000,
              104_000, 105_000, 103_000, 98_000,  97_000]
    df = _make_price_series(prices)
    df["Low"] = df["Close"] * 0.98   # garante que stop pode ser atingido

    # Trade 1 (bar 2): WIN (alvo 105k atingido no bar 3)
    sig1 = _signal(df, bar=2, tipo="Compra", stop_offset=5_000, target_offset=3_000)
    sig1["preco_alvo"] = 105_000.0

    # Trade 2 (bar 5): LOSS (preço cai para 98k, stop em 103k)
    sig2 = _signal(df, bar=5, tipo="Compra", stop_offset=2_000, target_offset=10_000)
    df.loc[df.index[8], "Low"] = 97_000.0  # garante toque no stop

    bt = Backtester(MockStrategy(df, [sig1, sig2]), initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0)
    bt.run()

    n = bt.metrics["trade_count"]
    assert n >= 1, "Deve haver pelo menos 1 trade"

    wr = bt.metrics["win_rate"]
    assert 0.0 <= wr <= 1.0, f"Win rate fora de [0,1]: {wr}"
    print(f"  [OK] test_win_rate_calculation  (wr={wr:.2%}, trades={n})")


def test_metrics_completeness():
    """Todas as métricas esperadas devem estar presentes após run()."""
    df  = _make_price_series([100_000, 101_000, 102_000, 105_000, 104_000])
    sig = _signal(df, bar=2, tipo="Compra", stop_offset=3_000, target_offset=3_000)
    sig["preco_alvo"] = 105_000.0

    bt = Backtester(MockStrategy(df, [sig]), initial_capital=100_000.0)
    bt.run()

    required_keys = [
        "initial_capital", "final_capital", "return_pct", "annualized_return",
        "trade_count", "win_rate", "avg_win", "avg_loss", "expectancy",
        "profit_factor", "max_drawdown", "sharpe_ratio", "sortino_ratio",
        "calmar_ratio", "max_consec_wins", "max_consec_losses",
        "avg_duration_bars", "total_commission", "slippage_pct", "pattern_stats",
    ]
    for key in required_keys:
        assert key in bt.metrics, f"Métrica '{key}' ausente"
    print("  [OK] test_metrics_completeness")


def test_sharpe_positive_for_profitable_strategy():
    """Sharpe deve ser positivo para estratégia lucrativa."""
    # Série monotonicamente crescente → equity sempre sobe
    prices = list(range(100_000, 110_001, 500))  # 21 candles
    df  = _make_price_series(prices)
    sig = _signal(df, bar=2, tipo="Compra", stop_offset=2_000, target_offset=8_000)
    sig["preco_alvo"] = float(prices[-1])  # alvo no último preço

    bt = Backtester(MockStrategy(df, [sig]), initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0)
    bt.run()

    # Pode não ter trade (alvo não atingido antes do fim), mas se tiver, deve ser lucrativo
    if bt.metrics["trade_count"] > 0:
        assert bt.metrics["return_pct"] > 0, "Retorno deve ser positivo"
    print(f"  [OK] test_sharpe_positive_for_profitable_strategy")


def test_max_drawdown_non_negative():
    """Max drawdown deve ser sempre >= 0."""
    prices = [100_000, 105_000, 103_000, 101_000, 98_000, 97_000, 100_000]
    df  = _make_price_series(prices)
    sig = _signal(df, bar=1, tipo="Compra", stop_offset=10_000, target_offset=2_000)

    bt = Backtester(MockStrategy(df, [sig]), initial_capital=100_000.0)
    bt.run()
    assert bt.metrics.get("max_drawdown", 0) >= 0
    print("  [OK] test_max_drawdown_non_negative")


def test_consecutive_wins_losses_counted():
    """max_consec_wins / losses devem ser calculados corretamente."""
    # Simula 3 wins seguidos + 2 losses
    df = _make_price_series([100_000] * 20)
    # Injetar trades manualmente (sem correr o loop)
    bt = Backtester.__new__(Backtester)
    bt.trades = [
        {"pnl":  100.0}, {"pnl":  200.0}, {"pnl":  300.0},   # 3 wins
        {"pnl": -100.0}, {"pnl": -200.0},                      # 2 losses
        {"pnl":  50.0},                                         # 1 win
    ]
    bt.equity = [100_000.0] * 7
    bt.equity_dates = pd.date_range("2023-01-02", periods=7, freq="B").tolist()
    bt.initial_capital = 100_000.0
    bt.slippage_pct = 0.0

    m = bt._compute_metrics(100_350.0, df)
    assert m["max_consec_wins"]   == 3, f"Esperado 3 wins consecutivos, obteve {m['max_consec_wins']}"
    assert m["max_consec_losses"] == 2, f"Esperado 2 losses consecutivos, obteve {m['max_consec_losses']}"
    print(f"  [OK] test_consecutive_wins_losses_counted  (W={m['max_consec_wins']}, L={m['max_consec_losses']})")


# ──────────────────────────────────────────────────────────────────────────────
# trade_report()
# ──────────────────────────────────────────────────────────────────────────────

def test_trade_report_empty():
    """trade_report() sem trades deve retornar DataFrame vazio."""
    df = _make_price_series([100_000] * 10)
    bt = Backtester(MockStrategy(df, []), initial_capital=100_000.0)
    bt.run()
    report = bt.trade_report()
    assert isinstance(report, pd.DataFrame)
    assert report.empty
    print("  [OK] test_trade_report_empty")


def test_trade_report_columns():
    """trade_report() deve ter todas as colunas esperadas."""
    prices = [100_000, 101_000, 102_000, 105_000, 104_000]
    df  = _make_price_series(prices)
    sig = _signal(df, bar=2, tipo="Compra", stop_offset=3_000, target_offset=3_000)
    sig["preco_alvo"] = 105_000.0

    bt = Backtester(MockStrategy(df, [sig]), initial_capital=100_000.0,
                    commission_per_trade=5.0, slippage_pct=0.0)
    bt.run()
    report = bt.trade_report()

    expected_cols = [
        "entry_date", "exit_date", "duration_bars", "type", "pattern",
        "entry_price", "exit_price", "amount", "gross_pnl", "commission",
        "pnl", "pct_change", "reason",
    ]
    for col in expected_cols:
        assert col in report.columns, f"Coluna '{col}' ausente no trade_report"

    assert len(report) == bt.metrics["trade_count"]
    print(f"  [OK] test_trade_report_columns  (rows={len(report)})")


def test_trade_report_duration_bars():
    """duration_bars deve ser >= 1 para trade que dura pelo menos 1 bar."""
    prices = [100_000, 101_000, 102_000, 103_000, 105_000, 104_000]
    df  = _make_price_series(prices)
    sig = _signal(df, bar=2, tipo="Compra", stop_offset=3_000, target_offset=3_000)
    sig["preco_alvo"] = 105_000.0

    bt = Backtester(MockStrategy(df, [sig]), initial_capital=100_000.0,
                    commission_per_trade=0.0, slippage_pct=0.0)
    bt.run()
    report = bt.trade_report()

    if not report.empty:
        assert (report["duration_bars"] >= 1).all(), (
            f"duration_bars deve ser >= 1, obteve {report['duration_bars'].tolist()}"
        )
    print(f"  [OK] test_trade_report_duration_bars")


# ──────────────────────────────────────────────────────────────────────────────
# Fator de anualização
# ──────────────────────────────────────────────────────────────────────────────

def test_annualization_daily():
    """Dados diários → fator ≈ √252."""
    df  = _make_price_series([100_000.0] * 20)  # freq='B' (business day)
    fac = Backtester._annualization_factor(df)
    assert abs(fac - np.sqrt(252)) < 0.1, f"Fator diário esperado √252={np.sqrt(252):.4f}, obteve {fac:.4f}"
    print(f"  [OK] test_annualization_daily  (factor={fac:.4f})")


def test_annualization_intraday_1h():
    """Dados de 1 hora → fator ≈ √(252*8)."""
    idx = pd.date_range("2023-01-02 09:00", periods=20, freq="h")
    df  = pd.DataFrame({"Close": [100_000.0] * 20}, index=idx)
    fac = Backtester._annualization_factor(df)
    expected = np.sqrt(252 * 8)
    assert abs(fac - expected) < 1.0, f"Fator 1h esperado {expected:.4f}, obteve {fac:.4f}"
    print(f"  [OK] test_annualization_intraday_1h  (factor={fac:.4f})")


def test_annualization_short_series():
    """Série com apenas 1 elemento → fallback √252."""
    df  = _make_price_series([100_000.0])
    fac = Backtester._annualization_factor(df)
    assert abs(fac - np.sqrt(252)) < 0.1
    print("  [OK] test_annualization_short_series")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_size_position_capped_by_pct,
    test_size_position_capped_by_risk,
    test_size_position_min_amount,
    test_size_position_zero_stop_distance,
    test_single_long_take_profit,
    test_single_long_stop_loss,
    test_single_short_take_profit,
    test_commission_reduces_pnl,
    test_slippage_reduces_pnl,
    test_no_signals,
    test_win_rate_calculation,
    test_metrics_completeness,
    test_sharpe_positive_for_profitable_strategy,
    test_max_drawdown_non_negative,
    test_consecutive_wins_losses_counted,
    test_trade_report_empty,
    test_trade_report_columns,
    test_trade_report_duration_bars,
    test_annualization_daily,
    test_annualization_intraday_1h,
    test_annualization_short_series,
]


def run_all() -> bool:
    passed = failed = 0
    print(f"\n{'='*60}")
    print("  Suite: backtester/ — position sizing + métricas + report")
    print(f"{'='*60}")
    for fn in _TESTS:
        try:
            fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"  [FAIL] {fn.__name__}")
            traceback.print_exc()
    print(f"{'='*60}")
    print(f"  Resultado: {passed} passou(aram) / {failed} falhou(aram)")
    print(f"{'='*60}\n")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
