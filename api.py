# api.py — Sprint-7 passo 2: FastAPI REST Service
"""
Serviço REST para o sistema de análise de mercado.

Endpoints:
  GET  /status          — saúde do serviço + timestamp
  POST /signal          — gera sinais para um ticker
  POST /backtest        — executa backtest com parâmetros personalizados
  GET  /metrics/{ticker} — métricas de performance armazenadas em cache

Uso:
    uvicorn api:app --reload --host 0.0.0.0 --port 8000

    # Exemplo
    curl -X POST http://localhost:8000/signal \
         -H "Content-Type: application/json" \
         -d '{"ticker": "^BVSP", "period": "1y"}'
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI (importação lazy para testes sem uvicorn instalado)
# ---------------------------------------------------------------------------
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    # Stubs para que o módulo importe mesmo sem fastapi
    class FastAPI:          # type: ignore
        def __init__(self, **kw): pass
        def get(self, *a, **kw):  return lambda f: f
        def post(self, *a, **kw): return lambda f: f
    class BaseModel: pass   # type: ignore
    def Field(*a, **kw): return None  # type: ignore
    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code=500, detail=""): super().__init__(detail)
    class JSONResponse:     # type: ignore
        def __init__(self, content, status_code=200): self.content = content

# ---------------------------------------------------------------------------
# Domínio
# ---------------------------------------------------------------------------
try:
    from data_loader import download
    from strategy import CombinedStrategy
    from backtester import Backtester
    _DOMAIN_AVAILABLE = True
except ImportError:
    _DOMAIN_AVAILABLE = False
    download = None           # type: ignore
    CombinedStrategy = None   # type: ignore
    Backtester = None         # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Schemas Pydantic
# ─────────────────────────────────────────────────────────────────────────────

class SignalRequest(BaseModel):
    ticker: str = Field("^BVSP", description="Ticker do ativo")
    period: str = Field("1y",    description="Periodo yfinance (ex: '1y', '2y')")
    interval: str = Field("1d",  description="Intervalo (ex: '1d', '1wk')")
    params: dict = Field(default_factory=dict,
                         description="Parametros extras da strategy")


class BacktestRequest(BaseModel):
    ticker: str   = Field("^BVSP")
    period: str   = Field("2y")
    interval: str = Field("1d")
    initial_capital: float = Field(100_000.0, gt=0)
    commission: float      = Field(0.001,  ge=0, le=0.05)
    slippage: float        = Field(0.001,  ge=0, le=0.05)
    cooldown_bars: int     = Field(2,      ge=0)
    params: dict           = Field(default_factory=dict)


class SignalOut(BaseModel):
    ticker: str
    generated_at: str
    signals: list[dict]
    n_signals: int


class BacktestOut(BaseModel):
    ticker: str
    generated_at: str
    metrics: dict
    n_trades: int


# ─────────────────────────────────────────────────────────────────────────────
# Cache simples em memória
# ─────────────────────────────────────────────────────────────────────────────

_cache: dict[str, dict] = {}
_CACHE_TTL = 300   # segundos


def _cache_get(key: str) -> dict | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data: dict) -> None:
    _cache[key] = {"ts": time.time(), "data": data}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _load_strategy(ticker: str, period: str, interval: str,
                   extra_params: dict | None = None):
    """Baixa dados e prepara CombinedStrategy."""
    if not _DOMAIN_AVAILABLE:
        raise RuntimeError("Módulos de domínio não disponíveis")

    df, meta = download(ticker, period=period, interval=interval)
    if df is None or df.empty:
        raise ValueError(f"Sem dados para ticker={ticker!r}")

    s = CombinedStrategy(ticker)
    s.set_data(df)
    if extra_params:
        s.params.update(extra_params)
    s.prepare()
    return s, df


def _signals_to_serializable(signals: list[dict]) -> list[dict]:
    """Converte tipos não-serializáveis (Timestamp, numpy) para Python nativo."""
    import numpy as np
    import pandas as pd

    out = []
    for sig in signals:
        row = {}
        for k, v in sig.items():
            if isinstance(v, pd.Timestamp):
                row[k] = str(v)[:19]
            elif isinstance(v, (np.integer,)):
                row[k] = int(v)
            elif isinstance(v, (np.floating, float)) and not (v == v):
                row[k] = None   # NaN → null
            elif isinstance(v, np.floating):
                row[k] = float(v)
            elif isinstance(v, np.ndarray):
                row[k] = v.tolist()
            else:
                row[k] = v
        out.append(row)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Market Analysis API",
    description="Sprint-7 — REST interface para análise de mercado",
    version="0.7.0",
)


@app.get("/status")
def status() -> dict:
    """Verifica saúde do serviço."""
    return {
        "status":     "ok",
        "ts":         datetime.now().isoformat(),
        "domain":     _DOMAIN_AVAILABLE,
        "fastapi":    _FASTAPI_AVAILABLE,
    }


@app.post("/signal", response_model=SignalOut)
def get_signal(req: SignalRequest):
    """
    Gera sinais de trading para o ticker solicitado.

    Baixa dados via yfinance, roda CombinedStrategy e retorna a lista de sinais.
    """
    cache_key = f"signal|{req.ticker}|{req.period}|{req.interval}"
    cached = _cache_get(cache_key)
    if cached and not req.params:   # cache apenas sem params customizados
        return cached

    try:
        s, _ = _load_strategy(req.ticker, req.period, req.interval, req.params)
        signals = s.generate_signals()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Erro em /signal: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    out = {
        "ticker":       req.ticker,
        "generated_at": datetime.now().isoformat(),
        "signals":      _signals_to_serializable(signals),
        "n_signals":    len(signals),
    }
    if not req.params:
        _cache_set(cache_key, out)
    return out


@app.post("/backtest", response_model=BacktestOut)
def run_backtest(req: BacktestRequest):
    """
    Executa backtest completo e devolve métricas.

    Parâmetros da strategy podem ser passados em `params`.
    """
    try:
        s, _ = _load_strategy(req.ticker, req.period, req.interval, req.params)
        bt = Backtester(
            s,
            initial_capital=req.initial_capital,
            commission_per_trade=req.commission,
            slippage_pct=req.slippage,
            cooldown_bars=req.cooldown_bars,
        )
        metrics = bt.run()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Erro em /backtest: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    # Serializar métricas (podem conter numpy/inf)
    import math
    clean: dict[str, Any] = {}
    for k, v in metrics.items():
        if isinstance(v, float) and not math.isfinite(v):
            clean[k] = None
        else:
            clean[k] = v

    out = {
        "ticker":       req.ticker,
        "generated_at": datetime.now().isoformat(),
        "metrics":      clean,
        "n_trades":     int(metrics.get("trade_count", 0) or 0),
    }
    _cache_set(f"bt|{req.ticker}|{req.period}", out)
    return out


@app.get("/metrics/{ticker}")
def get_metrics(ticker: str, period: str = "2y"):
    """
    Retorna métricas de backtest em cache para o ticker.

    Se não houver cache, executa backtest com parâmetros padrão.
    """
    key = f"bt|{ticker}|{period}"
    cached = _cache_get(key)
    if cached:
        return cached

    # Executa backtest padrão
    try:
        s, _ = _load_strategy(ticker, period, "1d")
        bt = Backtester(s)
        metrics = bt.run()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    import math
    clean = {k: (None if isinstance(v, float) and not math.isfinite(v) else v)
             for k, v in metrics.items()}
    out = {
        "ticker":       ticker,
        "generated_at": datetime.now().isoformat(),
        "metrics":      clean,
        "n_trades":     int(metrics.get("trade_count", 0) or 0),
    }
    _cache_set(key, out)
    return out
