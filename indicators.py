# indicators.py — Módulo consolidado de indicadores técnicos
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Utilitários internos
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_series(data: pd.DataFrame, col: str) -> pd.Series:
    """Extrai uma Series de um DataFrame, mesmo que a coluna seja DataFrame."""
    s = data[col]
    if isinstance(s, pd.DataFrame):
        return s.iloc[:, 0]
    return s


def _safe_series(s: pd.Series, fill: float = np.nan) -> pd.Series:
    """Retorna série zerada com mesmo índice se a entrada for inválida."""
    if s is None or s.empty:
        return pd.Series(dtype=float)
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Classe principal
# ──────────────────────────────────────────────────────────────────────────────

class TechnicalIndicators:
    """
    Calcula indicadores técnicos sobre um DataFrame OHLCV.

    Todos os métodos estáticos aceitam pd.Series e retornam pd.Series,
    permitindo testes unitários isolados de cada indicador.

    compute_all() orquestra o cálculo completo e retorna uma *cópia*
    do DataFrame de entrada com as colunas de indicadores adicionadas.
    """

    # ── Padrões ────────────────────────────────────────────────────────────────

    DEFAULT_PARAMS: dict = {
        "sma_periods": [20, 50],
        "ema_short":   8,
        "ema_medium":  21,
        "ema_long":    55,
        "rsi_period":  14,
        "atr_period":  14,
        "bb_period":   20,
        "bb_std":      2,
        "stoch_k":     14,
        "stoch_d":     3,
    }

    # ── Orquestrador ──────────────────────────────────────────────────────────

    @staticmethod
    def compute_all(data: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        """Calcula todos os indicadores técnicos sobre uma *cópia* do DataFrame.

        Args:
            data:   DataFrame com colunas OHLCV.
            params: Parâmetros opcionais — sobrescrevem DEFAULT_PARAMS.

        Returns:
            Nova cópia do DataFrame com colunas de indicadores adicionadas.
            O DataFrame original não é modificado.
        """
        if data is None or data.empty:
            logger.warning("compute_all: DataFrame vazio ou None")
            return data

        p = dict(TechnicalIndicators.DEFAULT_PARAMS)
        if params:
            p.update(params)

        df = data.copy()

        close      = _ensure_series(df, "Close")
        high       = _ensure_series(df, "High")
        low        = _ensure_series(df, "Low")

        # ── Médias Móveis Simples ─────────────────────────────────────────────
        for period in p["sma_periods"]:
            df[f"SMA_{period}"] = TechnicalIndicators.sma(close, period)

        # ── Médias Móveis Exponenciais ────────────────────────────────────────
        for label, span in [
            ("short",  p["ema_short"]),
            ("medium", p["ema_medium"]),
            ("long",   p["ema_long"]),
        ]:
            df[f"EMA_{span}"] = TechnicalIndicators.ema(close, span)

        # Aliases usados por outros módulos
        df["MME9"]  = TechnicalIndicators.ema(close, 9)
        df["MME21"] = TechnicalIndicators.ema(close, 21)

        # ── RSI (Wilder SMMA) ─────────────────────────────────────────────────
        df["RSI"] = TechnicalIndicators.rsi(close, p["rsi_period"])

        # ── MACD ──────────────────────────────────────────────────────────────
        macd_line, signal, hist = TechnicalIndicators.macd(close)
        df["MACD"]        = macd_line
        df["MACD_Signal"] = signal
        df["MACD_Hist"]   = hist

        # ── Bandas de Bollinger ───────────────────────────────────────────────
        bb_mid, bb_up, bb_dn = TechnicalIndicators.bollinger_bands(
            close, p["bb_period"], p["bb_std"]
        )
        df["BB_Meio"]     = bb_mid
        df["BB_Superior"] = bb_up
        df["BB_Inferior"] = bb_dn

        # ── ATR (Wilder SMMA) ─────────────────────────────────────────────────
        df["ATR"] = TechnicalIndicators.atr(high, low, close, p["atr_period"])

        # ── Estocástico ───────────────────────────────────────────────────────
        stoch_k, stoch_d = TechnicalIndicators.stochastic(
            high, low, close, p["stoch_k"], p["stoch_d"]
        )
        df["Stoch_K"] = stoch_k
        df["Stoch_D"] = stoch_d

        # ── Volume ────────────────────────────────────────────────────────────
        if "Volume" in df.columns:
            vol = _ensure_series(df, "Volume")
            vol_sma = vol.rolling(window=20, min_periods=1).mean()
            df["Volume_SMA20"] = vol_sma
            df["Volume_Ratio"] = vol / vol_sma.replace(0, np.nan)

        # ── Suporte / Resistência (swing simples) ─────────────────────────────
        df["Suporte"]    = low.rolling(window=10, min_periods=1).min()
        df["Resistencia"] = high.rolling(window=10, min_periods=1).max()

        logger.debug("Indicadores técnicos calculados: %d períodos", len(df))
        return df

    # ── Indicadores individuais ───────────────────────────────────────────────

    @staticmethod
    def sma(close: pd.Series, period: int) -> pd.Series:
        """Média Móvel Simples.

        Args:
            close:  Série de fechamentos.
            period: Número de períodos.

        Returns:
            Series com SMA; NaN nos primeiros (period-1) elementos.
        """
        return close.rolling(window=period, min_periods=period).mean()

    @staticmethod
    def ema(close: pd.Series, span: int) -> pd.Series:
        """Média Móvel Exponencial (EMA / MME).

        Usa ``adjust=False`` (recursivo), que é o padrão de plataformas
        como MetaTrader / TradingView.

        Args:
            close: Série de fechamentos.
            span:  Número de períodos (alpha = 2 / (span + 1)).

        Returns:
            Series com EMA a partir do primeiro elemento.
        """
        return close.ewm(span=span, adjust=False).mean()

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """RSI usando SMMA de Wilder (comportamento idêntico ao MetaTrader).

        Args:
            close:  Série de fechamentos.
            period: Número de períodos (padrão: 14).

        Returns:
            Series RSI no intervalo [0, 100]; NaN substituído por 50.
        """
        delta    = close.diff()
        gain     = delta.clip(lower=0)
        loss     = (-delta).clip(lower=0)

        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        rs  = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # Casos especiais:
        #   avg_loss == 0, avg_gain > 0  → RSI = 100 (sem perdas)
        #   avg_loss == 0, avg_gain == 0 → RSI = 50  (sem movimento)
        #   avg_gain == 0, avg_loss > 0  → RSI = 0   (sem ganhos)
        no_loss    = avg_loss == 0
        has_gain   = avg_gain > 0
        rsi = rsi.where(~no_loss, np.where(has_gain, 100.0, 50.0))
        rsi = rsi.where(~(avg_gain == 0) | no_loss, 0.0)
        return rsi.fillna(50.0)   # warm-up NaN (min_periods não atingido)

    @staticmethod
    def macd(
        close: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """MACD — Moving Average Convergence Divergence.

        Args:
            close:  Série de fechamentos.
            fast:   Períodos da EMA rápida (padrão: 12).
            slow:   Períodos da EMA lenta (padrão: 26).
            signal: Períodos da linha de sinal (padrão: 9).

        Returns:
            Tupla (macd_line, signal_line, histogram).
        """
        ema_fast   = close.ewm(span=fast,   adjust=False).mean()
        ema_slow   = close.ewm(span=slow,   adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram  = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(
        close: pd.Series,
        period: int = 20,
        num_std: float = 2.0,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Bandas de Bollinger.

        Args:
            close:   Série de fechamentos.
            period:  Períodos da média móvel central (padrão: 20).
            num_std: Múltiplo do desvio padrão (padrão: 2.0).

        Returns:
            Tupla (middle, upper, lower).
        """
        middle = close.rolling(window=period, min_periods=period).mean()
        std    = close.rolling(window=period, min_periods=period).std(ddof=1)
        upper  = middle + std * num_std
        lower  = middle - std * num_std
        return middle, upper, lower

    @staticmethod
    def atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
    ) -> pd.Series:
        """ATR — Average True Range usando SMMA de Wilder.

        CORREÇÃO v2: substituída SMA (rolling.mean) por SMMA de Wilder
        (ewm alpha=1/period), alinhando com MetaTrader / TradingView.

        Args:
            high:   Série de máximas.
            low:    Série de mínimas.
            close:  Série de fechamentos.
            period: Períodos (padrão: 14).

        Returns:
            Series com ATR; NaN nos primeiros períodos.
        """
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low  - close.shift(1)).abs()
        tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    @staticmethod
    def stochastic(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        k_period: int = 14,
        d_period: int = 3,
    ) -> tuple[pd.Series, pd.Series]:
        """Oscilador Estocástico %K e %D.

        Trata o caso de range zero (max == min) com fillna(50) após divisão
        segura, evitando RuntimeWarning de divisão por zero.

        Args:
            high:     Série de máximas.
            low:      Série de mínimas.
            close:    Série de fechamentos.
            k_period: Lookback para %K (padrão: 14).
            d_period: Suavização para %D (padrão: 3).

        Returns:
            Tupla (stoch_k, stoch_d) no intervalo [0, 100].
        """
        min_k  = low.rolling(window=k_period,  min_periods=k_period).min()
        max_k  = high.rolling(window=k_period, min_periods=k_period).max()
        rng    = (max_k - min_k).replace(0, np.nan)          # evita divisão por zero
        stoch_k = ((close - min_k) / rng * 100.0).fillna(50.0)
        stoch_d = stoch_k.rolling(window=d_period, min_periods=d_period).mean().fillna(50.0)
        return stoch_k, stoch_d
