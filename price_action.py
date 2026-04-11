# price_action.py — Análise de padrões de price action (metodologia Al Brooks)
# Consolidado e corrigido: gerar_sinais_entrada agora é método da classe.
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


class PriceActionAnalyzer:
    """Implementa padrões de price action baseados na metodologia de Al Brooks."""

    def __init__(self, dados: pd.DataFrame):
        self.dados = dados

    def get_series(self, column_name: str) -> pd.Series:
        """Extrai uma Series de forma segura, mesmo que a coluna seja DataFrame."""
        col = self.dados[column_name]
        if isinstance(col, pd.DataFrame):
            return col.iloc[:, 0]
        return col

    # ------------------------------------------------------------------
    # Pipeline principal
    # ------------------------------------------------------------------

    def analisar_padroes(self) -> pd.DataFrame:
        """Analisa todos os padrões de price action nos dados."""
        self.calcular_estrutura_barras()
        self.identificar_barras_tendencia()
        self.identificar_reversoes()
        self.identificar_continuacoes()
        self.identificar_falhas_breakout()
        return self.dados

    # ------------------------------------------------------------------
    # Estrutura das barras
    # ------------------------------------------------------------------

    def calcular_estrutura_barras(self) -> pd.DataFrame:
        """Calcula a estrutura básica das barras para análise de price action."""
        close = self.get_series('Close')
        open_price = self.get_series('Open')
        high = self.get_series('High')
        low = self.get_series('Low')

        # Tamanho das barras
        range_bar = high - low
        body = abs(close - open_price)
        range_nonzero = range_bar.replace(0, np.nan)
        body_pct = (body / range_nonzero).fillna(0)

        # Sombras (wicks)
        upper_wick = high - np.maximum(open_price, close)
        lower_wick = np.minimum(open_price, close) - low
        upper_wick_ratio = (upper_wick / range_nonzero).fillna(0)
        lower_wick_ratio = (lower_wick / range_nonzero).fillna(0)

        self.dados['Range'] = range_bar
        self.dados['Body'] = body
        self.dados['Body_Pct'] = body_pct
        self.dados['Upper_Wick'] = upper_wick
        self.dados['Lower_Wick'] = lower_wick
        self.dados['Upper_Wick_Ratio'] = upper_wick_ratio
        self.dados['Lower_Wick_Ratio'] = lower_wick_ratio

        # Direção da barra
        self.dados['Bull_Bar'] = (close > open_price).fillna(False).astype(int)
        self.dados['Bear_Bar'] = (close < open_price).fillna(False).astype(int)
        self.dados['Doji'] = (body_pct < 0.1).fillna(False).astype(int)

        # Tamanho relativo
        range_ma5 = range_bar.rolling(window=5).mean()
        self.dados['Range_MA5'] = range_ma5
        self.dados['Large_Range'] = (range_bar > range_ma5 * 1.5).fillna(False).astype(int)
        self.dados['Small_Range'] = (range_bar < range_ma5 * 0.5).fillna(False).astype(int)

        # Relação com barras anteriores
        self.dados['Higher_High'] = (high > high.shift(1)).fillna(False).astype(int)
        self.dados['Lower_Low'] = (low < low.shift(1)).fillna(False).astype(int)
        self.dados['Higher_Close'] = (close > close.shift(1)).fillna(False).astype(int)
        self.dados['Lower_Close'] = (close < close.shift(1)).fillna(False).astype(int)

        # Barras internas/externas
        self.dados['Inside_Bar'] = (
            (high <= high.shift(1)) & (low >= low.shift(1))
        ).fillna(False).astype(int)
        self.dados['Outside_Bar'] = (
            (high >= high.shift(1)) & (low <= low.shift(1))
        ).fillna(False).astype(int)

        return self.dados

    # ------------------------------------------------------------------
    # Barras de tendência
    # ------------------------------------------------------------------

    def identificar_barras_tendencia(self) -> pd.DataFrame:
        """Identifica barras de tendência (trend bars) segundo Al Brooks."""
        bull_bar = self.get_series('Bull_Bar')
        bear_bar = self.get_series('Bear_Bar')
        body_pct = self.get_series('Body_Pct')
        upper_wick_ratio = self.get_series('Upper_Wick_Ratio')
        lower_wick_ratio = self.get_series('Lower_Wick_Ratio')

        # Strong trend bars
        self.dados['Strong_Bull_Bar'] = (
            (bull_bar == 1) & (body_pct > 0.7) & (lower_wick_ratio < 0.15)
        ).fillna(False).astype(int)

        self.dados['Strong_Bear_Bar'] = (
            (bear_bar == 1) & (body_pct > 0.7) & (upper_wick_ratio < 0.15)
        ).fillna(False).astype(int)

        # Shaved bars
        range_bar = self.get_series('Range')
        range_nonzero = range_bar.replace(0, np.nan)
        self.dados['Shaved_Top'] = (
            self.get_series('Upper_Wick') / range_nonzero < 0.05
        ).fillna(False).astype(int)
        self.dados['Shaved_Bottom'] = (
            self.get_series('Lower_Wick') / range_nonzero < 0.05
        ).fillna(False).astype(int)

        # Barras consecutivas na mesma direção (micro tendência)
        for i in range(2, 6):
            self.dados[f'Bull_Bars_{i}'] = 1
            self.dados[f'Bear_Bars_{i}'] = 1
            for j in range(i):
                bull_shifted = bull_bar.shift(j).fillna(0)
                bear_shifted = bear_bar.shift(j).fillna(0)
                self.dados[f'Bull_Bars_{i}'] = (
                    self.get_series(f'Bull_Bars_{i}') & (bull_shifted == 1)
                ).fillna(False).astype(int)
                self.dados[f'Bear_Bars_{i}'] = (
                    self.get_series(f'Bear_Bars_{i}') & (bear_shifted == 1)
                ).fillna(False).astype(int)

        return self.dados

    # ------------------------------------------------------------------
    # Padrões de reversão
    # ------------------------------------------------------------------

    def identificar_reversoes(self) -> pd.DataFrame:
        """Identifica padrões de reversão segundo Al Brooks."""
        upper_wick_ratio = self.get_series('Upper_Wick_Ratio')
        lower_wick_ratio = self.get_series('Lower_Wick_Ratio')
        body_pct = self.get_series('Body_Pct')
        higher_high = self.get_series('Higher_High')
        lower_low = self.get_series('Lower_Low')
        bull_bar = self.get_series('Bull_Bar')
        bear_bar = self.get_series('Bear_Bar')
        doji = self.get_series('Doji')
        open_price = self.get_series('Open')
        close = self.get_series('Close')

        bull_bar_s1 = bull_bar.shift(1).fillna(0)
        bear_bar_s1 = bear_bar.shift(1).fillna(0)
        higher_high_s1 = higher_high.shift(1).fillna(0)
        lower_low_s1 = lower_low.shift(1).fillna(0)
        close_s1 = close.shift(1)
        open_s1 = open_price.shift(1)

        try:
            bull_bars_3_s1 = self.get_series('Bull_Bars_3').shift(1).fillna(0)
            bear_bars_3_s1 = self.get_series('Bear_Bars_3').shift(1).fillna(0)
        except KeyError:
            bull_bars_3_s1 = pd.Series(0, index=self.dados.index)
            bear_bars_3_s1 = pd.Series(0, index=self.dados.index)

        # ── Bearish reversals ──
        self.dados['Bearish_Pin_Bar'] = (
            (upper_wick_ratio > 0.6) & (body_pct < 0.3) & (higher_high == 1)
        ).fillna(False).astype(int)

        self.dados['Bearish_Engulfing'] = (
            (bear_bar == 1) & (bull_bar_s1 == 1) &
            (open_price > close_s1) & (close < open_s1)
        ).fillna(False).astype(int)

        self.dados['Bearish_Doji'] = (
            (doji == 1) & (higher_high == 1) & (bull_bars_3_s1 == 1)
        ).fillna(False).astype(int)

        self.dados['Bearish_Two_Bar_Reversal'] = (
            (bear_bar == 1) & (bull_bar_s1 == 1) &
            (higher_high_s1 == 1) & (lower_low == 1)
        ).fillna(False).astype(int)

        # ── Bullish reversals ──
        self.dados['Bullish_Pin_Bar'] = (
            (lower_wick_ratio > 0.6) & (body_pct < 0.3) & (lower_low == 1)
        ).fillna(False).astype(int)

        self.dados['Bullish_Engulfing'] = (
            (bull_bar == 1) & (bear_bar_s1 == 1) &
            (open_price < close_s1) & (close > open_s1)
        ).fillna(False).astype(int)

        self.dados['Bullish_Doji'] = (
            (doji == 1) & (lower_low == 1) & (bear_bars_3_s1 == 1)
        ).fillna(False).astype(int)

        self.dados['Bullish_Two_Bar_Reversal'] = (
            (bull_bar == 1) & (bear_bar_s1 == 1) &
            (lower_low_s1 == 1) & (higher_high == 1)
        ).fillna(False).astype(int)

        return self.dados

    # ------------------------------------------------------------------
    # Padrões de continuação
    # ------------------------------------------------------------------

    def identificar_continuacoes(self) -> pd.DataFrame:
        """Identifica padrões de continuação segundo Al Brooks."""
        bear_bar = self.get_series('Bear_Bar')
        bull_bar = self.get_series('Bull_Bar')
        close = self.get_series('Close')

        strong_bull_s1 = self.get_series('Strong_Bull_Bar').shift(1).fillna(0)
        strong_bear_s1 = self.get_series('Strong_Bear_Bar').shift(1).fillna(0)
        close_s2 = close.shift(2)

        self.dados['Bull_Pullback'] = (
            (bear_bar == 1) & (strong_bull_s1 == 1) & (close > close_s2)
        ).fillna(False).astype(int)

        self.dados['Bear_Pullback'] = (
            (bull_bar == 1) & (strong_bear_s1 == 1) & (close < close_s2)
        ).fillna(False).astype(int)

        # Micro-Channel
        higher_close = self.get_series('Higher_Close')
        lower_close = self.get_series('Lower_Close')

        self.dados['Bull_Micro_Channel'] = (
            (self.get_series('Bull_Bars_3') == 1) &
            (higher_close == 1) &
            (higher_close.shift(1).fillna(0) == 1) &
            (higher_close.shift(2).fillna(0) == 1)
        ).fillna(False).astype(int)

        self.dados['Bear_Micro_Channel'] = (
            (self.get_series('Bear_Bars_3') == 1) &
            (lower_close == 1) &
            (lower_close.shift(1).fillna(0) == 1) &
            (lower_close.shift(2).fillna(0) == 1)
        ).fillna(False).astype(int)

        return self.dados

    # ------------------------------------------------------------------
    # Falhas de breakout
    # ------------------------------------------------------------------

    def identificar_falhas_breakout(self) -> pd.DataFrame:
        """Identifica falhas de breakout (oportunidades de alta probabilidade)."""
        bear_bar = self.get_series('Bear_Bar')
        bull_bar = self.get_series('Bull_Bar')
        close = self.get_series('Close')
        open_s1 = self.get_series('Open').shift(1)

        strong_bull_s1 = self.get_series('Strong_Bull_Bar').shift(1).fillna(0)
        strong_bear_s1 = self.get_series('Strong_Bear_Bar').shift(1).fillna(0)
        higher_high_s1 = self.get_series('Higher_High').shift(1).fillna(0)
        lower_low_s1 = self.get_series('Lower_Low').shift(1).fillna(0)

        self.dados['Failed_Bull_Breakout'] = (
            (bear_bar == 1) & (strong_bull_s1 == 1) &
            (higher_high_s1 == 1) & (close < open_s1)
        ).fillna(False).astype(int)

        self.dados['Failed_Bear_Breakout'] = (
            (bull_bar == 1) & (strong_bear_s1 == 1) &
            (lower_low_s1 == 1) & (close > open_s1)
        ).fillna(False).astype(int)

        return self.dados

    # ------------------------------------------------------------------
    # Geração de sinais (CORRIGIDO — agora é método da classe)
    # ------------------------------------------------------------------

    def gerar_sinais_entrada(self, contexto_tendencia: bool = True,
                             min_strength: int = 7) -> list[dict]:
        """Gera sinais de entrada baseados em padrões de price action.

        Args:
            contexto_tendencia: Se True, filtra sinais pelo contexto de tendência (EMAs).
            min_strength: Força mínima do padrão (1-10) para gerar sinal.

        Returns:
            Lista de dicionários com sinais de entrada.
        """
        dados = self.dados
        sinais = []

        if len(dados) < 2:
            return sinais

        close = self.get_series('Close')

        # ATR para stops
        if 'ATR' in dados.columns:
            atr = self.get_series('ATR')
        else:
            high = self.get_series('High')
            low = self.get_series('Low')
            close_prev = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - close_prev).abs(),
                (low - close_prev).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(window=14).mean()

        # Mapeamento padrão → (coluna, força)
        bullish_patterns = [
            ('Bullish_Pin_Bar', 'Bullish Pin Bar', 8),
            ('Bullish_Engulfing', 'Bullish Engulfing', 8),
            ('Bullish_Doji', 'Bullish Doji', 6),
            ('Bullish_Two_Bar_Reversal', 'Bullish Two Bar Reversal', 7),
            ('Failed_Bear_Breakout', 'Failed Bear Breakout', 9),
        ]
        bearish_patterns = [
            ('Bearish_Pin_Bar', 'Bearish Pin Bar', 8),
            ('Bearish_Engulfing', 'Bearish Engulfing', 8),
            ('Bearish_Doji', 'Bearish Doji', 6),
            ('Bearish_Two_Bar_Reversal', 'Bearish Two Bar Reversal', 7),
            ('Failed_Bull_Breakout', 'Failed Bull Breakout', 9),
        ]

        for i in range(1, len(dados) - 1):
            data_atual = dados.index[i]
            preco = close.iloc[i]
            atr_atual = atr.iloc[i] if not pd.isna(atr.iloc[i]) else preco * 0.01

            # ── Sinais bullish ──
            for col, desc, forca in bullish_patterns:
                if col not in dados.columns:
                    continue
                if dados[col].iloc[i] != 1 or forca < min_strength:
                    continue

                sinal_ok = True
                if contexto_tendencia:
                    sinal_ok = self._check_trend_context(dados, i, close, 'long')

                if sinal_ok:
                    sinais.append({
                        'data': data_atual,
                        'tipo': 'Compra',
                        'preco': preco,
                        'stop_loss': preco - (atr_atual * 1.5),
                        'preco_alvo': preco + (atr_atual * 3),
                        'estrategia': f'Price Action - {desc}',
                        'forca': forca,
                    })
                    break  # Um sinal por barra

            # ── Sinais bearish ──
            for col, desc, forca in bearish_patterns:
                if col not in dados.columns:
                    continue
                if dados[col].iloc[i] != 1 or forca < min_strength:
                    continue

                sinal_ok = True
                if contexto_tendencia:
                    sinal_ok = self._check_trend_context(dados, i, close, 'short')

                if sinal_ok:
                    sinais.append({
                        'data': data_atual,
                        'tipo': 'Venda',
                        'preco': preco,
                        'stop_loss': preco + (atr_atual * 1.5),
                        'preco_alvo': preco - (atr_atual * 3),
                        'estrategia': f'Price Action - {desc}',
                        'forca': forca,
                    })
                    break

        return sinais

    @staticmethod
    def _check_trend_context(dados: pd.DataFrame, i: int,
                             close: pd.Series, direction: str) -> bool:
        """Verifica se o contexto de tendência é favorável ao sinal."""
        ema_cols = [c for c in dados.columns if c.startswith('EMA_')]
        if len(ema_cols) < 2:
            return True  # Sem dados de tendência — não filtrar

        # Usar EMA_21 e EMA_55 se disponíveis, caso contrário as duas primeiras
        ema_short_col = 'EMA_21' if 'EMA_21' in dados.columns else ema_cols[0]
        ema_long_col = 'EMA_55' if 'EMA_55' in dados.columns else ema_cols[-1]

        ema_short = dados[ema_short_col].iloc[i]
        ema_long = dados[ema_long_col].iloc[i]

        if pd.isna(ema_short) or pd.isna(ema_long):
            return True

        if direction == 'long':
            return close.iloc[i] > ema_short > ema_long
        else:  # short
            return close.iloc[i] < ema_short < ema_long