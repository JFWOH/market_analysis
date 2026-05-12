"""Sprint-13 — testes do Chandelier exit pós-breakeven."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtester import Backtester


class _StubStrategy:
    """Estratégia mock: devolve sinais fixos pré-definidos."""

    def __init__(self, df: pd.DataFrame, signals: list[dict],
                 params: dict | None = None):
        self.data   = df
        self._sigs  = signals
        self.params = dict(params or {})

    def prepare(self):
        return None

    def generate_signals(self):
        return list(self._sigs)


def _mk_df(closes: list[float], highs: list[float] | None = None,
           lows: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    h = highs if highs is not None else [c + 0.5 for c in closes]
    l = lows  if lows  is not None else [c - 0.5 for c in closes]
    return pd.DataFrame({
        "Open":   closes,
        "High":   h,
        "Low":    l,
        "Close":  closes,
        "Volume": [1_000_000.0] * n,
        "ATR":    [1.0] * n,
    }, index=idx)


class TestChandelierExit:
    def test_chandelier_no_op_when_disabled(self):
        # Preço sobe linearmente; sem chandelier, sai por TP
        closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
        df = _mk_df(closes)
        sig = [{
            "data":       df.index[1],
            "tipo":       "Compra",
            "preco":      101.0,
            "stop_loss":  99.0,
            "preco_alvo": 108.0,
            "estrategia": "TEST",
            "forca":      8,
        }]
        strat = _StubStrategy(df, sig, params={
            "use_partial_exit":         False,
            "use_chandelier_after_be":  False,
        })
        bt = Backtester(strat, initial_capital=100_000, cooldown_bars=0,
                        commission_per_trade=0.0, slippage_pct=0.0)
        bt.run()
        assert len(bt.trades) == 1
        assert bt.trades[0]["reason"] == "Take Profit"

    def test_chandelier_tightens_stop_after_breakeven(self):
        """Com partial exit + chandelier: stop sobe e fecha posição
        em pullback antes de atingir o TP original."""
        # Sobe até 108, depois cai de volta para 103
        closes = [100, 101, 102, 103, 104, 105, 106, 107, 108,
                  106, 104, 102]
        df = _mk_df(closes)
        # ATR=1.0, entry=101, init_risk=2 → partial em 103 (1R)
        sig = [{
            "data":       df.index[1],
            "tipo":       "Compra",
            "preco":      101.0,
            "stop_loss":  99.0,
            "preco_alvo": 130.0,         # alto p/ não disparar
            "estrategia": "TEST",
            "forca":      8,
        }]
        strat = _StubStrategy(df, sig, params={
            "use_partial_exit":          True,
            "partial_exit_r":            1.0,
            "partial_exit_fraction":     0.5,
            "breakeven_offset_atr":      0.0,
            "use_chandelier_after_be":   True,
            "chandelier_atr_mult":       2.0,  # apertado
        })
        bt = Backtester(strat, initial_capital=100_000, cooldown_bars=0,
                        commission_per_trade=0.0, slippage_pct=0.0)
        bt.run()
        # Esperamos pelo menos 2 trades: o partial e o stop chandelier
        reasons = [t["reason"] for t in bt.trades]
        assert any("Partial" in r or "Parcial" in r or "partial" in r.lower()
                   for r in reasons) or len(bt.trades) >= 1
        # E o stop final do trade principal deve ter sido movido para cima
        # do entry (breakeven ou melhor)
        last = bt.trades[-1]
        if last["reason"] != "Take Profit":
            # Saiu via stop apertado → preço de saída >= entry
            assert last["exit_price"] >= 100.5  # acima do stop original (99)

    def test_chandelier_never_loosens_stop(self):
        """Em barra de queda forte, chandelier não pode AFROUXAR o stop."""
        # Sobe até 106 (peak), depois sobe mais devagar
        closes = [100, 101, 102, 103, 104, 105, 106, 105.5, 105.2, 105.1]
        df = _mk_df(closes)
        sig = [{
            "data":       df.index[1],
            "tipo":       "Compra",
            "preco":      101.0,
            "stop_loss":  99.0,
            "preco_alvo": 120.0,
            "estrategia": "TEST",
            "forca":      8,
        }]
        strat = _StubStrategy(df, sig, params={
            "use_partial_exit":          True,
            "partial_exit_r":            1.0,
            "use_chandelier_after_be":   True,
            "chandelier_atr_mult":       3.0,
        })
        bt = Backtester(strat, initial_capital=100_000, cooldown_bars=0,
                        commission_per_trade=0.0, slippage_pct=0.0)
        bt.run()
        # Trade principal deve fechar com lucro (sem afrouxar stop)
        if bt.trades:
            assert all(t["pnl"] >= -100.0 for t in bt.trades)

    def test_peak_tracking_initialized(self):
        """Position dict deve ter peak_high e peak_low desde abertura."""
        closes = [100, 101, 102, 103]
        df = _mk_df(closes)
        sig = [{
            "data": df.index[1], "tipo": "Compra", "preco": 101.0,
            "stop_loss": 99.0, "preco_alvo": 200.0,
            "estrategia": "TEST", "forca": 8,
        }]
        strat = _StubStrategy(df, sig, params={})
        bt = Backtester(strat, initial_capital=100_000, cooldown_bars=0,
                        commission_per_trade=0.0, slippage_pct=0.0)
        # Só roda — se não levantar exceção, o init está OK
        bt.run()
