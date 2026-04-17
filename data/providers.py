"""
data/providers.py — Interface e implementações de provedores de dados OHLCV.

Hierarquia:
    DataProvider (ABC)
    └── YFinanceProvider  — Yahoo Finance com cache pickle e timezone

Compatibilidade retroativa:
    A classe ``DataProvider`` do módulo raiz ``data_provider.py`` ainda funciona;
    este módulo oferece a versão aprimorada com cache, timezone e validação.

Uso típico:
    from data.providers import YFinanceProvider

    provider = YFinanceProvider()
    df = provider.get_ohlcv("^BVSP", "1d", start="2023-01-01", end="2023-12-31")
    # df.index é DatetimeIndex tz-aware (America/Sao_Paulo)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from .cache import DataCache
from .schema import OHLCVSchema, OHLCVValidationError

logger = logging.getLogger(__name__)

# Fuso oficial da B3
_TZ_B3 = ZoneInfo("America/Sao_Paulo")

# Intervalos intraday com limite de histórico no Yahoo Finance
_INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}


class DataProvider(ABC):
    """Interface abstrata para provedores de dados OHLCV."""

    @abstractmethod
    def get_ohlcv(
        self,
        ticker: str,
        interval: str,
        *,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
    ) -> pd.DataFrame | None:
        """Retorna DataFrame OHLCV validado e tz-aware ou None em caso de falha.

        Args:
            ticker:   Código do ativo (ex: "^BVSP", "USDBRL=X").
            interval: Intervalo dos candles ('1m','5m','15m','30m','1h','1d').
            start:    Data de início ISO-8601 (ex: '2023-01-01'). Exclusivo com period.
            end:      Data de fim ISO-8601 (ex: '2023-12-31').
            period:   Período relativo ('1d','5d','1mo','3mo','6mo','1y','2y').
                      Usado apenas quando start/end não forem informados.

        Returns:
            DataFrame com DatetimeIndex tz-aware e colunas OHLCV, ou None.
        """
        ...


# ---------------------------------------------------------------------------


class YFinanceProvider(DataProvider):
    """Provedor Yahoo Finance com cache pickle, validação e timezone B3.

    Consolida a lógica de ``data_provider.DataProvider`` (módulo legado)
    e adiciona:
      • Integração com :class:`~data.cache.DataCache`
      • Conversão automática para ``America/Sao_Paulo``
      • Validação via :class:`~data.schema.OHLCVSchema`
      • Resolução robusta de MultiIndex (yfinance >= 0.2)
    """

    def __init__(
        self,
        cache: DataCache | None = None,
        cache_dir: str = "~/.market_analysis_cache",
        use_cache: bool = True,
    ) -> None:
        """
        Args:
            cache:     Instância de DataCache. Se None e use_cache=True, cria uma.
            cache_dir: Diretório do cache (usado apenas se cache=None).
            use_cache: Habilitar/desabilitar cache por instância.
        """
        self._use_cache = use_cache
        if use_cache:
            self._cache = cache if cache is not None else DataCache(cache_dir=cache_dir)
        else:
            self._cache = None

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def get_ohlcv(
        self,
        ticker: str,
        interval: str,
        *,
        start: str | None = None,
        end: str | None = None,
        period: str | None = None,
    ) -> pd.DataFrame | None:
        """Veja :meth:`DataProvider.get_ohlcv`."""
        # Validar que start/end ou period foram fornecidos
        if start is None and period is None:
            period = "1mo"
            logger.debug("Nenhum start/period informado — usando period='1mo'")

        # --- Cache lookup ---------------------------------------------------
        cache_key: str | None = None
        if self._cache is not None:
            cache_key = DataCache.make_key(
                ticker, interval,
                start or "", end or "", period or ""
            )
            cached = self._cache.get(cache_key, interval=interval)
            if cached is not None:
                return cached

        # --- Download -------------------------------------------------------
        raw = self._download(ticker, interval, start=start, end=end, period=period)
        if raw is None:
            return None

        # --- Normalizar MultiIndex e colunas --------------------------------
        df = self._normalize_columns(raw, ticker)
        if df is None:
            return None

        # --- Validar schema -------------------------------------------------
        try:
            df = OHLCVSchema.validate(df, drop_bad_rows=True)
        except OHLCVValidationError as exc:
            logger.error("Falha na validação OHLCV para %s: %s", ticker, exc)
            return None

        # --- Timezone -------------------------------------------------------
        df = self._convert_tz(df)

        # --- Persistir cache ------------------------------------------------
        if self._cache is not None and cache_key is not None:
            self._cache.set(cache_key, df)

        return df

    # ------------------------------------------------------------------
    # Retrocompatibilidade com data_provider.DataProvider legado
    # ------------------------------------------------------------------

    def download(self, ticker: str, interval: str = "1d", period: str = "1mo") -> pd.DataFrame | None:
        """Atalho retrocompatível — usa period."""
        return self.get_ohlcv(ticker, interval, period=period)

    def download_historical(
        self,
        ticker: str,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame | None:
        """Atalho retrocompatível — usa start/end."""
        return self.get_ohlcv(ticker, interval, start=start, end=end)

    # ------------------------------------------------------------------
    # Privados
    # ------------------------------------------------------------------

    def _download(
        self,
        ticker: str,
        interval: str,
        *,
        start: str | None,
        end: str | None,
        period: str | None,
    ) -> pd.DataFrame | None:
        """Faz o download bruto via yfinance."""
        kwargs: dict[str, Any] = {
            "tickers": ticker,
            "interval": interval,
            "progress": False,
            "auto_adjust": True,
        }
        if start is not None:
            kwargs["start"] = start
            if end is not None:
                kwargs["end"] = end
        else:
            kwargs["period"] = period or "1mo"

        logger.info(
            "YFinance download: ticker=%s interval=%s start=%s end=%s period=%s",
            ticker, interval, start, end, period,
        )
        try:
            data = yf.download(**kwargs)
            if data is None or data.empty:
                logger.warning("Nenhum dado retornado para %s", ticker)
                return None
            return data
        except Exception as exc:
            logger.error("Erro no download de %s: %s", ticker, exc)
            return None

    @staticmethod
    def _normalize_columns(data: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
        """Resolve MultiIndex e padroniza nomes de colunas OHLCV."""
        if data is None or data.empty:
            return None

        df = data.copy()

        # 1. Resolver MultiIndex (yfinance >= 0.2 para ticker único)
        if isinstance(df.columns, pd.MultiIndex):
            new_cols: list[str] = []
            for col in df.columns:
                if isinstance(col, tuple):
                    # (Price, Ticker) → pega Price (índice 0)
                    new_cols.append(str(col[0]))
                else:
                    new_cols.append(str(col))
            df.columns = new_cols
            logger.debug("MultiIndex resolvido: %s", new_cols)

        # 2. Garantir colunas obrigatórias (case-insensitive)
        required = ["Open", "High", "Low", "Close", "Volume"]
        for col in required:
            if col not in df.columns:
                match = [c for c in df.columns if c.lower() == col.lower()]
                if match:
                    df[col] = df[match[0]]
                    logger.debug("Mapeada coluna '%s' → '%s'", match[0], col)

        # 3. Fallback para Close
        if "Close" not in df.columns:
            price_cols = [
                c for c in df.columns
                if any(t in c.lower() for t in ["close", "adj", "last", "price"])
            ]
            if price_cols:
                df["Close"] = df[price_cols[0]]
                logger.warning("'Close' não encontrado — usando '%s'", price_cols[0])
            elif len(df.columns) > 0:
                df["Close"] = df[df.columns[0]]
                logger.warning(
                    "'Close' não encontrado — usando primeira coluna '%s'", df.columns[0]
                )
            else:
                logger.error("DataFrame sem colunas utilizáveis para %s", ticker)
                return None

        return df

    @staticmethod
    def _convert_tz(df: pd.DataFrame) -> pd.DataFrame:
        """Converte índice para America/Sao_Paulo (tz-aware).

        • Se o índice já for tz-aware, converte de timezone.
        • Se for tz-naive, assume UTC antes de converter.
        """
        if not isinstance(df.index, pd.DatetimeIndex):
            return df

        if df.index.tz is None:
            # tz-naive: assume UTC (comportamento padrão do yfinance para daily+)
            df = df.copy()
            df.index = df.index.tz_localize("UTC").tz_convert(_TZ_B3)
        elif str(df.index.tz) != str(_TZ_B3):
            df = df.copy()
            df.index = df.index.tz_convert(_TZ_B3)

        return df
