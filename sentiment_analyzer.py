# sentiment_analyzer.py — Análise de sentimento de mercado (versão consolidada)
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Analisa o sentimento do mercado através de múltiplos indicadores técnicos.

    Nota: O "sentimento" aqui é um índice de momentum composto baseado em
    indicadores técnicos (RSI, Estocástico, Momentum). Não incorpora dados
    de notícias ou fluxo de ordens.
    """

    def __init__(self, dados: pd.DataFrame):
        self.dados = dados

    def _get_series(self, col: str, default=None) -> pd.Series:
        """Extrai Series com segurança."""
        try:
            s = self.dados[col]
            return s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
        except KeyError:
            if default is not None:
                return pd.Series(default, index=self.dados.index)
            raise

    def calcular_sentimento(self) -> pd.DataFrame:
        """Calcula indicadores de sentimento e retorna o DataFrame enriquecido."""
        dados = self.dados

        # Verificar pré-requisitos
        if 'RSI' not in dados.columns:
            logger.warning("RSI não encontrado nos dados. Calcule indicadores primeiro.")
            return dados

        rsi = self._get_series('RSI')
        close = self._get_series('Close')

        # ── Divergências ──
        if 'Higher_High' in dados.columns and 'Lower_Low' in dados.columns:
            rsi_hh = (rsi > rsi.shift(1)) & (rsi.shift(1) > rsi.shift(2))
            rsi_ll = (rsi < rsi.shift(1)) & (rsi.shift(1) < rsi.shift(2))
            dados['Bullish_Divergence'] = (
                (self._get_series('Lower_Low', 0) == 1) & (~rsi_ll)
            ).fillna(False).astype(int)
            dados['Bearish_Divergence'] = (
                (self._get_series('Higher_High', 0) == 1) & (~rsi_hh)
            ).fillna(False).astype(int)

        # ── Extremos ──
        stoch_k = self._get_series('Stoch_K', 50)
        dados['Extreme_Overbought'] = ((rsi > 80) & (stoch_k > 90)).fillna(False).astype(int)
        dados['Extreme_Oversold'] = ((rsi < 20) & (stoch_k < 10)).fillna(False).astype(int)

        # ── Momentum normalizado ──
        momentum = close / close.shift(14) - 1
        dados['Momentum_14'] = momentum
        mom_range = momentum.max() - momentum.min()
        if mom_range > 0:
            dados['Momentum_Norm'] = 2 * (momentum - momentum.min()) / mom_range - 1
        else:
            dados['Momentum_Norm'] = 0.0

        # ── Índice de Sentimento (vetorizado, -100 a +100) ──
        # Componentes: RSI (peso 0.3), Stochastic (peso 0.2), Momentum (peso 0.5)
        rsi_contrib = ((rsi - 50) / 50).fillna(0) * 0.3
        stoch_contrib = ((stoch_k - 50) / 50).fillna(0) * 0.2
        mom_contrib = dados['Momentum_Norm'].fillna(0) * 0.5
        raw_sentiment = (rsi_contrib + stoch_contrib + mom_contrib) * 100
        dados['Sentiment_Index'] = raw_sentiment.clip(-100, 100)

        # ── Classificação por zona ──
        si = dados['Sentiment_Index']
        dados['Strong_Bullish_Sentiment'] = (si > 70).astype(int)
        dados['Bullish_Sentiment'] = ((si > 30) & (si <= 70)).astype(int)
        dados['Neutral_Sentiment'] = ((si >= -30) & (si <= 30)).astype(int)
        dados['Bearish_Sentiment'] = ((si < -30) & (si >= -70)).astype(int)
        dados['Strong_Bearish_Sentiment'] = (si < -70).astype(int)

        self.dados = dados
        logger.debug("Sentimento calculado — vetorizado")
        return dados

    def gerar_sinais_sentimento(self, threshold: float = 50) -> list[dict]:
        """Gera sinais baseados em mudanças de sentimento.

        Args:
            threshold: Limiar de sentimento para considerar mudança significativa.

        Returns:
            Lista de sinais de trading.
        """
        sinais = []
        dados = self.dados

        if 'Sentiment_Index' not in dados.columns or len(dados) < 5:
            return sinais

        sentiment = self._get_series('Sentiment_Index')
        close = self._get_series('Close')

        for i in range(5, len(dados)):
            sent_anterior = sentiment.iloc[i - 5:i - 1].mean()
            sent_atual = sentiment.iloc[i]
            preco = close.iloc[i]

            atr_val = dados['ATR'].iloc[i] if 'ATR' in dados.columns else preco * 0.01
            if pd.isna(atr_val):
                atr_val = preco * 0.01

            if sent_anterior < -threshold and sent_atual > 0:
                sinais.append({
                    'data': dados.index[i],
                    'tipo': 'Compra',
                    'preco': preco,
                    'stop_loss': preco - atr_val * 1.5,
                    'preco_alvo': preco + atr_val * 3,
                    'estrategia': 'Reversão de Sentimento Altista',
                    'forca': 8,
                })

            if sent_anterior > threshold and sent_atual < 0:
                sinais.append({
                    'data': dados.index[i],
                    'tipo': 'Venda',
                    'preco': preco,
                    'stop_loss': preco + atr_val * 1.5,
                    'preco_alvo': preco - atr_val * 3,
                    'estrategia': 'Reversão de Sentimento Baixista',
                    'forca': 8,
                })

        return sinais