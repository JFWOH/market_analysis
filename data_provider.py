# data_provider.py — Módulo consolidado para download e tratamento de dados de mercado
import pandas as pd
import numpy as np
import yfinance as yf
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DataProvider:
    """
    Provedor unificado de dados de mercado via Yahoo Finance.

    Consolida o melhor tratamento de MultiIndex e fallbacks de todas as
    versões anteriores do projeto.
    """

    def __init__(self, ticker: str, interval: str = '1d', period: str = '1mo'):
        """
        Args:
            ticker: Código do ativo (ex: "^BVSP", "USDBRL=X").
            interval: Intervalo dos candles ('1m','5m','15m','30m','1h','1d').
            period: Período de dados ('1d','5d','1mo','3mo','6mo','1y','2y').
        """
        self.ticker = ticker
        self.interval = interval
        self.period = period

    # ------------------------------------------------------------------
    # Público
    # ------------------------------------------------------------------

    def download(self) -> pd.DataFrame | None:
        """Baixa dados usando o período configurado.

        Returns:
            DataFrame com colunas OHLCV padronizadas ou None em caso de falha.
        """
        logger.info("Baixando dados para %s (interval=%s, period=%s)",
                     self.ticker, self.interval, self.period)
        try:
            data = yf.download(
                tickers=self.ticker,
                period=self.period,
                interval=self.interval,
                progress=False,
            )
            return self._normalize(data)
        except Exception as e:
            logger.error("Erro ao baixar dados para %s: %s", self.ticker, e)
            return None

    def download_historical(self, start: str, end: str,
                            interval: str | None = None) -> pd.DataFrame | None:
        """Baixa dados históricos para um intervalo de datas.

        Args:
            start: Data de início (ex: '2022-01-01').
            end: Data de fim (ex: '2023-12-31').
            interval: Opcional — sobrescreve o intervalo padrão.

        Returns:
            DataFrame com colunas OHLCV padronizadas ou None em caso de falha.
        """
        iv = interval or self.interval
        logger.info("Baixando histórico de %s (%s → %s, interval=%s)",
                     self.ticker, start, end, iv)
        try:
            data = yf.download(
                tickers=self.ticker,
                start=start,
                end=end,
                interval=iv,
                progress=False,
            )
            return self._normalize(data)
        except Exception as e:
            logger.error("Erro ao baixar histórico de %s: %s", self.ticker, e)
            return None

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _normalize(self, data: pd.DataFrame) -> pd.DataFrame | None:
        """Normaliza colunas do DataFrame retornado pelo yfinance."""
        if data is None or data.empty:
            logger.warning("Nenhum dado retornado para %s", self.ticker)
            return None

        # 1. Resolver MultiIndex (yfinance >= 0.2 retorna MultiIndex para ticker único)
        if isinstance(data.columns, pd.MultiIndex):
            logger.debug("Resolvendo MultiIndex de colunas")
            new_cols = []
            for col in data.columns:
                if isinstance(col, tuple) and len(col) > 1:
                    # Pega a primeira parte (Price) e ignora o ticker
                    new_cols.append(col[0])
                else:
                    new_cols.append(str(col))
            data.columns = new_cols

        # 2. Garantir que as colunas padrão existem
        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in required:
            if col not in data.columns:
                # Tentar encontrar equivalente case-insensitive
                match = [c for c in data.columns if c.lower() == col.lower()]
                if match:
                    data[col] = data[match[0]]
                    logger.debug("Mapeada coluna '%s' → '%s'", match[0], col)

        # 3. Fallback final para 'Close'
        if 'Close' not in data.columns:
            price_cols = [c for c in data.columns
                          if any(t in c.lower() for t in ['close', 'adj', 'last', 'price'])]
            if price_cols:
                data['Close'] = data[price_cols[0]]
                logger.warning("'Close' não encontrado — usando '%s'", price_cols[0])
            elif len(data.columns) > 0:
                data['Close'] = data[data.columns[0]]
                logger.warning("'Close' não encontrado — usando primeira coluna '%s'",
                               data.columns[0])
            else:
                logger.error("DataFrame vazio após normalização para %s", self.ticker)
                return None

        logger.info("Dados normalizados: %d períodos, colunas: %s",
                     len(data), list(data.columns))
        return data
