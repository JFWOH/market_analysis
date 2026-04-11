import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import time

class AnalisadorMercado:
    def __init__(self, ticker, intervalo='5m', periodo='1d'):
        self.ticker = ticker
        self.intervalo = intervalo
        self.periodo = periodo
        self.dados = None
        self.ultimo_preco = None
        self.tendencia_atual = None
        self.sinais = []
        
    def obter_dados(self):
        """Download data from Yahoo Finance"""
        try:
            print(f"Tentando obter dados para {self.ticker}...")
            data = yf.download(
                tickers=self.ticker,
                period=self.periodo,
                interval=self.intervalo,
                progress=False
            )
            
            print(f"Dados recebidos para {self.ticker}. Formato: {data.shape}")
            
            if data.empty:
                print(f"Não foi possível obter dados para {self.ticker}")
                return False
            
            # Print original columns for debugging
            print("Colunas originais:", data.columns.tolist())
            
            # Handle multi-level columns if present
            if isinstance(data.columns, pd.MultiIndex):
                print("Detectado MultiIndex nas colunas. Ajustando...")
                
                # Print the first few items to see the structure
                print("Estrutura MultiIndex:", [str(col) for col in data.columns[:2]])
                
                # Try a different approach for flattening
                new_columns = []
                for col in data.columns:
                    if isinstance(col, tuple):
                        # Join the tuple elements with underscore
                        new_columns.append('_'.join(str(x) for x in col))
                    else:
                        new_columns.append(str(col))
                
                data.columns = new_columns
            
            print("Colunas após ajuste:", data.columns.tolist())
            
            # Map common column names to expected names
            column_mapping = {
                'Adj Close': 'Close',
                'Adj_Close': 'Close',
                'CLOSE': 'Close',
                'close': 'Close',
                # Add more as needed
            }
            
            for old_name, new_name in column_mapping.items():
                if old_name in data.columns and new_name not in data.columns:
                    print(f"Renomeando coluna {old_name} para {new_name}")
                    data[new_name] = data[old_name]
            
            # If we still don't have a 'Close' column, try to find a suitable one
            if 'Close' not in data.columns:
                price_columns = [col for col in data.columns if any(term in col.lower() for term in ['close', 'adj', 'last', 'preço', 'price'])]
                if price_columns:
                    print(f"Coluna 'Close' não encontrada. Usando '{price_columns[0]}' como 'Close'")
                    data['Close'] = data[price_columns[0]]
                else:
                    # As a last resort, use the first column
                    print(f"Nenhuma coluna de preço encontrada! Usando primeira coluna '{data.columns[0]}' como 'Close'")
                    data['Close'] = data[data.columns[0]]
            
            # Store data and last price
            self.dados = data
            self.ultimo_preco = data['Close'].iloc[-1]
            print(f"Último preço obtido: {self.ultimo_preco}")
            return True
                
        except Exception as e:
            print(f"Erro ao obter dados: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def calcular_indicadores(self):
        """Calculate technical indicators"""
        if self.dados is None or self.dados.empty:
            print("Sem dados para calcular indicadores")
            return False
            
        try:
            # Print all columns to ensure we have what we need
            print("Calculando indicadores. Colunas disponíveis:", self.dados.columns.tolist())
            
            # Médias Móveis
            self.dados['MM20'] = self.dados['Close'].rolling(window=20).mean()
            self.dados['MM50'] = self.dados['Close'].rolling(window=50).mean()
            
            # Média Móvel Exponencial
            self.dados['MME9'] = self.dados['Close'].ewm(span=9, adjust=False).mean()
            self.dados['MME21'] = self.dados['Close'].ewm(span=21, adjust=False).mean()
            
            # RSI
            delta = self.dados['Close'].diff()
            ganhos = delta.copy()
            perdas = delta.copy()
            ganhos[ganhos < 0] = 0
            perdas[perdas > 0] = 0
            media_ganhos = ganhos.rolling(window=14).mean()
            media_perdas = abs(perdas.rolling(window=14).mean())
            rs = media_ganhos / media_perdas
            self.dados['RSI'] = 100 - (100 / (1 + rs))
            
            # MACD
            self.dados['MACD'] = self.dados['Close'].ewm(span=12, adjust=False).mean() - self.dados['Close'].ewm(span=26, adjust=False).mean()
            self.dados['MACD_Signal'] = self.dados['MACD'].ewm(span=9, adjust=False).mean()
            
            # Bandas de Bollinger
            self.dados['BB_Meio'] = self.dados['Close'].rolling(window=20).mean()
            std_dev = self.dados['Close'].rolling(window=20).std()
            self.dados['BB_Superior'] = self.dados['BB_Meio'] + (std_dev * 2)
            self.dados['BB_Inferior'] = self.dados['BB_Meio'] - (std_dev * 2)
            
            print("Indicadores calculados com sucesso")
            return True
        except Exception as e:
            print(f"Erro ao calcular indicadores: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def analisar_tendencia(self):
        """Analyze market trend"""
        if self.dados is None or self.dados.empty:
            return "Indeterminada"
            
        try:
            # Use the most recent row with complete data
            idx = -1
            while idx >= -len(self.dados):
                row = self.dados.iloc[idx]
                if not np.isnan(row['MM20']) and not np.isnan(row['RSI']) and not np.isnan(row['MACD']):
                    break
                idx -= 1
            
            if idx < -len(self.dados):
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
                
            # Análise de RSI
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
            import traceback
            traceback.print_exc()
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
            
            while idx_atual >= -len(self.dados):
                if not np.isnan(self.dados.iloc[idx_atual]['MME9']) and not np.isnan(self.dados.iloc[idx_atual]['RSI']):
                    break
                idx_atual -= 1
                idx_anterior = idx_atual - 1
            
            if idx_atual < -len(self.dados) or idx_anterior < -len(self.dados):
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
            import traceback
            traceback.print_exc()
            return []


def analisar_mercado_tempo_real(mini_indices=True, mini_dolar=True, intervalo='1h', periodo='1d', loop=True, intervalo_atualizacao=300):
    """Analyze Brazilian market in real time"""
    # Use a longer interval (1h) to ensure we have data
    ticker_indices = "^BVSP"
    ticker_dolar = "USDBRL=X"
    
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