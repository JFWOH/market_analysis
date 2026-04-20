# tests/unit/test_api.py  — Sprint-7 passo 2
"""
Testes unitários para api.py.

Estratégia: mockamos _load_strategy, download e Backtester para não
depender de conexão de rede nem de dados reais. Testamos a lógica de
cada endpoint + helpers de serialização + cache.
"""
from __future__ import annotations

import sys
import os
import time
from unittest.mock import MagicMock, patch

import pandas as pd
import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import api  # noqa: E402  (importa após ajuste de path)
from api import (
    _cache_get, _cache_set, _cache, _CACHE_TTL,
    _signals_to_serializable,
    SignalRequest, BacktestRequest,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _dummy_signals():
    return [
        {
            "data": pd.Timestamp("2024-01-15"),
            "tipo": "COMPRA",
            "estrategia": "EMA",
            "preco": 125_000.0,
            "stop_loss": 122_000.0,
            "preco_alvo": 130_000.0,
            "forca": 3,
            "meta_prob": float("nan"),
        }
    ]


def _dummy_metrics():
    return {
        "trade_count": 12,
        "profit_factor": 1.8,
        "return_pct": 0.12,
        "max_drawdown": 0.05,
        "win_rate": 0.60,
        "sharpe": float("inf"),   # deve virar None
    }


def _mock_strategy(signals=None):
    s = MagicMock()
    s.generate_signals.return_value = signals or _dummy_signals()
    s._prepared = True
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestCache:
    def setup_method(self):
        _cache.clear()

    def test_cache_miss_returns_none(self):
        assert _cache_get("nonexistent") is None

    def test_cache_set_and_get(self):
        _cache_set("k1", {"x": 1})
        assert _cache_get("k1") == {"x": 1}

    def test_cache_expired_returns_none(self):
        _cache["expired_key"] = {"ts": time.time() - _CACHE_TTL - 1, "data": {"v": 2}}
        assert _cache_get("expired_key") is None

    def test_cache_fresh_returns_data(self):
        _cache["fresh"] = {"ts": time.time(), "data": {"v": 99}}
        assert _cache_get("fresh") == {"v": 99}

    def test_cache_overwrite(self):
        _cache_set("k", {"a": 1})
        _cache_set("k", {"a": 2})
        assert _cache_get("k") == {"a": 2}


# ─────────────────────────────────────────────────────────────────────────────
# _signals_to_serializable
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalsToSerializable:
    def test_timestamp_becomes_string(self):
        sigs = [{"data": pd.Timestamp("2024-03-10 09:15:00"), "v": 1}]
        out  = _signals_to_serializable(sigs)
        assert isinstance(out[0]["data"], str)
        assert "2024-03-10" in out[0]["data"]

    def test_numpy_int_becomes_int(self):
        sigs = [{"n": np.int64(42)}]
        out  = _signals_to_serializable(sigs)
        assert isinstance(out[0]["n"], int)
        assert out[0]["n"] == 42

    def test_numpy_float_preserved(self):
        sigs = [{"p": np.float64(3.14)}]
        out  = _signals_to_serializable(sigs)
        assert isinstance(out[0]["p"], float)
        assert abs(out[0]["p"] - 3.14) < 1e-9

    def test_nan_becomes_none(self):
        sigs = [{"meta_prob": float("nan")}]
        out  = _signals_to_serializable(sigs)
        assert out[0]["meta_prob"] is None

    def test_numpy_array_becomes_list(self):
        sigs = [{"arr": np.array([1, 2, 3])}]
        out  = _signals_to_serializable(sigs)
        assert out[0]["arr"] == [1, 2, 3]

    def test_plain_values_unchanged(self):
        sigs = [{"s": "hello", "i": 5, "f": 1.5}]
        out  = _signals_to_serializable(sigs)
        assert out[0] == {"s": "hello", "i": 5, "f": 1.5}

    def test_empty_list(self):
        assert _signals_to_serializable([]) == []

    def test_multiple_signals(self):
        sigs = [{"a": np.int32(1)}, {"b": pd.Timestamp("2024-01-01")}]
        out  = _signals_to_serializable(sigs)
        assert len(out) == 2
        assert isinstance(out[0]["a"], int)
        assert isinstance(out[1]["b"], str)


# ─────────────────────────────────────────────────────────────────────────────
# /status endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusEndpoint:
    def test_returns_ok(self):
        result = api.status()
        assert result["status"] == "ok"

    def test_has_ts(self):
        result = api.status()
        assert "ts" in result

    def test_has_domain_key(self):
        result = api.status()
        assert "domain" in result

    def test_has_fastapi_key(self):
        result = api.status()
        assert "fastapi" in result


# ─────────────────────────────────────────────────────────────────────────────
# /signal endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalEndpoint:
    def setup_method(self):
        _cache.clear()

    def _make_req(self, ticker="^BVSP", period="1y", interval="1d", params=None):
        return SignalRequest(
            ticker=ticker, period=period, interval=interval,
            params=params or {}
        )

    def test_returns_signal_out_structure(self):
        with patch("api._load_strategy") as mock_ls:
            mock_ls.return_value = (_mock_strategy(), None)
            result = api.get_signal(self._make_req())
        assert "ticker" in result
        assert "signals" in result
        assert "n_signals" in result
        assert "generated_at" in result

    def test_n_signals_matches_list(self):
        with patch("api._load_strategy") as mock_ls:
            mock_ls.return_value = (_mock_strategy(_dummy_signals()), None)
            result = api.get_signal(self._make_req())
        assert result["n_signals"] == len(result["signals"])

    def test_ticker_in_response(self):
        with patch("api._load_strategy") as mock_ls:
            mock_ls.return_value = (_mock_strategy([]), None)
            result = api.get_signal(self._make_req(ticker="PETR4.SA"))
        assert result["ticker"] == "PETR4.SA"

    def test_uses_cache_on_second_call(self):
        with patch("api._load_strategy") as mock_ls:
            mock_ls.return_value = (_mock_strategy([]), None)
            api.get_signal(self._make_req())
            api.get_signal(self._make_req())
        # _load_strategy chamado apenas uma vez (segunda vez usa cache)
        assert mock_ls.call_count == 1

    def test_no_cache_with_custom_params(self):
        with patch("api._load_strategy") as mock_ls:
            mock_ls.return_value = (_mock_strategy([]), None)
            api.get_signal(self._make_req(params={"ema_fast": 8}))
            api.get_signal(self._make_req(params={"ema_fast": 8}))
        # Sem cache quando params customizados
        assert mock_ls.call_count == 2

    def test_raises_404_on_empty_data(self):
        with patch("api._load_strategy") as mock_ls:
            mock_ls.side_effect = ValueError("Sem dados")
            if api._FASTAPI_AVAILABLE:
                with pytest.raises(api.HTTPException) as exc_info:
                    api.get_signal(self._make_req())
                assert exc_info.value.status_code == 404
            else:
                with pytest.raises(Exception):
                    api.get_signal(self._make_req())

    def test_timestamps_serialized(self):
        with patch("api._load_strategy") as mock_ls:
            mock_ls.return_value = (_mock_strategy(_dummy_signals()), None)
            result = api.get_signal(self._make_req())
        # Timestamps devem ser strings, não Timestamp objects
        for sig in result["signals"]:
            if "data" in sig and sig["data"] is not None:
                assert isinstance(sig["data"], str)


# ─────────────────────────────────────────────────────────────────────────────
# /backtest endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestBacktestEndpoint:
    def setup_method(self):
        _cache.clear()

    def _make_req(self, **kw):
        defaults = {
            "ticker": "^BVSP", "period": "2y", "interval": "1d",
            "initial_capital": 100_000.0, "commission": 0.001,
            "slippage": 0.001, "cooldown_bars": 2, "params": {},
        }
        defaults.update(kw)
        return BacktestRequest(**defaults)

    def test_returns_backtest_out_structure(self):
        mock_bt = MagicMock()
        mock_bt.run.return_value = _dummy_metrics()
        with patch("api._load_strategy") as mock_ls, \
             patch("api.Backtester", return_value=mock_bt):
            mock_ls.return_value = (_mock_strategy(), None)
            result = api.run_backtest(self._make_req())
        assert "metrics" in result
        assert "n_trades" in result
        assert "ticker" in result

    def test_n_trades_from_metrics(self):
        mock_bt = MagicMock()
        mock_bt.run.return_value = _dummy_metrics()
        with patch("api._load_strategy") as mock_ls, \
             patch("api.Backtester", return_value=mock_bt):
            mock_ls.return_value = (_mock_strategy(), None)
            result = api.run_backtest(self._make_req())
        assert result["n_trades"] == 12

    def test_inf_metrics_become_none(self):
        mock_bt = MagicMock()
        mock_bt.run.return_value = _dummy_metrics()   # sharpe=inf
        with patch("api._load_strategy") as mock_ls, \
             patch("api.Backtester", return_value=mock_bt):
            mock_ls.return_value = (_mock_strategy(), None)
            result = api.run_backtest(self._make_req())
        # sharpe=inf deve virar None
        assert result["metrics"].get("sharpe") is None

    def test_ticker_in_response(self):
        mock_bt = MagicMock()
        mock_bt.run.return_value = {"trade_count": 5}
        with patch("api._load_strategy") as mock_ls, \
             patch("api.Backtester", return_value=mock_bt):
            mock_ls.return_value = (_mock_strategy(), None)
            result = api.run_backtest(self._make_req(ticker="VALE3.SA"))
        assert result["ticker"] == "VALE3.SA"

    def test_raises_404_on_no_data(self):
        with patch("api._load_strategy") as mock_ls:
            mock_ls.side_effect = ValueError("Sem dados")
            if api._FASTAPI_AVAILABLE:
                with pytest.raises(api.HTTPException) as exc_info:
                    api.run_backtest(self._make_req())
                assert exc_info.value.status_code == 404
            else:
                with pytest.raises(Exception):
                    api.run_backtest(self._make_req())

    def test_sets_cache_after_backtest(self):
        mock_bt = MagicMock()
        mock_bt.run.return_value = _dummy_metrics()
        with patch("api._load_strategy") as mock_ls, \
             patch("api.Backtester", return_value=mock_bt):
            mock_ls.return_value = (_mock_strategy(), None)
            api.run_backtest(self._make_req(ticker="TEST", period="1y"))
        assert _cache_get("bt|TEST|1y") is not None


# ─────────────────────────────────────────────────────────────────────────────
# /metrics/{ticker} endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricsEndpoint:
    def setup_method(self):
        _cache.clear()

    def test_returns_from_cache_if_available(self):
        _cache_set("bt|^BVSP|2y", {"ticker": "^BVSP", "cached": True,
                                    "metrics": {}, "n_trades": 5,
                                    "generated_at": "2024-01-01"})
        result = api.get_metrics("^BVSP", period="2y")
        assert result["cached"] is True

    def test_runs_backtest_if_no_cache(self):
        mock_bt = MagicMock()
        mock_bt.run.return_value = _dummy_metrics()
        with patch("api._load_strategy") as mock_ls, \
             patch("api.Backtester", return_value=mock_bt):
            mock_ls.return_value = (_mock_strategy(), None)
            result = api.get_metrics("^BVSP", period="2y")
        assert "metrics" in result
        assert "n_trades" in result

    def test_ticker_in_response(self):
        mock_bt = MagicMock()
        mock_bt.run.return_value = _dummy_metrics()
        with patch("api._load_strategy") as mock_ls, \
             patch("api.Backtester", return_value=mock_bt):
            mock_ls.return_value = (_mock_strategy(), None)
            result = api.get_metrics("PETR4.SA")
        assert result["ticker"] == "PETR4.SA"


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic request models
# ─────────────────────────────────────────────────────────────────────────────

class TestRequestModels:
    def test_signal_request_defaults(self):
        req = SignalRequest()
        assert req.ticker == "^BVSP"
        assert req.period == "1y"
        assert req.interval == "1d"
        assert req.params == {}

    def test_signal_request_custom(self):
        req = SignalRequest(ticker="VALE3.SA", period="2y",
                            params={"ema_fast": 5})
        assert req.ticker == "VALE3.SA"
        assert req.params["ema_fast"] == 5

    def test_backtest_request_defaults(self):
        req = BacktestRequest()
        assert req.initial_capital == 100_000.0
        assert req.commission == 0.001
        assert req.cooldown_bars == 2

    def test_backtest_request_custom_capital(self):
        req = BacktestRequest(initial_capital=50_000.0)
        assert req.initial_capital == 50_000.0
