import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import time

class AnalisadorMercado:
    def __init__(self, ticker, intervalo='1h', periodo='1mo'):
        self.ticker = ticker
        self.intervalo = intervalo
        self.periodo = periodo  # Using a longer period for better analysis
        self.dados = None
        self.ultimo_preco = None
        self.tendencia_atual = None
        self.sinais = []
        
    def obter_dados(self):
        """Download data from Yahoo Finance"""
        try:
            print(f"Obtendo dados para {self.ticker}...")
            data = yf.download(
                tickers=self.ticker,
                period=self.periodo,
                interval=self.intervalo,
                progress=False
            )
            
            print(f"Dados recebidos: {len(data)} períodos")
            
            if data.empty:
                print(f"Não foi possível obter dados para {self.ticker}")
                return False
            
            # Handle multi-level columns if present
            if isinstance(data.columns, pd.MultiIndex):
                new_columns = []
                for col in data.columns:
                    if isinstance(col, tuple):
                        new_columns.append('_'.join(str(x) for x in col))
                    else:
                        new_columns.append(str(col))
                
                data.columns = new_columns
            
            # Map common column names to expected names
            if 'Close' not in data.columns:
                price_columns = [col for col in data.columns if 'close' in col.lower()]
                if price_columns:
                    data['Close'] = data[price_columns[0]]
                else:
                    # As a last resort, use the first column
                    data['Close'] = data[data.columns[0]]
            
            # Store data and last price
            self.dados = data
            self.ultimo_preco = data['Close'].iloc[-1]
            return True
                
        except Exception as e:
            print(f"Erro ao obter dados: {e}")
            return False
            
    def calcular_indicadores(self):
        """Calculate technical indicators"""
        if self.dados is None or self.dados.empty:
            return False
            
        try:
            # Adjust window sizes based on available data
            data_len = len(self.dados)
            mm_window = min(20, max(5, data_len // 4))
            rsi_window = min(14, max(5, data_len // 6))
            
            # Médias Móveis
            self.dados['MM20'] = self.dados['Close'].rolling(window=mm_window).mean()
            self.dados['MM50'] = self.dados['Close'].rolling(window=min(50, max(10, data_len // 2))).mean()
            
            # Média Móvel Exponencial
            self.dados['MME9'] = self.dados['Close'].ewm(span=min(9, max(3, data_len // 10)), adjust=False).mean()
            self.dados['MME21'] = self.dados['Close'].ewm(span=min(21, max(7, data_len // 5)), adjust=False).mean()
            
            # RSI
            delta = self.dados['Close'].diff()
            ganhos = delta.copy()
            perdas = delta.copy()
            ganhos[ganhos < 0] = 0
            perdas[perdas > 0] = 0
            media_ganhos = ganhos.rolling(window=rsi_window).mean()
            media_perdas = abs(perdas.rolling(window=rsi_window).mean())
            rs = media_ganhos / media_perdas
            self.dados['RSI'] = 100 - (100 / (1 + rs))
            
            # MACD
            macd_fast = min(12, max(4, data_len // 8))
            macd_slow = min(26, max(9, data_len // 4))
            macd_signal = min(9, max(3, data_len // 10))
            
            self.dados['MACD'] = self.dados['Close'].ewm(span=macd_fast, adjust=False).mean() - self.dados['Close'].ewm(span=macd_slow, adjust=False).mean()
            self.dados['MACD_Signal'] = self.dados['MACD'].ewm(span=macd_signal, adjust=False).mean()
            
            # Bandas de Bollinger
            bb_window = min(20, max(5, data_len // 4))
            self.dados['BB_Meio'] = self.dados['Close'].rolling(window=bb_window).mean()
            std_dev = self.dados['Close'].rolling(window=bb_window).std()
            self.dados['BB_Superior'] = self.dados['BB_Meio'] + (std_dev * 2)
            self.dados['BB_Inferior'] = self.dados['BB_Meio'] - (std_dev * 2)
            
            return True
        except Exception as e:
            print(f"Erro ao calcular indicadores: {e}")
            return False
    
    def analisar_tendencia(self):
        """Analyze market trend"""
        if self.dados is None or self.dados.empty:
            return "Indeterminada"
            
        try:
            # Use the most recent row with sufficient data
            idx = -1
            while idx >= -min(len(self.dados), 30):  # Check up to 30 latest rows
                row = self.dados.iloc[idx]
                if not np.isnan(row['MM20']) and not np.isnan(row['MACD']):
                    break
                idx -= 1
            
            if idx < -min(len(self.dados), 30):
                return "Indeterminada"  # Not enough data
                
            ultimos_dados = self.dados.iloc[idx]
            
            # Pontuação para tendência
            pontuacao = 0
            
            # Análise de Médias Móveis
            if ultimos_dados['Close'] > ultimos_dados['MM20']:
                pontuacao += 1
            else:
                pontuacao -= 1
                
            # Análise de MACD
            if ultimos_dados['MACD'] > ultimos_dados['MACD_Signal']:
                pontuacao += 2
            else:
                pontuacao -= 2
                
            # Análise de RSI (if available)
            if 'RSI' in ultimos_dados and not np.isnan(ultimos_dados['RSI']):
                if ultimos_dados['RSI'] > 50:
                    pontuacao += 1
                else:
                    pontuacao -= 1
                
            # Determinar tendência
            if pontuacao >= 2:
                self.tendencia_atual = "Alta"
            elif pontuacao <= -2:
                self.tendencia_atual = "Baixa"
            else:
                self.tendencia_atual = "Lateral"
                
            return self.tendencia_atual
        except Exception as e:
            print(f"Erro ao analisar tendência: {e}")
            return "Indeterminada"
    
    def identificar_pontos_entrada(self):
        """Identify potential entry points"""
        if self.dados is None or self.dados.empty or len(self.dados) < 2:
            return []
            
        try:
            sinais = []
            
            # Use the most recent valid data
            idx_atual = -1
            idx_anterior = -2
            
            while idx_atual >= -min(len(self.dados), 30) and idx_anterior >= -min(len(self.dados), 30):
                if not np.isnan(self.dados.iloc[idx_atual]['MME9']) and not np.isnan(self.dados.iloc[idx_anterior]['MME9']):
                    break
                idx_atual -= 1
                idx_anterior = idx_atual - 1
            
            if idx_atual < -min(len(self.dados), 30) or idx_anterior < -min(len(self.dados), 30):
                return []  # Not enough valid data
                
            ultimos_dados = self.dados.iloc[idx_atual]
            dados_anteriores = self.dados.iloc[idx_anterior]
            
            tendencia = self.analisar_tendencia()
            
            # Cruzamento de Médias Móveis
            if (dados_anteriores['MME9'] <= dados_anteriores['MME21']) and (ultimos_dados['MME9'] > ultimos_dados['MME21']):
                sinais.append({
                    'tipo': 'Compra',
                    'estrategia': 'Cruzamento MM',
                    'descricao': 'MME9 cruzou para cima da MME21',
                    'forca': 'Forte' if tendencia == 'Alta' else 'Média',
                    'preco_alvo': round(ultimos_dados['Close'] * 1.01, 2),
                    'stop_loss': round(ultimos_dados['Close'] * 0.99, 2)
                })
                    
            elif (dados_anteriores['MME9'] >= dados_anteriores['MME21']) and (ultimos_dados['MME9'] < ultimos_dados['MME21']):
                sinais.append({
                    'tipo': 'Venda',
                    'estrategia': 'Cruzamento MM',
                    'descricao': 'MME9 cruzou para baixo da MME21',
                    'forca': 'Forte' if tendencia == 'Baixa' else 'Média',
                    'preco_alvo': round(ultimos_dados['Close'] * 0.99, 2),
                    'stop_loss': round(ultimos_dados['Close'] * 1.01, 2)
                })
            
            # Estratégia de RSI
            if 'RSI' in ultimos_dados and not np.isnan(ultimos_dados['RSI']):
                if ultimos_dados['RSI'] < 30 and tendencia != 'Baixa':
                    sinais.append({
                        'tipo': 'Compra',
                        'estrategia': 'RSI',
                        'descricao': 'RSI sobrevendido',
                        'forca': 'Média',
                        'preco_alvo': round(ultimos_dados['Close'] * 1.02, 2),
                        'stop_loss': round(ultimos_dados['Close'] * 0.99, 2)
                    })
                    
                if ultimos_dados['RSI'] > 70 and tendencia != 'Alta':
                    sinais.append({
                        'tipo': 'Venda',
                        'estrategia': 'RSI',
                        'descricao': 'RSI sobrecomprado',
                        'forca': 'Média',
                        'preco_alvo': round(ultimos_dados['Close'] * 0.98, 2),
                        'stop_loss': round(ultimos_dados['Close'] * 1.01, 2)
                    })
                
            self.sinais = sinais
            return sinais
        except Exception as e:
            print(f"Erro ao identificar pontos de entrada: {e}")
            return []


def analisar_mercado_tempo_real(mini_indices=True, mini_dolar=True, intervalo='1h', periodo='1mo', loop=True, intervalo_atualizacao=300):
    """Analyze Brazilian market in real time"""
    ticker_indices = "^BVSP"  # Ibovespa as proxy for Mini Índice
    ticker_dolar = "USDBRL=X"  # USD/BRL as proxy for Mini Dólar
    
    print(f"Iniciando análise de mercado em tempo real - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"Configuração: Intervalo={intervalo}, Período={periodo}")
    print(f"Tickers: Índice={ticker_indices}, Dólar={ticker_dolar}")
    
    # Initialize analyzers
    analisador_indices = AnalisadorMercado(ticker_indices, intervalo, periodo) if mini_indices else None
    analisador_dolar = AnalisadorMercado(ticker_dolar, intervalo, periodo) if mini_dolar else None
    
    def executar_analise():
        """Execute one analysis iteration"""
        print("\n" + "="*60)
        print(f"ANÁLISE DE MERCADO - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        print("="*60)
        
        if mini_indices:
            print("\n>>> MINI ÍNDICE (Ibovespa)")
            if analisador_indices.obter_dados():
                if analisador_indices.calcular_indicadores():
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
        
        if mini_dolar:
            print("\n>>> MINI DÓLAR (USD/BRL)")
            if analisador_dolar.obter_dados():
                if analisador_dolar.calcular_indicadores():
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
    
    try:
        # Run analysis once
        executar_analise()
        
        # Run in loop if requested
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
        import traceback
        traceback.print_exc()
    finally:
        print("\nAnálise de mercado finalizada.")

if __name__ == "__main__":
    analisar_mercado_tempo_real(loop=False)