# market_strategy.py - Arquivo unificado com todas as funcionalidades
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import time

class IndicadoresTecnicos:
    """Classe para cálculo de indicadores técnicos básicos"""
    
    @staticmethod
    def calcular_indicadores(dados):
        """Calcula todos os indicadores técnicos básicos"""
        if dados is None or dados.empty:
            return dados
            
        # Garantir que estamos trabalhando com Series
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
        
        # Médias Móveis
        dados['MM20'] = close.rolling(window=20).mean()
        dados['MM50'] = close.rolling(window=50).mean()
        
        # Médias Móveis Exponenciais
        dados['EMA_8'] = close.ewm(span=8, adjust=False).mean()
        dados['EMA_13'] = close.ewm(span=13, adjust=False).mean()
        dados['EMA_21'] = close.ewm(span=21, adjust=False).mean()
        dados['EMA_55'] = close.ewm(span=55, adjust=False).mean()
        
        # RSI - Índice de Força Relativa
        delta = close.diff()
        ganhos = delta.copy()
        perdas = delta.copy()
        ganhos[ganhos < 0] = 0
        perdas[perdas > 0] = 0
        
        media_ganhos = ganhos.rolling(window=14).mean()
        media_perdas = abs(perdas.rolling(window=14).mean())
        
        with np.errstate(divide='ignore', invalid='ignore'):
            rs = media_ganhos / media_perdas
            dados['RSI_14'] = 100 - (100 / (1 + rs))
        
        dados['RSI_14'] = dados['RSI_14'].fillna(50)
        
        # MACD - Moving Average Convergence Divergence
        dados['MACD'] = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        dados['MACD_Signal'] = dados['MACD'].ewm(span=9, adjust=False).mean()
        dados['MACD_Hist'] = dados['MACD'] - dados['MACD_Signal']
        
        # Stochastic Oscillator
        periodo_k = 14
        periodo_d = 3
        
        min_14 = low.rolling(window=periodo_k).min()
        max_14 = high.rolling(window=periodo_k).max()
        
        with np.errstate(divide='ignore', invalid='ignore'):
            stoch_k = ((close - min_14) / (max_14 - min_14)) * 100
        
        dados['Stoch_K'] = stoch_k.fillna(50)
        dados['Stoch_D'] = dados['Stoch_K'].rolling(window=periodo_d).mean().fillna(50)
        
        # ATR - Average True Range
        high_low = high - low
        high_close_prev = abs(high - close.shift(1))
        low_close_prev = abs(low - close.shift(1))
        
        true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
        dados['ATR_14'] = true_range.rolling(window=14).mean()
        
        # Bandas de Bollinger
        dados['BB_Meio'] = close.rolling(window=20).mean()
        std_dev = close.rolling(window=20).std()
        dados['BB_Superior'] = dados['BB_Meio'] + (std_dev * 2)
        dados['BB_Inferior'] = dados['BB_Meio'] - (std_dev * 2)
        
        return dados

class PriceAction:
    """Análise de padrões de price action"""
    
    @staticmethod
    def analisar_padroes(dados):
        """Analisa e identifica padrões de price action"""
        if dados is None or dados.empty:
            return dados
            
        # Extrair séries com segurança
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
        
        # Calcular estrutura das barras
        dados['Range'] = high - low
        dados['Body'] = abs(close - open_price)
        
        range_nonzero = dados['Range'].replace(0, np.nan)
        dados['Body_Pct'] = (dados['Body'] / range_nonzero).fillna(0)
        
        dados['Upper_Wick'] = high - np.maximum(open_price, close)
        dados['Lower_Wick'] = np.minimum(open_price, close) - low
        
        dados['Upper_Wick_Ratio'] = (dados['Upper_Wick'] / range_nonzero).fillna(0)
        dados['Lower_Wick_Ratio'] = (dados['Lower_Wick'] / range_nonzero).fillna(0)
        
        # Direção da barra
        dados['Bull_Bar'] = (close > open_price).fillna(False).astype(int)
        dados['Bear_Bar'] = (close < open_price).fillna(False).astype(int)
        dados['Doji'] = (dados['Body_Pct'] < 0.1).fillna(False).astype(int)
        
        # Relação com barras anteriores
        dados['Higher_High'] = (high > high.shift(1)).fillna(False).astype(int)
        dados['Lower_Low'] = (low < low.shift(1)).fillna(False).astype(int)
        dados['Higher_Close'] = (close > close.shift(1)).fillna(False).astype(int)
        dados['Lower_Close'] = (close < close.shift(1)).fillna(False).astype(int)
        
        # === PADRÕES DE PRICE ACTION ===
        
        # Barras de tendência
        strong_bull = ((dados['Bull_Bar'] == 1) & 
                     (dados['Body_Pct'] > 0.7) & 
                     (dados['Lower_Wick_Ratio'] < 0.15)).fillna(False)
        
        strong_bear = ((dados['Bear_Bar'] == 1) & 
                      (dados['Body_Pct'] > 0.7) & 
                      (dados['Upper_Wick_Ratio'] < 0.15)).fillna(False)
        
        dados['Strong_Bull_Bar'] = strong_bull.astype(int)
        dados['Strong_Bear_Bar'] = strong_bear.astype(int)
        
        # Pin Bars
        bullish_pin = ((dados['Lower_Wick_Ratio'] > 0.6) & 
                      (dados['Body_Pct'] < 0.3) & 
                      (dados['Lower_Low'] == 1)).fillna(False)
        
        bearish_pin = ((dados['Upper_Wick_Ratio'] > 0.6) & 
                      (dados['Body_Pct'] < 0.3) & 
                      (dados['Higher_High'] == 1)).fillna(False)
        
        dados['Bullish_Pin_Bar'] = bullish_pin.astype(int)
        dados['Bearish_Pin_Bar'] = bearish_pin.astype(int)
        
        # Engulfing Patterns
        bullish_engulf = ((dados['Bull_Bar'] == 1) & 
                         (dados['Bear_Bar'].shift(1).fillna(0) == 1) & 
                         (open_price < close.shift(1)) & 
                         (close > open_price.shift(1))).fillna(False)
        
        bearish_engulf = ((dados['Bear_Bar'] == 1) & 
                         (dados['Bull_Bar'].shift(1).fillna(0) == 1) & 
                         (open_price > close.shift(1)) & 
                         (close < open_price.shift(1))).fillna(False)
        
        dados['Bullish_Engulfing'] = bullish_engulf.astype(int)
        dados['Bearish_Engulfing'] = bearish_engulf.astype(int)
        
        # Two Bar Reversals
        bullish_reversal = ((dados['Bull_Bar'] == 1) & 
                           (dados['Bear_Bar'].shift(1).fillna(0) == 1) & 
                           (dados['Lower_Low'].shift(1).fillna(0) == 1) & 
                           (dados['Higher_High'] == 1)).fillna(False)
        
        bearish_reversal = ((dados['Bear_Bar'] == 1) & 
                           (dados['Bull_Bar'].shift(1).fillna(0) == 1) & 
                           (dados['Higher_High'].shift(1).fillna(0) == 1) & 
                           (dados['Lower_Low'] == 1)).fillna(False)
        
        dados['Bullish_Two_Bar_Reversal'] = bullish_reversal.astype(int)
        dados['Bearish_Two_Bar_Reversal'] = bearish_reversal.astype(int)
        
        return dados
    
    @staticmethod
    def gerar_sinais_entrada(dados, contexto_tendencia=True, min_strength=7):
        """Gera sinais de entrada baseados em padrões de price action"""
        sinais = []
        
        if dados is None or dados.empty or len(dados) < 2:
            return sinais
            
        # Extrair séries necessárias
        close = dados['Close'] if not isinstance(dados['Close'], pd.DataFrame) else dados['Close'].iloc[:,0]
        
        for i in range(1, len(dados)-1):
            data_atual = dados.index[i]
            preco = close.iloc[i]
            
            # Verificar se temos ATR para calcular stops
            if 'ATR_14' in dados.columns:
                atr = dados['ATR_14'].iloc[i]
                if pd.isna(atr):
                    atr = preco * 0.01  # Fallback se ATR for NaN
            else:
                atr = preco * 0.01  # 1% do preço como fallback
            
            # Verificar sinais de compra
            sinal_compra = False
            descricao = ""
            forca = 0
            
            # Verificar padrões bullish
            if dados['Bullish_Pin_Bar'].iloc[i] == 1:
                sinal_compra = True
                descricao = "Bullish Pin Bar"
                forca = 8
            elif dados['Bullish_Engulfing'].iloc[i] == 1:
                sinal_compra = True
                descricao = "Bullish Engulfing"
                forca = 8
            elif dados['Bullish_Two_Bar_Reversal'].iloc[i] == 1:
                sinal_compra = True
                descricao = "Bullish Two Bar Reversal"
                forca = 7
            
            # Aplicar filtros e gerar sinal de compra
            if sinal_compra and forca >= min_strength:
                # Verificar tendência se necessário
                if contexto_tendencia:
                    if 'EMA_21' in dados.columns and 'EMA_55' in dados.columns:
                        ema_21 = dados['EMA_21'].iloc[i]
                        ema_55 = dados['EMA_55'].iloc[i]
                        if pd.isna(ema_21) or pd.isna(ema_55) or not (preco > ema_21 > ema_55):
                            sinal_compra = False
                
                if sinal_compra:
                    stop_loss = preco - (atr * 1.5)
                    take_profit = preco + (atr * 3)
                    
                    sinais.append({
                        'data': data_atual,
                        'tipo': 'Compra',
                        'preco': preco,
                        'stop_loss': stop_loss,
                        'preco_alvo': take_profit,
                        'estrategia': f'Price Action - {descricao}',
                        'forca': forca
                    })
            
            # Verificar sinais de venda
            sinal_venda = False
            descricao = ""
            forca = 0
            
            # Verificar padrões bearish
            if dados['Bearish_Pin_Bar'].iloc[i] == 1:
                sinal_venda = True
                descricao = "Bearish Pin Bar"
                forca = 8
            elif dados['Bearish_Engulfing'].iloc[i] == 1:
                sinal_venda = True
                descricao = "Bearish Engulfing"
                forca = 8
            elif dados['Bearish_Two_Bar_Reversal'].iloc[i] == 1:
                sinal_venda = True
                descricao = "Bearish Two Bar Reversal"
                forca = 7
            
            # Aplicar filtros e gerar sinal de venda
            if sinal_venda and forca >= min_strength:
                # Verificar tendência se necessário
                if contexto_tendencia:
                    if 'EMA_21' in dados.columns and 'EMA_55' in dados.columns:
                        ema_21 = dados['EMA_21'].iloc[i]
                        ema_55 = dados['EMA_55'].iloc[i]
                        if pd.isna(ema_21) or pd.isna(ema_55) or not (preco < ema_21 < ema_55):
                            sinal_venda = False
                
                if sinal_venda:
                    stop_loss = preco + (atr * 1.5)
                    take_profit = preco - (atr * 3)
                    
                    sinais.append({
                        'data': data_atual,
                        'tipo': 'Venda',
                        'preco': preco,
                        'stop_loss': stop_loss,
                        'preco_alvo': take_profit,
                        'estrategia': f'Price Action - {descricao}',
                        'forca': forca
                    })
        
        return sinais

class AnalisadorSentimento:
    """Análise de sentimento do mercado"""
    
    @staticmethod
    def calcular_sentimento(dados):
        """Calcula indicadores de sentimento de mercado"""
        if dados is None or dados.empty:
            return dados
            
        # Verificar se temos os indicadores necessários
        if 'RSI_14' not in dados.columns:
            dados = IndicadoresTecnicos.calcular_indicadores(dados)
        
        # Extrair séries relevantes
        rsi = dados['RSI_14']
        stoch_k = dados['Stoch_K']
        
        # Medir extremos
        dados['Extreme_Overbought'] = ((rsi > 80) & (stoch_k > 90)).fillna(False).astype(int)
        dados['Extreme_Oversold'] = ((rsi < 20) & (stoch_k < 10)).fillna(False).astype(int)
        
        # Índice de sentimento (-100 a +100)
        dados['Sentiment_Index'] = 0.0
        
        # Cálculo simplificado de sentimento baseado em RSI e Stochastic
        for i in range(len(dados)):
            sentiment = 0
            
            # RSI (0-100) -> (-50 a +50)
            if not pd.isna(rsi.iloc[i]):
                sentiment += (rsi.iloc[i] - 50)
            
            # Stochastic K (0-100) -> (-50 a +50)
            if not pd.isna(stoch_k.iloc[i]):
                sentiment += (stoch_k.iloc[i] - 50) * 0.5
            
            # Normalizar para -100 a +100
            sentiment = max(-100, min(100, sentiment))
            dados.loc[dados.index[i], 'Sentiment_Index'] = sentiment
        
        # Classificar zonas de sentimento
        dados['Bullish_Sentiment'] = (dados['Sentiment_Index'] > 30).fillna(False).astype(int)
        dados['Bearish_Sentiment'] = (dados['Sentiment_Index'] < -30).fillna(False).astype(int)
        
        return dados
    
    @staticmethod
    def gerar_sinais_sentimento(dados, threshold=50):
        """Gera sinais baseados em mudanças de sentimento"""
        sinais = []
        
        if dados is None or dados.empty or len(dados) < 5:
            return sinais
            
        # Verificar se temos o índice de sentimento
        if 'Sentiment_Index' not in dados.columns:
            dados = AnalisadorSentimento.calcular_sentimento(dados)
        
        # Extrair séries relevantes
        sentiment = dados['Sentiment_Index']
        close = dados['Close'] if not isinstance(dados['Close'], pd.DataFrame) else dados['Close'].iloc[:,0]
        
        for i in range(5, len(dados)):
            data_atual = dados.index[i]
            preco = close.iloc[i]
            
            # Calcular média do sentimento anterior
            sentimento_anterior = sentiment.iloc[i-5:i-1].mean()
            sentimento_atual = sentiment.iloc[i]
            
            # Verificar mudanças significativas de sentimento
            mudanca_para_altista = (sentimento_anterior < -threshold) and (sentimento_atual > 0)
            mudanca_para_baixista = (sentimento_anterior > threshold) and (sentimento_atual < 0)
            
            # Calcular ATR para stops
            if 'ATR_14' in dados.columns:
                atr = dados['ATR_14'].iloc[i]
                if pd.isna(atr):
                    atr = preco * 0.01
            else:
                atr = preco * 0.01
            
            # Gerar sinais baseados em mudanças de sentimento
            if mudanca_para_altista:
                sinais.append({
                    'data': data_atual,
                    'tipo': 'Compra',
                    'preco': preco,
                    'stop_loss': preco - (atr * 1.5),
                    'preco_alvo': preco + (atr * 3),
                    'estrategia': 'Reversão de Sentimento Altista',
                    'forca': 8
                })
            
            if mudanca_para_baixista:
                sinais.append({
                    'data': data_atual,
                    'tipo': 'Venda',
                    'preco': preco,
                    'stop_loss': preco + (atr * 1.5),
                    'preco_alvo': preco - (atr * 3),
                    'estrategia': 'Reversão de Sentimento Baixista',
                    'forca': 8
                })
        
        return sinais

class EstrategiaAvancada:
    """Estratégia de trading avançada combinando price action e sentimento"""
    
    def __init__(self, ticker="", intervalo='1h', periodo='1mo', params=None):
        self.ticker = ticker
        self.intervalo = intervalo
        self.periodo = periodo
        self.dados = None
        
        # Parâmetros padrão
        self.params = {
            'ema_curta': 8,
            'ema_media': 21,
            'ema_longa': 55,
            'atr_multiplicador_sl': 1.5,
            'atr_multiplicador_tp': 3.0,
            'filtro_tendencia': True,
            'filtro_sentimento': True,
            'min_price_action_strength': 7,
            'min_sentiment_score': 30
        }
        
        # Substituir por parâmetros customizados
        if params:
            for key, value in params.items():
                self.params[key] = value
    
    def obter_dados(self, inicio='1mo'):
        """Obtém dados históricos para o ativo"""
        if not self.ticker:
            print("Ticker não especificado")
            return False
            
        try:
            dados = yf.download(
                tickers=self.ticker,
                period=inicio,
                interval=self.intervalo,
                progress=False
            )
            
            if dados.empty:
                print(f"Sem dados para {self.ticker}")
                return False
                
            self.dados = dados
            return True
        except Exception as e:
            print(f"Erro ao obter dados: {e}")
            return False
    
    def preparar_dados(self, dados_externos=None):
        """Prepara todos os dados com indicadores e padrões"""
        # Usar dados externos ou dados da classe
        dados = dados_externos if dados_externos is not None else self.dados
        
        if dados is None or dados.empty:
            return None
            
        # Calcular indicadores técnicos
        dados = IndicadoresTecnicos.calcular_indicadores(dados)
        
        # Analisar padrões de price action
        dados = PriceAction.analisar_padroes(dados)
        
        # Calcular sentimento
        dados = AnalisadorSentimento.calcular_sentimento(dados)
        
        # Atualizar dados da classe se não foram fornecidos dados externos
        if dados_externos is None:
            self.dados = dados
            
        return dados
    
    def gerar_sinais(self, dados_externos=None):
        """Gera sinais de trading combinando todas as estratégias"""
        # Usar dados externos ou dados da classe
        dados = dados_externos if dados_externos is not None else self.dados
        
        if dados is None or dados.empty:
            return []
            
        # Preparar dados se necessário
        if 'RSI_14' not in dados.columns:
            dados = self.preparar_dados(dados)
        
        # Obter sinais de price action
        sinais_price_action = PriceAction.gerar_sinais_entrada(
            dados, 
            contexto_tendencia=self.params['filtro_tendencia'],
            min_strength=self.params['min_price_action_strength']
        )
        
        # Obter sinais de sentimento
        sinais_sentimento = AnalisadorSentimento.gerar_sinais_sentimento(
            dados,
            threshold=self.params['min_sentiment_score']
        )
        
        # Combinar todos os sinais
        todos_sinais = sinais_price_action + sinais_sentimento
        
        # Filtro adicional de sentimento se ativado
        if self.params['filtro_sentimento'] and len(todos_sinais) > 0:
            sinais_filtrados = []
            for sinal in todos_sinais:
                data_idx = dados.index.get_loc(sinal['data'])
                sentimento = dados['Sentiment_Index'].iloc[data_idx]
                
                # Para sinais de compra, verificar sentimento positivo
                if sinal['tipo'] == 'Compra' and sentimento < 0:
                    continue
                    
                # Para sinais de venda, verificar sentimento negativo
                if sinal['tipo'] == 'Venda' and sentimento > 0:
                    continue
                    
                sinais_filtrados.append(sinal)
                
            todos_sinais = sinais_filtrados
            
        return todos_sinais
    
    def executar_backtest(self, capital_inicial=100000.0, dados_externos=None):
        """Executa backtest da estratégia"""
        # Usar dados externos ou dados da classe
        dados = dados_externos if dados_externos is not None else self.dados
        
        if dados is None or dados.empty:
            return None
            
        # Preparar dados se necessário
        if 'RSI_14' not in dados.columns:
            dados = self.preparar_dados(dados)
        
        # Gerar sinais
        sinais = self.gerar_sinais(dados)
        
        # Variáveis para tracking
        capital = capital_inicial
        posicoes = []
        trades_concluidos = []
        equity = [capital]
        datas_equity = [dados.index[0]]
        
        # Simular trading
        for i in range(1, len(dados)):
            data_atual = dados.index[i]
            preco_atual = dados['Close'].iloc[i]
            
            if isinstance(preco_atual, pd.Series):
                preco_atual = preco_atual.iloc[0]
            
            # Atualizar posições existentes
            novas_posicoes = []
            for pos in posicoes:
                # Verificar se atingiu stop ou alvo
                if pos['tipo'] == 'Compra':
                    # Stop loss
                    if dados['Low'].iloc[i] <= pos['stop_loss']:
                        resultado = (pos['stop_loss'] / pos['preco'] - 1) * pos['valor']
                        capital += pos['valor'] + resultado
                        
                        trades_concluidos.append({
                            'entrada': pos['data'],
                            'saida': data_atual,
                            'tipo': pos['tipo'],
                            'preco_entrada': pos['preco'],
                            'preco_saida': pos['stop_loss'],
                            'resultado': resultado,
                            'motivo': 'Stop Loss',
                            'estrategia': pos['estrategia']
                        })
                    # Take profit
                    elif dados['High'].iloc[i] >= pos['preco_alvo']:
                        resultado = (pos['preco_alvo'] / pos['preco'] - 1) * pos['valor']
                        capital += pos['valor'] + resultado
                        
                        trades_concluidos.append({
                            'entrada': pos['data'],
                            'saida': data_atual,
                            'tipo': pos['tipo'],
                            'preco_entrada': pos['preco'],
                            'preco_saida': pos['preco_alvo'],
                            'resultado': resultado,
                            'motivo': 'Take Profit',
                            'estrategia': pos['estrategia']
                        })
                    else:
                        # Manter posição
                        novas_posicoes.append(pos)
                
                elif pos['tipo'] == 'Venda':
                    # Stop loss
                    if dados['High'].iloc[i] >= pos['stop_loss']:
                        resultado = (pos['preco'] / pos['stop_loss'] - 1) * pos['valor']
                        capital += pos['valor'] + resultado
                        
                        trades_concluidos.append({
                            'entrada': pos['data'],
                            'saida': data_atual,
                            'tipo': pos['tipo'],
                            'preco_entrada': pos['preco'],
                            'preco_saida': pos['stop_loss'],
                            'resultado': resultado,
                            'motivo': 'Stop Loss',
                            'estrategia': pos['estrategia']
                        })
                    # Take profit
                    elif dados['Low'].iloc[i] <= pos['preco_alvo']:
                        resultado = (pos['preco'] / pos['preco_alvo'] - 1) * pos['valor']
                        capital += pos['valor'] + resultado
                        
                        trades_concluidos.append({
                            'entrada': pos['data'],
                            'saida': data_atual,
                            'tipo': pos['tipo'],
                            'preco_entrada': pos['preco'],
                            'preco_saida': pos['preco_alvo'],
                            'resultado': resultado,
                            'motivo': 'Take Profit',
                            'estrategia': pos['estrategia']
                        })
                    else:
                        # Manter posição
                        novas_posicoes.append(pos)
            
            # Atualizar lista de posições
            posicoes = novas_posicoes
            
            # Verificar por novos sinais
            for sinal in sinais:
                if sinal['data'] == data_atual:
                    # Calcular valor da operação (10% do capital ou R$10.000, o que for menor)
                    valor_operacao = min(capital * 0.1, 10000)
                    
                    if valor_operacao >= 1000:  # Mínimo de R$1.000 por operação
                        # Adicionar nova posição
                        posicoes.append({
                            'data': data_atual,
                            'tipo': sinal['tipo'],
                            'preco': preco_atual,
                            'stop_loss': sinal['stop_loss'],
                            'preco_alvo': sinal['preco_alvo'],
                            'valor': valor_operacao,
                            'estrategia': sinal['estrategia']
                        })
                        
                        # Deduzir capital
                        capital -= valor_operacao
            
            # Atualizar equity curve
            equity.append(capital + sum(pos['valor'] for pos in posicoes))
            datas_equity.append(data_atual)
        
        # Fechar posições restantes
        for pos in posicoes:
            # Calcular resultado com último preço disponível
            ultimo_preco = dados['Close'].iloc[-1]
            if isinstance(ultimo_preco, pd.Series):
                ultimo_preco = ultimo_preco.iloc[0]
                
            if pos['tipo'] == 'Compra':
                resultado = (ultimo_preco / pos['preco'] - 1) * pos['valor']
            else:  # Venda
                resultado = (pos['preco'] / ultimo_preco - 1) * pos['valor']
                
            capital += pos['valor'] + resultado
            
            trades_concluidos.append({
                'entrada': pos['data'],
                'saida': dados.index[-1],
                'tipo': pos['tipo'],
                'preco_entrada': pos['preco'],
                'preco_saida': ultimo_preco,
                'resultado': resultado,
                'motivo': 'Fim do Backtesting',
                'estrategia': pos['estrategia']
            })
        
        # Calcular métricas
        retorno_total = capital / capital_inicial - 1
        win_rate = sum(1 for t in trades_concluidos if t['resultado'] > 0) / max(1, len(trades_concluidos))
        
        # Calcular drawdown
        picos = pd.Series(equity).cummax()
        drawdowns = (pd.Series(equity) / picos - 1) * 100
        max_drawdown = abs(drawdowns.min())
        
        # Resultado
        return {
            'capital_inicial': capital_inicial,
            'capital_final': capital,
            'retorno_total': retorno_total,
            'trades': trades_concluidos,
            'num_trades': len(trades_concluidos),
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'equity': equity,
            'datas_equity': datas_equity
        }

# Função para executar otimização
def otimizar_estrategia(ticker, nome_ativo, periodo_inicio='2022-01-01', periodo_fim='2023-12-31', intervalo='1d'):
    """Otimiza parâmetros da estratégia para um ativo específico"""
    print(f"Otimizando estratégia para {nome_ativo}...")
    
    # Baixar dados para o período de treino
    try:
        dados_treino = yf.download(
            tickers=ticker,
            start=periodo_inicio,
            end=periodo_fim,
            interval=intervalo,
            progress=False
        )
        
        print(f"Dados obtidos: {len(dados_treino)} períodos")
        
        if dados_treino.empty:
            print(f"Sem dados para {ticker}")
            return None
    except Exception as e:
        print(f"Erro ao obter dados: {e}")
        return None
    
    # Definir grid de parâmetros para testar
    parametros_grid = [
        # ema_curta, ema_media, ema_longa, filtro_tendencia, min_strength
        {'ema_curta': 8, 'ema_media': 21, 'ema_longa': 55, 'filtro_tendencia': True, 'min_price_action_strength': 7},
        {'ema_curta': 8, 'ema_media': 21, 'ema_longa': 55, 'filtro_tendencia': False, 'min_price_action_strength': 7},
        {'ema_curta': 9, 'ema_media': 21, 'ema_longa': 55, 'filtro_tendencia': True, 'min_price_action_strength': 7},
        {'ema_curta': 9, 'ema_media': 21, 'ema_longa': 55, 'filtro_tendencia': False, 'min_price_action_strength': 7},
        {'ema_curta': 8, 'ema_media': 21, 'ema_longa': 55, 'filtro_tendencia': True, 'min_price_action_strength': 6},
        {'ema_curta': 8, 'ema_media': 21, 'ema_longa': 55, 'filtro_tendencia': False, 'min_price_action_strength': 6},
        {'ema_curta': 9, 'ema_media': 21, 'ema_longa': 55, 'filtro_tendencia': True, 'min_price_action_strength': 6},
        {'ema_curta': 9, 'ema_media': 21, 'ema_longa': 55, 'filtro_tendencia': False, 'min_price_action_strength': 6},
    ]
    
    # Testar cada combinação
    resultados = []
    
    for i, params in enumerate(parametros_grid):
        print(f"Testando combinação {i+1}/{len(parametros_grid)}: {params}")
        
        # Instanciar estratégia com estes parâmetros
        estrategia = EstrategiaAvancada(ticker=ticker, params=params)
        
        # Preparar dados
        dados_preparados = estrategia.preparar_dados(dados_treino)
        
        if dados_preparados is None:
            print("Erro ao preparar dados")
            continue
        
        # Executar backtest
        resultado = estrategia.executar_backtest(dados_externos=dados_preparados)
        
        if resultado:
            resultado['params'] = params
            resultados.append(resultado)
            print(f"Resultado: Retorno {resultado['retorno_total']:.2%}, Win Rate: {resultado['win_rate']:.2%}, Trades: {resultado['num_trades']}")
    
    # Ordenar resultados por retorno total
    resultados.sort(key=lambda x: x['retorno_total'], reverse=True)
    
    # Mostrar melhores resultados
    print("\n=== MELHORES RESULTADOS ===")
    for i, res in enumerate(resultados[:3]):
        print(f"{i+1}. Retorno: {res['retorno_total']:.2%}, Win Rate: {res['win_rate']:.2%}, Drawdown: {res['max_drawdown']:.2%}")
        print(f"   Parâmetros: {res['params']}")
    
    # Retornar melhores parâmetros
    return resultados[0]['params'] if resultados else None