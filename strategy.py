# strategy.py — Estratégia combinada consolidada (indicadores + price action + sentimento)
import pandas as pd
import numpy as np
import logging
from datetime import datetime

from data_provider import DataProvider
from indicators import TechnicalIndicators
from price_action import PriceActionAnalyzer
from sentiment_analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)


class CombinedStrategy:
    """
    Estratégia de trading combinando análise técnica, price action e sentimento.

    Consolida as funcionalidades de market_strategy.py, advanced_strategy.py
    e enhanced_strategy.py em um único módulo coerente.
    """

    DEFAULT_PARAMS = {
        # EMAs
        'ema_short': 8,
        'ema_medium': 21,
        'ema_long': 55,
        # Risk management
        'atr_stop_multiplier': 1.5,
        'atr_target_multiplier': 3.0,
        'max_risk_pct': 0.01,
        'max_position_pct': 0.10,
        # Filtros
        'use_trend_filter': True,
        'use_sentiment_filter': True,
        'use_volume_filter': False,
        'min_pattern_strength': 7,
        'min_sentiment_threshold': 30,
        # Trading
        'allow_long': True,
        'allow_short': True,
        'use_trailing_stop': True,
        'trailing_start_atr': 1.5,
        'trailing_step_atr': 0.5,
    }

    def __init__(self, ticker: str, name: str = '', params: dict | None = None):
        self.ticker = ticker
        self.name = name or ticker
        self.data: pd.DataFrame | None = None
        self.params = {**self.DEFAULT_PARAMS}
        if params:
            self.params.update(params)

    # ------------------------------------------------------------------
    # Dados
    # ------------------------------------------------------------------

    def load_data(self, period: str = '1mo', interval: str = '1d') -> bool:
        """Carrega dados usando DataProvider."""
        provider = DataProvider(self.ticker, interval=interval, period=period)
        self.data = provider.download()
        return self.data is not None

    def load_historical(self, start: str, end: str,
                        interval: str = '1d') -> bool:
        """Carrega dados históricos para backtesting."""
        provider = DataProvider(self.ticker, interval=interval)
        self.data = provider.download_historical(start, end)
        return self.data is not None

    def set_data(self, data: pd.DataFrame) -> None:
        """Define dados externos (útil para otimização com cache)."""
        self.data = data.copy()

    # ------------------------------------------------------------------
    # Preparação
    # ------------------------------------------------------------------

    def prepare(self) -> pd.DataFrame | None:
        """Calcula todos os indicadores, padrões e sentimento."""
        if self.data is None or self.data.empty:
            return None

        p = self.params
        indicator_params = {
            'ema_short': p['ema_short'],
            'ema_medium': p['ema_medium'],
            'ema_long': p['ema_long'],
        }

        # 1. Indicadores técnicos
        self.data = TechnicalIndicators.compute_all(self.data, indicator_params)

        # 2. Price action
        pa = PriceActionAnalyzer(self.data)
        self.data = pa.analisar_padroes()

        # 3. Sentimento
        sa = SentimentAnalyzer(self.data)
        self.data = sa.calcular_sentimento()

        return self.data

    # ------------------------------------------------------------------
    # Geração de sinais
    # ------------------------------------------------------------------

    def generate_signals(self) -> list[dict]:
        """Gera sinais combinando price action e sentimento, filtrados por parâmetros."""
        if self.data is None or self.data.empty:
            return []

        if 'RSI' not in self.data.columns:
            self.prepare()

        p = self.params

        # Sinais de price action
        pa = PriceActionAnalyzer(self.data)
        pa_signals = pa.gerar_sinais_entrada(
            contexto_tendencia=p['use_trend_filter'],
            min_strength=p['min_pattern_strength'],
        )

        # Sinais de sentimento
        sa = SentimentAnalyzer(self.data)
        sent_signals = sa.gerar_sinais_sentimento(
            threshold=p['min_sentiment_threshold'],
        )

        all_signals = pa_signals + sent_signals

        # Filtrar por sentimento
        if p['use_sentiment_filter'] and 'Sentiment_Index' in self.data.columns:
            filtered = []
            for s in all_signals:
                idx = self.data.index.get_loc(s['data'])
                sentiment = self.data['Sentiment_Index'].iloc[idx]
                if s['tipo'] == 'Compra' and sentiment < 0:
                    continue
                if s['tipo'] == 'Venda' and sentiment > 0:
                    continue
                filtered.append(s)
            all_signals = filtered

        # Filtrar por direção permitida
        if not p['allow_long']:
            all_signals = [s for s in all_signals if s['tipo'] != 'Compra']
        if not p['allow_short']:
            all_signals = [s for s in all_signals if s['tipo'] != 'Venda']

        return all_signals

    # ------------------------------------------------------------------
    # Análise rápida (para monitoramento em tempo real)
    # ------------------------------------------------------------------

    def analyze(self) -> dict:
        """Executa análise completa e retorna resumo."""
        if self.data is None:
            return {'error': 'Sem dados carregados'}

        self.prepare()
        signals = self.generate_signals()

        # Tendência
        trend = self._determine_trend()

        # Último preço
        last_price = float(self.data['Close'].iloc[-1])
        rsi_val = float(self.data['RSI'].iloc[-1]) if not pd.isna(self.data['RSI'].iloc[-1]) else None
        atr_val = float(self.data['ATR'].iloc[-1]) if not pd.isna(self.data['ATR'].iloc[-1]) else None

        return {
            'ticker': self.ticker,
            'name': self.name,
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'trend': trend,
            'last_price': last_price,
            'rsi': rsi_val,
            'atr': atr_val,
            'signals': signals,
        }

    def _determine_trend(self) -> str:
        """Determina a tendência atual baseado em indicadores."""
        if self.data is None or self.data.empty:
            return 'Indeterminada'

        # Encontrar a última linha com dados válidos
        for idx in range(-1, -min(len(self.data), 30) - 1, -1):
            row = self.data.iloc[idx]
            if not pd.isna(row.get('SMA_20', np.nan)) and not pd.isna(row.get('MACD', np.nan)):
                break
        else:
            return 'Indeterminada'

        score = 0

        # Preço vs SMA
        if row['Close'] > row.get('SMA_20', row['Close']):
            score += 1
        else:
            score -= 1

        # MACD
        if row['MACD'] > row.get('MACD_Signal', 0):
            score += 2
        else:
            score -= 2

        # RSI
        rsi = row.get('RSI', 50)
        if not pd.isna(rsi):
            if rsi > 50:
                score += 1
            else:
                score -= 1

        # EMA alignment
        ema_s = row.get(f'EMA_{self.params["ema_short"]}')
        ema_m = row.get(f'EMA_{self.params["ema_medium"]}')
        ema_l = row.get(f'EMA_{self.params["ema_long"]}')
        if ema_s is not None and ema_m is not None and ema_l is not None:
            if not any(pd.isna(x) for x in [ema_s, ema_m, ema_l]):
                if ema_s > ema_m > ema_l:
                    score += 2
                elif ema_s < ema_m < ema_l:
                    score -= 2

        if score >= 3:
            return 'Alta'
        elif score <= -3:
            return 'Baixa'
        return 'Lateral'
