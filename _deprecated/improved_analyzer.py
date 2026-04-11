import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import time

class AnalisadorMercado:
    """Analisador de ativos do mercado financeiro brasileiro."""
    
    def __init__(self, ticker, intervalo='5m', periodo='1d'):
        """Inicializa o analisador com o ticker específico."""
        self.ticker = ticker
        self.intervalo = intervalo
        self.periodo = periodo
        self.dados = None
        self.ultimo_preco = None
        self.tendencia_atual = None
        self.sinais = []
        
def obter_dados(self):
    try:
        print(f"Tentando obter dados para {self.ticker}...")
        data = yf.download(
            tickers=self.ticker,
            period=self.periodo,
            interval=self.intervalo,
            progress=False
        )
        
        # Debug info
        print(f"Dados recebidos. Formato: {data.shape}")
        print("Colunas:", data.columns.tolist() if not data.empty else "Nenhuma")
        
        if data.empty:
            print(f"Não foi possível obter dados para {self.ticker}")
            return False
        
        # Handle multi-level columns if present
        if isinstance(data.columns, pd.MultiIndex):
            print("Detectado MultiIndex nas colunas. Ajustando...")
            data.columns = [col[1] if isinstance(col, tuple) and len(col) > 1 else col 
                          for col in data.columns]
            print("Colunas após ajuste:", data.columns.tolist())
        
        # Make sure we have the 'Close' column
        if 'Close' not in data.columns:
            print(f"Coluna 'Close' não encontrada! Colunas disponíveis: {data.columns.tolist()}")
            if len(data.columns) > 0:
                # Use the first available price column as Close
                price_column = data.columns[0]
                print(f"Usando coluna '{price_column}' como 'Close'")
                data['Close'] = data[price_column]
            else:
                return False
        
        self.dados = data
        self.ultimo_preco = data['Close'].iloc[-1] if not data.empty else None
        return True
            
    except Exception as e:
        print(f"Erro ao obter dados: {e}")
        import traceback
        traceback.print_exc()
        return False
            
    def calcular_indicadores(self):
        """Calcula indicadores técnicos."""
        if self.dados is None or self.dados.empty:
            return False
            
        # Médias Móveis
        self.dados['MM20'] = self.dados['Close'].rolling(window=20).mean()
        self.dados['MM50'] = self.dados['Close'].rolling(window=50).mean()
        
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
        
        # MACD
        self.dados['MACD'] = self.dados['Close'].ewm(span=12, adjust=False).mean() - self.dados['Close'].ewm(span=26, adjust=False).mean()
        self.dados['MACD_Signal'] = self.dados['MACD'].ewm(span=9, adjust=False).mean()
        
        # Bandas de Bollinger
        periodo_bb = 20
        desvio_padrao = 2
        self.dados['BB_Meio'] = self.dados['Close'].rolling(window=periodo_bb).mean()
        std_dev = self.dados['Close'].rolling(window=periodo_bb).std()
        self.dados['BB_Superior'] = self.dados['BB_Meio'] + (std_dev * desvio_padrao)
        self.dados['BB_Inferior'] = self.dados['BB_Meio'] - (std_dev * desvio_padrao)
        
        return True
    
    def analisar_tendencia(self):
        """Analisa a tendência atual do mercado."""
        if self.dados is None or self.dados.empty:
            return "Indeterminada"
            
        ultimos_dados = self.dados.iloc[-1]
        
        # Definir pontuação para tendência
        pontuacao = 0
        
        # 1. Análise de Médias Móveis
        if ultimos_dados['Close'] > ultimos_dados['MM20']:
            pontuacao += 1
        else:
            pontuacao -= 1
            
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
            
        # Determinar tendência baseada na pontuação
        if pontuacao >= 2:
            self.tendencia_atual = "Alta"
        elif pontuacao <= -2:
            self.tendencia_atual = "Baixa"
        else:
            self.tendencia_atual = "Lateral"
            
        return self.tendencia_atual
    
    def identificar_pontos_entrada(self):
        """Identifica possíveis pontos de entrada para operações."""
        if self.dados is None or self.dados.empty or len(self.dados) < 2:
            return []
            
        sinais = []
        ultimos_dados = self.dados.iloc[-1]
        dados_anteriores = self.dados.iloc[-2]
        
        # Analisar tendência atual
        tendencia = self.analisar_tendencia()
        
        # 1. Estratégia de Cruzamento de Médias Móveis
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
        
        # 2. Estratégia de RSI
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

def analisar_mercado_tempo_real(mini_indices=True, mini_dolar=True, intervalo='5m', periodo='1d', loop=True, intervalo_atualizacao=300):
    # Try alternative ticker symbols
    ticker_indices = "^BVSP"  # Ibovespa
    ticker_dolar = "USDBRL=X"  # Try this alternative USD/BRL format
    
    print(f"Iniciando análise de mercado em tempo real - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"Configuração: Intervalo={intervalo}, Período={periodo}")
    print(f"Tickers: Índice={ticker_indices}, Dólar={ticker_dolar}")
    
    analisador_indices = AnalisadorMercado(ticker_indices, intervalo, periodo) if mini_indices else None
    analisador_dolar = AnalisadorMercado(ticker_dolar, intervalo, periodo) if mini_dolar else None
    
    def executar_analise():
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
    analisar_mercado_tempo_real(loop=False)