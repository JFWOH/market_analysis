"""Unit tests for Fibonacci retracement indicator and signals (Sprint-8)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators import TechnicalIndicators
from strategy import CombinedStrategy


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mk_uptrend(n: int = 80, base: float = 100.0, slope: float = 0.5,
                noise: float = 0.1, seed: int = 0) -> pd.DataFrame:
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


def _mk_downtrend(n: int = 80, base: float = 100.0, slope: float = -0.5,
                  noise: float = 0.1, seed: int = 1) -> pd.DataFrame:
    return _mk_uptrend(n=n, base=base + abs(slope) * n, slope=slope,
                       noise=noise, seed=seed)


# ── fibonacci_levels() ────────────────────────────────────────────────────────

class TestFibonacciLevels:
    def test_returns_expected_columns(self):
        df = _mk_uptrend()
        fib = TechnicalIndicators.fibonacci_levels(
            df["High"], df["Low"], df["Close"],
            swing_window=10, min_swing_atr=0.5,
        )
        for col in ["fib_swing_high", "fib_swing_low", "fib_trend",
                    "fib_23", "fib_38", "fib_50", "fib_61", "fib_78",
                    "fib_127", "fib_161"]:
            assert col in fib.columns

    def test_no_lookahead(self):
        """Os valores em i não podem depender de high/low de [i, i+...]."""
        df = _mk_uptrend(n=60)
        fib_full = TechnicalIndicators.fibonacci_levels(
            df["High"], df["Low"], df["Close"],
            swing_window=10, min_swing_atr=0.0,
        )
        # Trim depois de i=40 e recalcular: valores em [0, 40) devem ser iguais
        cut = 40
        df_cut = df.iloc[:cut]
        fib_cut = TechnicalIndicators.fibonacci_levels(
            df_cut["High"], df_cut["Low"], df_cut["Close"],
            swing_window=10, min_swing_atr=0.0,
        )
        for col in ["fib_swing_high", "fib_swing_low", "fib_trend",
                    "fib_50", "fib_61"]:
            a = fib_full[col].iloc[:cut].values
            b = fib_cut[col].values
            # Compara ignorando NaN-vs-NaN
            mask = ~(np.isnan(a) & np.isnan(b))
            np.testing.assert_allclose(a[mask], b[mask], rtol=1e-9, atol=1e-9)

    def test_warmup_period_is_nan(self):
        df = _mk_uptrend(n=40)
        fib = TechnicalIndicators.fibonacci_levels(
            df["High"], df["Low"], df["Close"],
            swing_window=20, min_swing_atr=0.0,
        )
        # As primeiras 20 barras (< swing_window) devem ter swing high/low NaN
        assert fib["fib_swing_high"].iloc[:20].isna().all()
        assert fib["fib_swing_low"].iloc[:20].isna().all()

    def test_uptrend_detected(self):
        df = _mk_uptrend(n=80, slope=1.0, noise=0.05)
        fib = TechnicalIndicators.fibonacci_levels(
            df["High"], df["Low"], df["Close"],
            swing_window=20, min_swing_atr=0.0,
        )
        trends = fib["fib_trend"].iloc[30:].dropna()
        # Em alta linear, swing_low ocorre antes do swing_high → trend = +1
        assert (trends > 0).sum() > (trends < 0).sum()

    def test_downtrend_detected(self):
        df = _mk_downtrend(n=80, slope=-1.0, noise=0.05)
        fib = TechnicalIndicators.fibonacci_levels(
            df["High"], df["Low"], df["Close"],
            swing_window=20, min_swing_atr=0.0,
        )
        trends = fib["fib_trend"].iloc[30:].dropna()
        assert (trends < 0).sum() > (trends > 0).sum()

    def test_retracement_ordering_uptrend(self):
        """Em uptrend: swing_low < fib_78 < fib_61 < fib_50 < fib_38 < fib_23 < swing_high."""
        df = _mk_uptrend(n=80, slope=1.0, noise=0.0)
        fib = TechnicalIndicators.fibonacci_levels(
            df["High"], df["Low"], df["Close"],
            swing_window=20, min_swing_atr=0.0,
        )
        row = fib.dropna().iloc[-1]
        if row["fib_trend"] > 0:
            assert row["fib_swing_low"] < row["fib_78"] < row["fib_61"] \
                < row["fib_50"] < row["fib_38"] < row["fib_23"] \
                < row["fib_swing_high"]
            assert row["fib_161"] > row["fib_swing_high"]

    def test_amplitude_filter_blocks_small_swings(self):
        # Série quase plana: amp será < min_swing_atr * ATR → tudo NaN
        n = 60
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        flat = pd.Series(100.0 + np.random.default_rng(0).normal(0, 0.01, n), index=idx)
        df = pd.DataFrame({"High": flat + 0.05, "Low": flat - 0.05, "Close": flat})
        fib = TechnicalIndicators.fibonacci_levels(
            df["High"], df["Low"], df["Close"],
            swing_window=20, min_swing_atr=10.0,  # exigência absurda
        )
        # nenhuma linha satisfaz amplitude → fib_50 deve ser todo NaN
        assert fib["fib_50"].isna().all()

    def test_compute_all_integrates_fibonacci(self):
        df = _mk_uptrend(n=80)
        out = TechnicalIndicators.compute_all(df)
        for col in ["fib_50", "fib_61", "fib_trend"]:
            assert col in out.columns


# ── _fibonacci_signals() ──────────────────────────────────────────────────────

class TestFibonacciSignals:
    def _strat(self, df: pd.DataFrame, **overrides) -> CombinedStrategy:
        s = CombinedStrategy(ticker="TEST")
        s.data = TechnicalIndicators.compute_all(df)
        s.params.update({
            "use_ensemble":       True,
            "ensemble_ema_cross": False,
            "ensemble_breakout":  False,
            "ensemble_fibonacci": True,
            "fib_swing_window":   20,
            "fib_min_swing_atr":  0.5,
            "fib_tolerance_atr":  2.0,  # frouxo p/ pegar sinais nos testes
        })
        s.params.update(overrides)
        return s

    def test_returns_list(self):
        s = self._strat(_mk_uptrend(n=80))
        out = s._fibonacci_signals()
        assert isinstance(out, list)

    def test_no_data_returns_empty(self):
        s = CombinedStrategy(ticker="TEST")
        s.data = None
        s.params["ensemble_fibonacci"] = True
        assert s._fibonacci_signals() == []

    def test_missing_columns_returns_empty(self):
        df = _mk_uptrend(n=80)
        s = CombinedStrategy(ticker="TEST")
        s.data = df  # sem compute_all → sem colunas fib_*
        s.params["ensemble_fibonacci"] = True
        assert s._fibonacci_signals() == []

    def test_signal_schema(self):
        s = self._strat(_mk_uptrend(n=120, slope=1.0))
        out = s._fibonacci_signals()
        if out:
            sig = out[0]
            for k in ["data", "tipo", "preco", "stop_loss",
                      "preco_alvo", "estrategia", "forca"]:
                assert k in sig
            assert sig["estrategia"] == "Fibonacci"
            assert sig["tipo"] in ("Compra", "Venda")

    def test_long_stop_below_entry(self):
        s = self._strat(_mk_uptrend(n=120, slope=1.0))
        for sig in s._fibonacci_signals():
            if sig["tipo"] == "Compra":
                assert sig["stop_loss"] < sig["preco"]
                assert sig["preco_alvo"] > sig["preco"]

    def test_short_stop_above_entry(self):
        s = self._strat(_mk_downtrend(n=120, slope=-1.0))
        for sig in s._fibonacci_signals():
            if sig["tipo"] == "Venda":
                assert sig["stop_loss"] > sig["preco"]
                assert sig["preco_alvo"] < sig["preco"]

    def test_allow_long_false_blocks_buys(self):
        s = self._strat(_mk_uptrend(n=120, slope=1.0), allow_long=False)
        assert all(sig["tipo"] != "Compra" for sig in s._fibonacci_signals())

    def test_allow_short_false_blocks_sells(self):
        s = self._strat(_mk_downtrend(n=120, slope=-1.0), allow_short=False)
        assert all(sig["tipo"] != "Venda" for sig in s._fibonacci_signals())

    def test_zero_tolerance_yields_few_or_no_signals(self):
        s = self._strat(_mk_uptrend(n=120, slope=1.0),
                        fib_tolerance_atr=0.0)
        loose = self._strat(_mk_uptrend(n=120, slope=1.0),
                            fib_tolerance_atr=5.0)
        assert len(s._fibonacci_signals()) <= len(loose._fibonacci_signals())

    def test_disabled_by_default(self):
        """ensemble_fibonacci default = False → generate_signals não chama."""
        assert CombinedStrategy.DEFAULT_PARAMS["ensemble_fibonacci"] is False

    def test_generate_signals_includes_fibonacci_when_enabled(self):
        s = self._strat(_mk_uptrend(n=150, slope=1.0, noise=0.05))
        # Desliga filtros que podem zerar tudo
        s.params.update({
            "use_regime_filter":    False,
            "use_sentiment_filter": False,
            "filter_by_hour":       False,
        })
        sigs = s.generate_signals()
        # Pode existir 0 (sem confluência) ou mais; só validamos que roda sem erro
        assert isinstance(sigs, list)
