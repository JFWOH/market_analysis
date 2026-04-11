# price_action_fixed.py (versão corrigida do price_action.py)
import pandas as pd
import numpy as np

class PriceActionAnalyzer:
    """Implementa padrões de price action baseados na metodologia de Al Brooks"""
    
    def __init__(self, dados):
        self.dados = dados
        
    def analisar_padroes(self):
        """Analisa todos os padrões de price action nos dados"""
        self.calcular_estrutura_barras()
        self.identificar_barras_tendencia()
        self.identificar_reversoes()
        self.identificar_continuacoes()
        self.identificar_falhas_breakout()
        return self.dados
        
    def calcular_estrutura_barras(self):
        """Calcula a estrutura básica das barras para análise de price action"""
        dados = self.dados
        
        # Garantir que estamos trabalhando com Series, não com DataFrames
        if isinstance(dados['Close'], pd.DataFrame):
            close = dados['Close'].iloc[:,0]
            open_price = dados['Open'].iloc[:,0]
            high = dados['High'].iloc[:,0]
            low = dados['Low'].iloc[:,0]
        else:
            close = dados['Close']
            open_price = dados['Open']
            high = dados['High']
            low = dados['Low']
            
        # Calcular tamanho das barras
        dados['Range'] = high - low
        dados['Body'] = abs(close - open_price)
        dados['Body_Pct'] = dados['Body'] / dados['Range']
        dados['Upper_Wick'] = high - np.maximum(open_price, close)
        dados['Lower_Wick'] = np.minimum(open_price, close) - low
        dados['Upper_Wick_Ratio'] = dados['Upper_Wick'] / dados['Range']
        dados['Lower_Wick_Ratio'] = dados['Lower_Wick'] / dados['Range']
        
        # Direção da barra
        dados['Bull_Bar'] = (close > open_price).astype(int)
        dados['Bear_Bar'] = (close < open_price).astype(int)
        dados['Doji'] = (dados['Body_Pct'] < 0.1).astype(int)  # Corpo muito pequeno
        
        # Tamanho relativo às barras anteriores
        dados['Range_MA5'] = dados['Range'].rolling(window=5).mean()
        dados['Large_Range'] = (dados['Range'] > dados['Range_MA5'] * 1.5).astype(int)
        dados['Small_Range'] = (dados['Range'] < dados['Range_MA5'] * 0.5).astype(int)
        
        # Relação com barras anteriores
        dados['Higher_High'] = (high > high.shift(1)).astype(int)
        dados['Lower_Low'] = (low < low.shift(1)).astype(int)
        dados['Higher_Close'] = (close > close.shift(1)).astype(int)
        dados['Lower_Close'] = (close < close.shift(1)).astype(int)
        
        # Barras internas/externas
        dados['Inside_Bar'] = ((high <= high.shift(1)) & (low >= low.shift(1))).astype(int)
        dados['Outside_Bar'] = ((high >= high.shift(1)) & (low <= low.shift(1))).astype(int)
        
        self.dados = dados
        return dados
    
    def identificar_barras_tendencia(self):
        """Identifica barras de tendência (trend bars) segundo Al Brooks"""
        dados = self.dados
        
        # Barra de tendência de alta (strong bull trend bar)
        dados['Strong_Bull_Bar'] = ((dados['Bull_Bar'] == 1) & 
                                 (dados['Body_Pct'] > 0.7) & 
                                 (dados['Lower_Wick_Ratio'] < 0.15)).astype(int)
        
        # Barra de tendência de baixa (strong bear trend bar)
        dados['Strong_Bear_Bar'] = ((dados['Bear_Bar'] == 1) & 
                                  (dados['Body_Pct'] > 0.7) & 
                                  (dados['Upper_Wick_Ratio'] < 0.15)).astype(int)
        
        # Shaved bar (sem sombras em uma das pontas - sinal de força)
        dados['Shaved_Top'] = (dados['Upper_Wick'] / dados['Range'] < 0.05).astype(int)
        dados['Shaved_Bottom'] = (dados['Lower_Wick'] / dados['Range'] < 0.05).astype(int)
        
        # Barras consecutivas na mesma direção (micro tendência)
        for i in range(2, 6):  # 2 a 5 barras consecutivas
            dados[f'Bull_Bars_{i}'] = 1
            dados[f'Bear_Bars_{i}'] = 1
            
            for j in range(i):
                bull_shifted = dados['Bull_Bar'].shift(j)
                bear_shifted = dados['Bear_Bar'].shift(j)
                
                # Usando & para operação bit a bit em vez de 'and' lógico
                # Também convertendo para int para garantir tipo numérico
                dados[f'Bull_Bars_{i}'] = (dados[f'Bull_Bars_{i}'] & (bull_shifted == 1)).astype(int)
                dados[f'Bear_Bars_{i}'] = (dados[f'Bear_Bars_{i}'] & (bear_shifted == 1)).astype(int)
        
        self.dados = dados
        return dados
    
    def identificar_reversoes(self):
        """Identifica padrões de reversão segundo Al Brooks"""
        dados = self.dados
        
        # === REVERSÕES DE ALTA PARA BAIXA ===
        
        # Pin Bar superior (Bearish Pin Bar)
        dados['Bearish_Pin_Bar'] = ((dados['Upper_Wick_Ratio'] > 0.6) & 
                                  (dados['Body_Pct'] < 0.3) & 
                                  (dados['Higher_High'] == 1)).astype(int)
        
        # Engolfo de alta para baixa (Bearish Engulfing)
        dados['Bearish_Engulfing'] = ((dados['Bear_Bar'] == 1) & 
                                     (dados['Bull_Bar'].shift(1) == 1) & 
                                     (dados['Open'] > dados['Close'].shift(1)) & 
                                     (dados['Close'] < dados['Open'].shift(1))).astype(int)
        
        # Doji após movimento de alta (Exhaustion)
        dados['Bearish_Doji'] = ((dados['Doji'] == 1) & 
                               (dados['Higher_High'] == 1) & 
                               (dados['Bull_Bars_3'].shift(1) == 1)).astype(int)
        
        # Two Bar Reversal (alta para baixa)
        dados['Bearish_Two_Bar_Reversal'] = ((dados['Bear_Bar'] == 1) & 
                                           (dados['Bull_Bar'].shift(1) == 1) & 
                                           (dados['Higher_High'].shift(1) == 1) & 
                                           (dados['Lower_Low'] == 1)).astype(int)
        
        # === REVERSÕES DE BAIXA PARA ALTA ===
        
        # Pin Bar inferior (Bullish Pin Bar)
        dados['Bullish_Pin_Bar'] = ((dados['Lower_Wick_Ratio'] > 0.6) & 
                                   (dados['Body_Pct'] < 0.3) & 
                                   (dados['Lower_Low'] == 1)).astype(int)
        
        # Engolfo de baixa para alta (Bullish Engulfing)
        dados['Bullish_Engulfing'] = ((dados['Bull_Bar'] == 1) & 
                                     (dados['Bear_Bar'].shift(1) == 1) & 
                                     (dados['Open'] < dados['Close'].shift(1)) & 
                                     (dados['Close'] > dados['Open'].shift(1))).astype(int)
        
        # Doji após movimento de baixa (Exhaustion)
        dados['Bullish_Doji'] = ((dados['Doji'] == 1) & 
                               (dados['Lower_Low'] == 1) & 
                               (dados['Bear_Bars_3'].shift(1) == 1)).astype(int)
        
        # Two Bar Reversal (baixa para alta)
        dados['Bullish_Two_Bar_Reversal'] = ((dados['Bull_Bar'] == 1) & 
                                           (dados['Bear_Bar'].shift(1) == 1) & 
                                           (dados['Lower_Low'].shift(1) == 1) & 
                                           (dados['Higher_High'] == 1)).astype(int)
        
        self.dados = dados
        return dados
    
    def identificar_continuacoes(self):
        """Identifica padrões de continuação segundo Al Brooks"""
        dados = self.dados
        
        # Pullback em tendência de alta
        dados['Bull_Pullback'] = ((dados['Bear_Bar'] == 1) & 
                                (dados['Strong_Bull_Bar'].shift(1) == 1) & 
                                (dados['Close'] > dados['Close'].shift(2))).astype(int)
        
        # Pullback em tendência de baixa
        dados['Bear_Pullback'] = ((dados['Bull_Bar'] == 1) & 
                                (dados['Strong_Bear_Bar'].shift(1) == 1) & 
                                (dados['Close'] < dados['Close'].shift(2))).astype(int)
        
        # Micro-Channel (3+ barras consecutivas com mesma direção sem correção)
        dados['Bull_Micro_Channel'] = ((dados['Bull_Bars_3'] == 1) & 
                                     (dados['Higher_Close'] == 1) & 
                                     (dados['Higher_Close'].shift(1) == 1) & 
                                     (dados['Higher_Close'].shift(2) == 1)).astype(int)
                                     
        dados['Bear_Micro_Channel'] = ((dados['Bear_Bars_3'] == 1) & 
                                     (dados['Lower_Close'] == 1) & 
                                     (dados['Lower_Close'].shift(1) == 1) & 
                                     (dados['Lower_Close'].shift(2) == 1)).astype(int)
        
        self.dados = dados
        return dados
    
    def identificar_falhas_breakout(self):
        """Identifica falhas de breakout (oportunidades de alta probabilidade)"""
        dados = self.dados
        
        # Falha de breakout de alta (Failed Bull Breakout)
        dados['Failed_Bull_Breakout'] = ((dados['Bear_Bar'] == 1) & 
                                       (dados['Strong_Bull_Bar'].shift(1) == 1) & 
                                       (dados['Higher_High'].shift(1) == 1) & 
                                       (dados['Close'] < dados['Open'].shift(1))).astype(int)
        
        # Falha de breakout de baixa (Failed Bear Breakout)
        dados['Failed_Bear_Breakout'] = ((dados['Bull_Bar'] == 1) & 
                                       (dados['Strong_Bear_Bar'].shift(1) == 1) & 
                                       (dados['Lower_Low'].shift(1) == 1) & 
                                       (dados['Close'] > dados['Open'].shift(1))).astype(int)
        
        self.dados = dados
        return dados
        
    def gerar_sinais_entrada(self, contexto_tendencia=True, min_strength=7):
        """Gera sinais de entrada baseados em padrões de price action"""
        # Implementação do método que gera sinais...
        # (código omitido para brevidade)