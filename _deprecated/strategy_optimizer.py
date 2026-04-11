# strategy_optimizer.py
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import yfinance as yf
from datetime import datetime
import os
import itertools
from market_analyzer import AnalisadorMercado

class OtimizadorEstrategia:
    def __init__(self, ticker, nome_ativo, periodo_inicio='2021-01-01', periodo_fim='2023-12-31'):
        """Inicializa o otimizador com parâmetros básicos"""
        self.ticker = ticker
        self.nome_ativo = nome_ativo
        self.periodo_inicio = periodo_inicio
        self.periodo_fim = periodo_fim
        self.dados = None
        self.parametros_otimos = {}
        self.melhor_resultado = -9999
        self.resultados_grid = []
        
    def obter_dados(self, intervalo='1d'):
        """Obtém dados históricos mais extensos para testes robustos"""
        print(f"Baixando dados históricos para {self.nome_ativo}...")
        try:
            dados = yf.download(
                tickers=self.ticker,
                start=self.periodo_inicio,
                end=self.periodo_fim,
                interval=intervalo,
                progress=False
            )
            
            # Tratar dados, lidar com colunas, etc.
            # (código de tratamento de dados aqui)
            
            self.dados = dados
            print(f"Dados obtidos: {len(dados)} períodos")
            return True
            
        except Exception as e:
            print(f"Erro ao obter dados: {e}")
            return False
    
    def adicionar_indicadores_avancados(self):
        """Adiciona indicadores avançados aos dados"""
        if self.dados is None:
            return False
            
        dados = self.dados.copy()
        
        # === INDICADORES DE MOMENTUM ===
        # RSI com múltiplos períodos
        for periodo in [7, 14, 21]:
            delta = dados['Close'].diff()
            ganhos = delta.copy()
            perdas = delta.copy()
            ganhos[ganhos < 0] = 0
            perdas[perdas > 0] = 0
            media_ganhos = ganhos.rolling(window=periodo).mean()
            media_perdas = abs(perdas.rolling(window=periodo).mean())
            rs = media_ganhos / media_perdas
            dados[f'RSI_{periodo}'] = 100 - (100 / (1 + rs))
        
        # Stochastic Oscillator
        periodo_k = 14
        periodo_d = 3
        dados['Stoch_K'] = 100 * ((dados['Close'] - dados['Low'].rolling(window=periodo_k).min()) / 
                                 (dados['High'].rolling(window=periodo_k).max() - 
                                  dados['Low'].rolling(window=periodo_k).min()))
        dados['Stoch_D'] = dados['Stoch_K'].rolling(window=periodo_d).mean()
        
        # === INDICADORES DE TENDÊNCIA ===
        # Múltiplas Médias Móveis EMAs
        for periodo in [8, 13, 21, 34, 55, 89]:  # Sequência Fibonacci
            dados[f'EMA_{periodo}'] = dados['Close'].ewm(span=periodo, adjust=False).mean()
        
        # === INDICADORES DE VOLATILIDADE ===
        # ATR - Average True Range
        alto_baixo = dados['High'] - dados['Low']
        alto_fechamento = abs(dados['High'] - dados['Close'].shift())
        baixo_fechamento = abs(dados['Low'] - dados['Close'].shift())
        tr = pd.concat([alto_baixo, alto_fechamento, baixo_fechamento], axis=1).max(axis=1)
        dados['ATR_14'] = tr.rolling(window=14).mean()
        
        # Bollinger Bands com diferentes desvios
        for periodo, desvio in [(20, 2), (20, 3), (50, 2)]:
            dados[f'BB_Meio_{periodo}'] = dados['Close'].rolling(window=periodo).mean()
            std_dev = dados['Close'].rolling(window=periodo).std()
            dados[f'BB_Superior_{periodo}_{desvio}'] = dados[f'BB_Meio_{periodo}'] + (std_dev * desvio)
            dados[f'BB_Inferior_{periodo}_{desvio}'] = dados[f'BB_Meio_{periodo}'] - (std_dev * desvio)
        
        # === INDICADORES DE VOLUME ===
        if 'Volume' in dados.columns:
            # Volume Force Index
            dados['Force_Index_13'] = dados['Close'].diff() * dados['Volume']
            dados['Force_Index_13'] = dados['Force_Index_13'].ewm(span=13, adjust=False).mean()
            
            # On-Balance Volume (OBV)
            dados['OBV'] = np.where(dados['Close'] > dados['Close'].shift(), 
                                   dados['Volume'], 
                                   np.where(dados['Close'] < dados['Close'].shift(), 
                                           -dados['Volume'], 0)).cumsum()
        
        # === INDICADORES DE PRICE ACTION (Al Brooks) ===
        # Barras de Tendência
        dados['Range'] = dados['High'] - dados['Low']
        dados['Body'] = abs(dados['Close'] - dados['Open'])
        dados['Body_Pct'] = dados['Body'] / dados['Range']
        dados['Trend_Bar'] = dados['Body_Pct'] > 0.6  # Barra de tendência forte
        
        # Inversão de 2 barras
        dados['Higher_High'] = dados['High'] > dados['High'].shift()
        dados['Lower_Low'] = dados['Low'] < dados['Low'].shift()
        dados['Higher_Close'] = dados['Close'] > dados['Close'].shift()
        dados['Lower_Close'] = dados['Close'] < dados['Close'].shift()
        
        # Padrão de Pin Bar (Price Rejection)
        dados['Upper_Wick'] = dados['High'] - np.maximum(dados['Open'], dados['Close'])
        dados['Lower_Wick'] = np.minimum(dados['Open'], dados['Close']) - dados['Low']
        dados['Upper_Wick_Ratio'] = dados['Upper_Wick'] / dados['Range']
        dados['Lower_Wick_Ratio'] = dados['Lower_Wick'] / dados['Range']
        
        # Pin Bar superior (potencial reversão de alta para baixa)
        dados['Pin_Bar_Top'] = (dados['Upper_Wick_Ratio'] > 0.6) & (dados['Body_Pct'] < 0.3)
        
        # Pin Bar inferior (potencial reversão de baixa para alta)
        dados['Pin_Bar_Bottom'] = (dados['Lower_Wick_Ratio'] > 0.6) & (dados['Body_Pct'] < 0.3)
        
        # Inside Bar (barra interna)
        dados['Inside_Bar'] = (dados['High'] < dados['High'].shift()) & (dados['Low'] > dados['Low'].shift())
        
        # Outside Bar (barra externa)
        dados['Outside_Bar'] = (dados['High'] > dados['High'].shift()) & (dados['Low'] < dados['Low'].shift())
        
        # Barra de reversão após tendência (setup de entrada Al Brooks)
        dados['Reversal_Bar_Up'] = dados['Pin_Bar_Bottom'] & dados['Lower_Low'] & dados['Higher_Close']
        dados['Reversal_Bar_Down'] = dados['Pin_Bar_Top'] & dados['Higher_High'] & dados['Lower_Close']
        
        # === INDICADORES DE SENTIMENTO DE MERCADO ===
        # Volatilidade Relativa
        dados['Volatility_Ratio'] = dados['ATR_14'] / dados['ATR_14'].rolling(window=90).mean()
        
        # Momentum relativo de força
        dados['RSI_Trend'] = dados['RSI_14'] - dados['RSI_14'].rolling(window=5).mean()
        
        self.dados = dados
        return True
    
    def executar_grid_search(self, parametros_grid):
        """Executa uma busca em grade para encontrar os melhores parâmetros"""
        print("Iniciando otimização de parâmetros...")
        
        # Criar todas as combinações possíveis de parâmetros
        chaves_params = list(parametros_grid.keys())
        combinacoes = list(itertools.product(*[parametros_grid[k] for k in chaves_params]))
        
        total_combinacoes = len(combinacoes)
        print(f"Testando {total_combinacoes} combinações de parâmetros...")
        
        # Testar cada combinação
        for i, valores in enumerate(combinacoes):
            parametros = dict(zip(chaves_params, valores))
            print(f"Teste {i+1}/{total_combinacoes}: {parametros}")
            
            # Executar backtest com estes parâmetros
            retorno, trades, sharpe = self.executar_backtest(parametros)
            
            resultado = {
                'parametros': parametros,
                'retorno': retorno,
                'num_trades': len(trades),
                'win_rate': sum(1 for t in trades if t['resultado'] > 0) / len(trades) if trades else 0,
                'sharpe': sharpe
            }
            
            self.resultados_grid.append(resultado)
            
            # Atualizar melhor resultado
            if retorno > self.melhor_resultado:
                self.melhor_resultado = retorno
                self.parametros_otimos = parametros
                
        # Ordenar resultados
        self.resultados_grid = sorted(self.resultados_grid, key=lambda x: x['retorno'], reverse=True)
        
        # Mostrar melhores resultados
        print("\n=== TOP 5 MELHORES COMBINAÇÕES ===")
        for i, res in enumerate(self.resultados_grid[:5]):
            print(f"{i+1}. Retorno: {res['retorno']:.2%}, Win Rate: {res['win_rate']:.2%}, Trades: {res['num_trades']}")
            print(f"   Parâmetros: {res['parametros']}")
            
        return self.parametros_otimos, self.melhor_resultado
    
    def executar_backtest(self, parametros):
        """Executa um backtest com os parâmetros fornecidos"""
        # Implementar aqui o código de backtesting com os parâmetros específicos
        # Retornar retorno percentual, lista de trades e Sharpe ratio
        pass
    
    def plotar_resultados_grid(self):
        """Gera visualizações dos resultados da otimização"""
        plt.figure(figsize=(12, 8))
        
        # Extrair dados para o gráfico
        retornos = [r['retorno'] * 100 for r in self.resultados_grid]
        win_rates = [r['win_rate'] * 100 for r in self.resultados_grid]
        num_trades = [r['num_trades'] for r in self.resultados_grid]
        
        # Tamanho dos pontos proporcional ao número de trades
        sizes = [max(20, min(200, n*2)) for n in num_trades]
        
        # Colormap baseado no retorno
        colors = retornos
        
        # Scatter plot
        scatter = plt.scatter(win_rates, retornos, s=sizes, c=colors, 
                             alpha=0.7, cmap='viridis')
        
        plt.colorbar(scatter, label='Retorno (%)')
        plt.xlabel('Taxa de Acerto (%)')
        plt.ylabel('Retorno Total (%)')
        plt.title('Relação entre Win Rate e Retorno (tamanho = número de trades)')
        plt.grid(True, alpha=0.3)
        
        # Marcar o melhor resultado
        melhor_idx = retornos.index(max(retornos))
        plt.scatter([win_rates[melhor_idx]], [retornos[melhor_idx]], 
                   s=200, c='red', marker='*', edgecolors='black')
        
        # Salvar gráfico
        plt.savefig(f'otimizacao_{self.nome_ativo}.png')
        
        return True