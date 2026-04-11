import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import warnings
warnings.filterwarnings('ignore')

class AnalisadorMercadoBrasileiro:
    """
    Analisador de ativos do mercado financeiro brasileiro em tempo real,
    focado em mini contratos de índice e dólar.
    """
    
    def __init__(self, ticker, intervalo='5m', periodo='1d'):
        """
        Inicializa o analisador com o ticker específico.
        
        Parâmetros:
        - ticker: str - Código do ativo (ex: "^BVSP" para Ibovespa, "BRL=X" para Dólar)
        - intervalo: str - Intervalo de tempo dos candles ('1m', '5m', '15m', '30m', '1h', '1d')
        - periodo: str - Período de análise ('1d', '5d', '1mo', '3mo')
        """
        self.ticker = ticker
        self.intervalo = intervalo
        self.periodo = periodo
        self.dados = None
        self.ultimo_preco = None
        self.tendencia_atual = None
        self.sinais = []
        
    def obter_dados(self):
        """Obtém dados históricos do ativo através da API do Yahoo Finance"""
        try:
            self.dados = yf.download(
                tickers=self.ticker,
                period=self.periodo,
                interval=self.intervalo,
                progress=False
            )
            
            # Make sure we have the expected data structure
            if isinstance(self.dados.columns, pd.MultiIndex):
            # If we have a MultiIndex (multiple columns for OHLC), flatten it
                self.dados.columns = [col[1] if isinstance(col, tuple) and len(col) > 1 else col 
                                for col in self.dados.columns]
            
            # Verificar se obteve dados
            if self.dados.empty:
                print(f"Não foi possível obter dados para {self.ticker}")
                return False
                
            # Armazenar último preço conhecido
            self.ultimo_preco = self.dados['Close'].iloc[-1]
            return True
            
        except Exception as e:
            print(f"Erro ao obter dados: {e}")
            return False
            
    def calcular_indicadores(self):
        """Calcula todos os indicadores técnicos relevantes"""
        if self.dados is None or self.dados.empty:
            return False
            
        # Médias Móveis
        self.dados['MM20'] = self.dados['Close'].rolling(window=20).mean()
        self.dados['MM50'] = self.dados['Close'].rolling(window=50).mean()
        self.dados['MM200'] = self.dados['Close'].rolling(window=200).mean()
        
        # Média Móvel Exponencial
        self.dados['MME9'] = self.dados['Close'].ewm(span=9, adjust=False).mean()
        self.dados['MME21'] = self.dados['Close'].ewm(span=21, adjust=False).mean()
        
        # RSI - Índice de Força Relativa
        delta = self.dados['Close'].diff()
        ganhos = delta.copy()
        perdas = delta.copy()
        ganhos[ganhos < 0] = 0
        perdas[perdas > 0] = 0
        periodo_rsi = 14
        media_ganhos = ganhos.rolling(window=periodo_rsi).mean()
        media_perdas = abs(perdas.rolling(window=periodo_rsi).mean())
        rs = media_ganhos / media_perdas
        self.dados['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD - Moving Average Convergence Divergence
        self.dados['MACD'] = self.dados['Close'].ewm(span=12, adjust=False).mean() - self.dados['Close'].ewm(span=26, adjust=False).mean()
        self.dados['MACD_Signal'] = self.dados['MACD'].ewm(span=9, adjust=False).mean()
        self.dados['MACD_Hist'] = self.dados['MACD'] - self.dados['MACD_Signal']
        
         # Bandas de Bollinger
        periodo_bb = 20
        desvio_padrao = 2
        self.dados['BB_Meio'] = self.dados['Close'].rolling(window=periodo_bb).mean()
        # Use .to_frame() to ensure we're working with a proper Series
        std_dev = self.dados['Close'].rolling(window=periodo_bb).std()
        self.dados['BB_Superior'] = self.dados['BB_Meio'] + (std_dev * desvio_padrao)
        self.dados['BB_Inferior'] = self.dados['BB_Meio'] - (std_dev * desvio_padrao)
        
        # ATR - Average True Range (Volatilidade)
        high_low = self.dados['High'] - self.dados['Low']
        high_close = abs(self.dados['High'] - self.dados['Close'].shift())
        low_close = abs(self.dados['Low'] - self.dados['Close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        self.dados['ATR'] = tr.rolling(window=14).mean()
        
        # Volume médio
        self.dados['Volume_Medio'] = self.dados['Volume'].rolling(window=20).mean()
        
        # Suporte e Resistência (simplificado)
        self.dados['Suporte'] = self.dados['Low'].rolling(window=10).min()
        self.dados['Resistencia'] = self.dados['High'].rolling(window=10).max()
        
        return True
    
    def analisar_tendencia(self):
        """Analisa a tendência atual do mercado baseada nos indicadores"""
        if self.dados is None or self.dados.empty:
            return "Indeterminada"
            
        # Obter dados mais recentes
        ultimos_dados = self.dados.iloc[-1]
        dados_previos = self.dados.iloc[-2] if len(self.dados) > 1 else None
        
        # Definir pontuação para tendência
        pontuacao = 0
        
        # 1. Análise de Médias Móveis
        if ultimos_dados['Close'] > ultimos_dados['MM50']:
            pontuacao += 1
        else:
            pontuacao -= 1
            
        if ultimos_dados['MM20'] > ultimos_dados['MM50']:
            pontuacao += 2
        else:
            pontuacao -= 2
            
        # 2. Análise de MACD
        if ultimos_dados['MACD'] > ultimos_dados['MACD_Signal']:
            pontuacao += 2
        else:
            pontuacao -= 2
            
        # 3. Análise de RSI
        if ultimos_dados['RSI'] > 50:
            pontuacao += 1
        else:
            pontuacao -= 1
            
        if ultimos_dados['RSI'] > 70:
            pontuacao += 0.5  # Sobrecomprado, possível reversão
        elif ultimos_dados['RSI'] < 30:
            pontuacao -= 0.5  # Sobrevendido, possível reversão
            
        # 4. Análise de Bandas de Bollinger
        if ultimos_dados['Close'] > ultimos_dados['BB_Meio']:
            pontuacao += 1
        else:
            pontuacao -= 1
            
        if ultimos_dados['Close'] > ultimos_dados['BB_Superior']:
            pontuacao += 0.5  # Possível sobrecompra
        elif ultimos_dados['Close'] < ultimos_dados['BB_Inferior']:
            pontuacao -= 0.5  # Possível sobrevenda
            
        # 5. Análise de tendência dos preços recentes (últimos 5 candles)
        precos_recentes = self.dados['Close'].iloc[-5:] if len(self.dados) >= 5 else self.dados['Close']
        if precos_recentes.is_monotonic_increasing:
            pontuacao += 2
        elif precos_recentes.is_monotonic_decreasing:
            pontuacao -= 2
            
        # Determinar tendência baseada na pontuação
        if pontuacao >= 3:
            self.tendencia_atual = "Alta"
        elif pontuacao <= -3:
            self.tendencia_atual = "Baixa"
        else:
            self.tendencia_atual = "Lateral"
            
        return self.tendencia_atual
    
    def identificar_pontos_entrada(self):
        """Identifica possíveis pontos de entrada para operações baseados em estratégias técnicas"""
        if self.dados is None or self.dados.empty:
            return []
            
        sinais = []
        ultimos_dados = self.dados.iloc[-1]
        
        # Analisar tendência atual
        tendencia = self.analisar_tendencia()
        
        # 1. Estratégia de Cruzamento de Médias Móveis (MME9 e MME21)
        dados_anteriores = self.dados.iloc[-2] if len(self.dados) > 1 else None
        if dados_anteriores is not None:
            # Cruzamento de alta (Golden Cross)
            if (dados_anteriores['MME9'] <= dados_anteriores['MME21']) and (ultimos_dados['MME9'] > ultimos_dados['MME21']):
                sinais.append({
                    'tipo': 'Compra',
                    'estrategia': 'Cruzamento MM',
                    'descricao': 'MME9 cruzou para cima da MME21',
                    'forca': 'Forte' if tendencia == 'Alta' else 'Média',
                    'preco_alvo': ultimos_dados['Close'] + (2 * ultimos_dados['ATR']),
                    'stop_loss': ultimos_dados['Close'] - ultimos_dados['ATR']
                })
                
            # Cruzamento de baixa (Death Cross)
            elif (dados_anteriores['MME9'] >= dados_anteriores['MME21']) and (ultimos_dados['MME9'] < ultimos_dados['MME21']):
                sinais.append({
                    'tipo': 'Venda',
                    'estrategia': 'Cruzamento MM',
                    'descricao': 'MME9 cruzou para baixo da MME21',
                    'forca': 'Forte' if tendencia == 'Baixa' else 'Média',
                    'preco_alvo': ultimos_dados['Close'] - (2 * ultimos_dados['ATR']),
                    'stop_loss': ultimos_dados['Close'] + ultimos_dados['ATR']
                })
        
        # 2. Estratégia de Suporte e Resistência
        if abs(ultimos_dados['Close'] - ultimos_dados['Suporte']) / ultimos_dados['Suporte'] < 0.005:
            sinais.append({
                'tipo': 'Compra',
                'estrategia': 'Suporte',
                'descricao': 'Preço tocando suporte',
                'forca': 'Média',
                'preco_alvo': ultimos_dados['Close'] * 1.01,
                'stop_loss': ultimos_dados['Suporte'] * 0.995
            })
            
        if abs(ultimos_dados['Close'] - ultimos_dados['Resistencia']) / ultimos_dados['Resistencia'] < 0.005:
            sinais.append({
                'tipo': 'Venda',
                'estrategia': 'Resistência',
                'descricao': 'Preço tocando resistência',
                'forca': 'Média',
                'preco_alvo': ultimos_dados['Close'] * 0.99,
                'stop_loss': ultimos_dados['Resistencia'] * 1.005
            })
        
        # 3. Estratégia de RSI
        if ultimos_dados['RSI'] < 30 and tendencia != 'Baixa':
            sinais.append({
                'tipo': 'Compra',
                'estrategia': 'RSI',
                'descricao': 'RSI sobrevendido',
                'forca': 'Média',
                'preco_alvo': ultimos_dados['Close'] * 1.02,
                'stop_loss': ultimos_dados['Close'] * 0.99
            })
            
        if ultimos_dados['RSI'] > 70 and tendencia != 'Alta':
            sinais.append({
                'tipo': 'Venda',
                'estrategia': 'RSI',
                'descricao': 'RSI sobrecomprado',
                'forca': 'Média',
                'preco_alvo': ultimos_dados['Close'] * 0.98,
                'stop_loss': ultimos_dados['Close'] * 1.01
            })
        
        # 4. Estratégia de MACD
        if dados_anteriores is not None:
            # Cruzamento de alta do MACD
            if (dados_anteriores['MACD'] <= dados_anteriores['MACD_Signal']) and (ultimos_dados['MACD'] > ultimos_dados['MACD_Signal']):
                sinais.append({
                    'tipo': 'Compra',
                    'estrategia': 'MACD',
                    'descricao': 'MACD cruzou para cima da linha de sinal',
                    'forca': 'Forte' if tendencia == 'Alta' else 'Média',
                    'preco_alvo': ultimos_dados['Close'] * 1.015,
                    'stop_loss': ultimos_dados['Close'] * 0.99
                })
                
            # Cruzamento de baixa do MACD
            elif (dados_anteriores['MACD'] >= dados_anteriores['MACD_Signal']) and (ultimos_dados['MACD'] < ultimos_dados['MACD_Signal']):
                sinais.append({
                    'tipo': 'Venda',
                    'estrategia': 'MACD',
                    'descricao': 'MACD cruzou para baixo da linha de sinal',
                    'forca': 'Forte' if tendencia == 'Baixa' else 'Média',
                    'preco_alvo': ultimos_dados['Close'] * 0.985,
                    'stop_loss': ultimos_dados['Close'] * 1.01
                })
        
        # 5. Estratégia de Bandas de Bollinger
        if ultimos_dados['Close'] < ultimos_dados['BB_Inferior'] and tendencia != 'Baixa':
            sinais.append({
                'tipo': 'Compra',
                'estrategia': 'Bandas de Bollinger',
                'descricao': 'Preço abaixo da banda inferior',
                'forca': 'Média',
                'preco_alvo': ultimos_dados['BB_Meio'],
                'stop_loss': ultimos_dados['Close'] * 0.99
            })
            
        if ultimos_dados['Close'] > ultimos_dados['BB_Superior'] and tendencia != 'Alta':
            sinais.append({
                'tipo': 'Venda',
                'estrategia': 'Bandas de Bollinger',
                'descricao': 'Preço acima da banda superior',
                'forca': 'Média',
                'preco_alvo': ultimos_dados['BB_Meio'],
                'stop_loss': ultimos_dados['Close'] * 1.01
            })
            
        # Armazenar sinais para referência futura
        self.sinais = sinais
        return sinais
    
    def mostrar_dashboard(self):
        """Exibe um dashboard com gráficos e indicadores técnicos"""
        if self.dados is None or self.dados.empty:
            print("Não há dados para exibir.")
            return
            
        # Configurar o gráfico principal
        fig = go.Figure()
        
        # Adicionar velas (Candlestick)
        fig.add_trace(go.Candlestick(
            x=self.dados.index,
            open=self.dados['Open'],
            high=self.dados['High'],
            low=self.dados['Low'],
            close=self.dados['Close'],
            name='Preço'
        ))
        
        # Adicionar Médias Móveis
        fig.add_trace(go.Scatter(
            x=self.dados.index,
            y=self.dados['MM20'],
            mode='lines',
            name='MM20',
            line=dict(color='blue', width=1)
        ))
        
        fig.add_trace(go.Scatter(
            x=self.dados.index,
            y=self.dados['MM50'],
            mode='lines',
            name='MM50',
            line=dict(color='orange', width=1)
        ))
        
        # Adicionar Bandas de Bollinger
        fig.add_trace(go.Scatter(
            x=self.dados.index,
            y=self.dados['BB_Superior'],
            mode='lines',
            name='BB Superior',
            line=dict(color='rgba(173, 204, 255, 0.7)', width=1)
        ))
        
        fig.add_trace(go.Scatter(
            x=self.dados.index,
            y=self.dados['BB_Inferior'],
            mode='lines',
            name='BB Inferior',
            fill='tonexty',
            fillcolor='rgba(173, 204, 255, 0.2)',
            line=dict(color='rgba(173, 204, 255, 0.7)', width=1)
        ))
        
        # Marcar pontos de entrada
        for sinal in self.sinais:
            if sinal['tipo'] == 'Compra':
                fig.add_trace(go.Scatter(
                    x=[self.dados.index[-1]],
                    y=[self.dados['Low'].iloc[-1] * 0.998],
                    mode='markers',
                    marker=dict(symbol='triangle-up', size=12, color='green'),
                    name=f"Compra: {sinal['estrategia']}"
                ))
            else:
                fig.add_trace(go.Scatter(
                    x=[self.dados.index[-1]],
                    y=[self.dados['High'].iloc[-1] * 1.002],
                    mode='markers',
                    marker=dict(symbol='triangle-down', size=12, color='red'),
                    name=f"Venda: {sinal['estrategia']}"
                ))
                
        # Configurar layout do gráfico
        fig.update_layout(
            title=f'Análise Técnica - {self.ticker} - Tendência: {self.tendencia_atual}',
            xaxis_title='Data',
            yaxis_title='Preço',
            xaxis_rangeslider_visible=False,
            template='plotly_white'
        )
        
        # Exibir gráfico
        fig.show()
        
        # Exibir indicadores e sinais
        print(f"\n=== Análise para {self.ticker} - {datetime.now().strftime('%d/%m/%Y %H:%M')} ===")
        print(f"Tendência atual: {self.tendencia_atual}")
        print(f"Último preço: {self.ultimo_preco:.2f}")
        print(f"RSI: {self.dados['RSI'].iloc[-1]:.2f}")
        print(f"Volatilidade (ATR): {self.dados['ATR'].iloc[-1]:.4f}")
        
        if self.sinais:
            print("\n--- Sinais de Operação ---")
            for sinal in self.sinais:
                print(f"Tipo: {sinal['tipo']} | Estratégia: {sinal['estrategia']} | Força: {sinal['forca']}")
                print(f"Descrição: {sinal['descricao']}")
                print(f"Preço Alvo: {sinal['preco_alvo']:.2f} | Stop Loss: {sinal['stop_loss']:.2f}")
                print("-" * 30)
        else:
            print("\nNenhum sinal de operação identificado no momento.")

# Função principal para executar a análise em tempo real
def analisar_mercado_tempo_real(mini_indices=True, mini_dolar=True, intervalo='5m', periodo='1d', loop=True, intervalo_atualizacao=300):
    print("Function called with parameters:")
    print(f"  mini_indices={mini_indices}, mini_dolar={mini_dolar}")
    print(f"  intervalo={intervalo}, periodo={periodo}")
    print(f"  loop={loop}, intervalo_atualizacao={intervalo_atualizacao}")
    
    """
    Realiza análise em tempo real dos ativos selecionados.
    
    Parâmetros:
    - mini_indices: bool - Se deve analisar o Mini Índice
    - mini_dolar: bool - Se deve analisar o Mini Dólar
    - intervalo: str - Intervalo de tempo dos candles
    - periodo: str - Período de análise
    - loop: bool - Se deve executar em loop contínuo
    - intervalo_atualizacao: int - Tempo entre atualizações em segundos
    """
    # Tickers que correspondem aproximadamente ao Mini Índice e Mini Dólar
    ticker_indices = "^BVSP"  # Ibovespa como proxy para Mini Índice
    ticker_dolar = "BRL=X"   # Taxa de câmbio como proxy para Mini Dólar
    
    print(f"Iniciando análise de mercado em tempo real - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"Configuração: Intervalo={intervalo}, Período={periodo}")
    
    # Inicializar analisadores
    analisador_indices = AnalisadorMercadoBrasileiro(ticker_indices, intervalo, periodo) if mini_indices else None
    analisador_dolar = AnalisadorMercadoBrasileiro(ticker_dolar, intervalo, periodo) if mini_dolar else None
    
    def executar_analise():
         print("Starting analysis execution...")
        """Executa uma iteração de análise para os ativos selecionados"""
        print("\n" + "="*60)
        print(f"ANÁLISE DE MERCADO - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        print("="*60)
        
        if mini_indices:
            print("\n>>> MINI ÍNDICE (Ibovespa)")
            if analisador_indices.obter_dados():
                analisador_indices.calcular_indicadores()
                tendencia = analisador_indices.analisar_tendencia()
                sinais = analisador_indices.identificar_pontos_entrada()
                
                print(f"Tendência: {tendencia}")
                print(f"Último preço: {analisador_indices.ultimo_preco:.2f}")
                
                if sinais:
                    print("\nSinais de operação encontrados:")
                    for sinal in sinais:
                        print(f"- {sinal['tipo']} ({sinal['estrategia']}): {sinal['descricao']}")
                        print(f"  Preço alvo: {sinal['preco_alvo']:.2f} | Stop: {sinal['stop_loss']:.2f}")
                else:
                    print("\nNenhum sinal de operação identificado no momento.")
                    
                # Opcional: mostrar dashboard gráfico
                # analisador_indices.mostrar_dashboard()
            else:
                print("Falha ao obter dados para o Mini Índice.")
                
        if mini_dolar:
            print("\n>>> MINI DÓLAR (USD/BRL)")
            if analisador_dolar.obter_dados():
                analisador_dolar.calcular_indicadores()
                tendencia = analisador_dolar.analisar_tendencia()
                sinais = analisador_dolar.identificar_pontos_entrada()
                
                print(f"Tendência: {tendencia}")
                print(f"Último preço: {analisador_dolar.ultimo_preco:.4f}")
                
                if sinais:
                    print("\nSinais de operação encontrados:")
                    for sinal in sinais:
                        print(f"- {sinal['tipo']} ({sinal['estrategia']}): {sinal['descricao']}")
                        print(f"  Preço alvo: {sinal['preco_alvo']:.4f} | Stop: {sinal['stop_loss']:.4f}")
                else:
                    print("\nNenhum sinal de operação identificado no momento.")
                    
                # Opcional: mostrar dashboard gráfico
                # analisador_dolar.mostrar_dashboard()
            else:
                print("Falha ao obter dados para o Mini Dólar.")
    
    try:
        # Executar uma vez independentemente
        executar_analise()
        
        # Executar em loop se solicitado
        if loop:
            print(f"\nMonitoramento contínuo ativado. Intervalo de atualização: {intervalo_atualizacao} segundos.")
            print("Pressione Ctrl+C para interromper o programa.")
            
            while True:
                time.sleep(intervalo_atualizacao)
                executar_analise()
                
    except KeyboardInterrupt:
        print("\nMonitoramento interrompido pelo usuário.")
    except Exception as e:
        print(f"\nErro na execução: {e}")
    finally:
        print("\nAnálise de mercado finalizada.")

# Exemplo de uso
if __name__ == "__main__":
    # Para executar uma única vez:
    # analisar_mercado_tempo_real(loop=False)
    
    # Para executar continuamente a cada 5 minutos:
    analisar_mercado_tempo_real(intervalo='5m', periodo='1d', intervalo_atualizacao=300)