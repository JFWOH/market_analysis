"""Sprint-11 — testes do Macro Direction Lock."""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import TechnicalIndicators
from strategy import CombinedStrategy


def _mk(slope: float, n: int = 120, base: float = 100.0,
        noise: float = 0.05, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = base + np.arange(n) * slope + rng.normal(0, noise, size=n)
    high = close + 0.5
    low = close - 0.5
    opn = close - 0.1
    vol = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Open": opn, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


class TestMacroDirectionDefaults:
    def test_default_off(self):
        assert CombinedStrategy.DEFAULT_PARAMS["macro_direction_lock"] is False

    def test_default_window(self):
        assert CombinedStrategy.DEFAULT_PARAMS["macro_direction_window"] == 60


class TestMacroDirectionLogic:
    def _strat(self, df, **overrides):
        s = CombinedStrategy(ticker="TEST")
        s.set_data(TechnicalIndicators.compute_all(df))
        s.params.update({
            "macro_direction_lock":      True,
            "macro_direction_window":    60,
            "macro_direction_ret_min":   0.05,
            "macro_direction_hurst_min": 0.55,
        })
        s.params.update(overrides)
        return s

    def test_blocks_short_in_uptrend(self):
        df = _mk(slope=1.0, n=120, noise=0.05)  # alta forte
        s = self._strat(df, macro_direction_hurst_min=-1.0)  # ignora Hurst
        ts = s.data.index[100]
        venda = {"data": ts, "tipo": "Venda", "estrategia": "X"}
        assert s._macro_direction_allows(venda) is False

    def test_allows_long_in_uptrend(self):
        df = _mk(slope=1.0, n=120, noise=0.05)
        s = self._strat(df, macro_direction_hurst_min=-1.0)
        ts = s.data.index[100]
        compra = {"data": ts, "tipo": "Compra", "estrategia": "X"}
        assert s._macro_direction_allows(compra) is True

    def test_blocks_long_in_downtrend(self):
        df = _mk(slope=-1.0, n=120, base=200.0, noise=0.05)
        s = self._strat(df, macro_direction_hurst_min=-1.0)
        ts = s.data.index[100]
        compra = {"data": ts, "tipo": "Compra", "estrategia": "X"}
        assert s._macro_direction_allows(compra) is False

    def test_allows_short_in_downtrend(self):
        df = _mk(slope=-1.0, n=120, base=200.0, noise=0.05)
        s = self._strat(df, macro_direction_hurst_min=-1.0)
        ts = s.data.index[100]
        venda = {"data": ts, "tipo": "Venda", "estrategia": "X"}
        assert s._macro_direction_allows(venda) is True

    def test_flat_market_allows_both(self):
        df = _mk(slope=0.0, n=120, noise=0.1)  # ret ~ 0
        s = self._strat(df, macro_direction_hurst_min=-1.0)
        ts = s.data.index[100]
        for tipo in ("Compra", "Venda"):
            assert s._macro_direction_allows(
                {"data": ts, "tipo": tipo, "estrategia": "X"}) is True

    def test_hurst_below_threshold_disables_lock(self):
        """Mesmo com retorno acima do limiar, se Hurst médio < threshold,
        o regime não é considerado confirmado e o sinal passa."""
        df = _mk(slope=1.0, n=120, noise=0.05)
        s = self._strat(df, macro_direction_hurst_min=0.99)  # impossível
        ts = s.data.index[100]
        venda = {"data": ts, "tipo": "Venda", "estrategia": "X"}
        assert s._macro_direction_allows(venda) is True

    def test_unknown_timestamp_permissive(self):
        df = _mk(slope=1.0, n=120)
        s = self._strat(df)
        fake_ts = pd.Timestamp("1900-01-01")
        assert s._macro_direction_allows(
            {"data": fake_ts, "tipo": "Venda", "estrategia": "X"}) is True

    def test_no_data_permissive(self):
        s = CombinedStrategy(ticker="TEST")
        s.params["macro_direction_lock"] = True
        assert s._macro_direction_allows(
            {"data": pd.Timestamp("2024-01-01"), "tipo": "Venda"}) is True


class TestMacroDirectionIntegration:
    def test_generate_signals_drops_shorts_in_uptrend(self):
        df = _mk(slope=1.0, n=150, noise=0.1)
        s = CombinedStrategy(ticker="TEST")
        s.set_data(TechnicalIndicators.compute_all(df))
        s.params.update({
            "use_ensemble":          True,
            "ensemble_ema_cross":    True,
            "ensemble_breakout":     True,
            "use_regime_filter":     False,
            "use_sentiment_filter":  False,
            "filter_by_hour":        False,
            "macro_direction_lock":  False,  # sem lock primeiro
            "macro_direction_hurst_min": -1.0,
        })
        sigs_off = s.generate_signals()
        shorts_off = [x for x in sigs_off if x["tipo"] == "Venda"]

        s2 = CombinedStrategy(ticker="TEST")
        s2.set_data(TechnicalIndicators.compute_all(df))
        s2.params.update({**s.params, "macro_direction_lock": True})
        sigs_on = s2.generate_signals()
        shorts_on = [x for x in sigs_on if x["tipo"] == "Venda"]

        # Com lock ativo em uptrend forte, número de shorts deve diminuir
        assert len(shorts_on) <= len(shorts_off)
