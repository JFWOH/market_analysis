# indicators.py — Módulo consolidado de indicadores técnicos
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def _ensure_series(data: pd.DataFrame, col: str) -> pd.Series:
    """Extrai uma Series de um DataFrame, mesmo que a coluna seja DataFrame."""
    s = data[col]
    if isinstance(s, pd.DataFrame):
        return s.iloc[:, 0]
    return s


class TechnicalIndicators:
    """
    Calcula indicadores técnicos sobre um DataFrame OHLCV.

    Consolida as implementações de analyzer.py, market_strategy.py,
    enhanced_strategy.py e sentiment_analyzer.py.
    """

    @staticmethod
    def compute_all(data: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        """Calcula todos os indicadores técnicos de uma vez.

        Args:
            data: DataFrame com colunas OHLCV.
            params: Parâmetros opcionais (ema_short, ema_medium, ema_long, etc).

        Returns:
            DataFrame com colunas de indicadores adicionadas.
        """
        if data is None or data.empty:
            return data

        p = {
            'sma_periods': [20, 50],
            'ema_short': 8,
            'ema_medium': 21,
            'ema_long': 55,
            'rsi_period': 14,
            'atr_period': 14,
            'bb_period': 20,
            'bb_std': 2,
            'stoch_k': 14,
            'stoch_d': 3,
        }
        if params:
            p.update(params)

        close = _ensure_series(data, 'Close')
        high = _ensure_series(data, 'High')
        low = _ensure_series(data, 'Low')
        open_price = _ensure_series(data, 'Open')

        # ── Médias Móveis Simples ──
        for period in p['sma_periods']:
            data[f'SMA_{period}'] = close.rolling(window=period).mean()

        # ── Médias Móveis Exponenciais ──
        for label, span in [('short', p['ema_short']),
                            ('medium', p['ema_medium']),
                            ('long', p['ema_long'])]:
            data[f'EMA_{span}'] = close.ewm(span=span, adjust=False).mean()

        # Aliases comuns usados por outros módulos
        data['MME9'] = close.ewm(span=9, adjust=False).mean()
        data['MME21'] = close.ewm(span=21, adjust=False).mean()

        # ── RSI (Wilder's Smoothed Moving Average) ──
        data['RSI'] = TechnicalIndicators.rsi(close, p['rsi_period'])

        # ── MACD ──
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        data['MACD'] = ema12 - ema26
        data['MACD_Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
        data['MACD_Hist'] = data['MACD'] - data['MACD_Signal']

        # ── Bandas de Bollinger ──
        data['BB_Meio'] = close.rolling(window=p['bb_period']).mean()
        std_dev = close.rolling(window=p['bb_period']).std()
        data['BB_Superior'] = data['BB_Meio'] + std_dev * p['bb_std']
        data['BB_Inferior'] = data['BB_Meio'] - std_dev * p['bb_std']

        # ── ATR (Average True Range) ──
        data['ATR'] = TechnicalIndicators.atr(high, low, close, p['atr_period'])

        # ── Oscilador Estocástico ──
        min_k = low.rolling(window=p['stoch_k']).min()
        max_k = high.rolling(window=p['stoch_k']).max()
        with np.errstate(divide='ignore', invalid='ignore'):
            stoch_k = ((close - min_k) / (max_k - min_k)) * 100
        data['Stoch_K'] = stoch_k.fillna(50)
        data['Stoch_D'] = data['Stoch_K'].rolling(window=p['stoch_d']).mean().fillna(50)

        # ── Volume ──
        if 'Volume' in data.columns:
            vol = _ensure_series(data, 'Volume')
            data['Volume_SMA20'] = vol.rolling(window=20).mean()
            data['Volume_Ratio'] = vol / data['Volume_SMA20'].replace(0, np.nan)

        # ── Suporte e Resistência (simplificado) ──
        data['Suporte'] = low.rolling(window=10).min()
        data['Resistencia'] = high.rolling(window=10).max()

        logger.debug("Indicadores técnicos calculados com sucesso")
        return data

    # ------------------------------------------------------------------
    # Indicadores individuais
    # ------------------------------------------------------------------

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Calcula RSI usando SMMA de Wilder (mais preciso que SMA)."""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).fillna(50)

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 14) -> pd.Series:
        """Calcula o Average True Range."""
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()
