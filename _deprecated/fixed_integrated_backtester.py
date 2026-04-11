# fixed_integrated_backtester.py
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import yfinance as yf
from datetime import datetime, timedelta
import matplotlib.dates as mdates
import os
import sys

# Import your market analyzer
from market_analyzer import AnalisadorMercado

print("Integrated Backtester - Starting...")

class BacktesterIntegrado:
    def __init__(self, ticker, nome_ativo, periodo_inicio='2023-01-01', periodo_fim=None, intervalo='1d'):
        self.ticker = ticker
        self.nome_ativo = nome_ativo
        self.periodo_inicio = periodo_inicio
        self.periodo_fim = periodo_fim if periodo_fim else datetime.now().strftime('%Y-%m-%d')
        self.intervalo = intervalo
        self.dados = None
        self.trades = []
        self.capital = 100000.0
        self.equity = []
        self.datas = []
        
    def obter_dados(self):
        print(f"Baixando dados históricos para {self.nome_ativo}...")
        try:
            dados = yf.download(
                tickers=self.ticker,
                start=self.periodo_inicio,
                end=self.periodo_fim,
                interval=self.intervalo,
                progress=False
            )
            
            print(f"Dados obtidos: {len(dados)} períodos")
            
            if dados.empty:
                print(f"Erro: Nenhum dado obtido para {self.ticker}")
                return False
                
            # Handle multi-level columns
            if isinstance(dados.columns, pd.MultiIndex):
                new_columns = []
                for col in dados.columns:
                    if isinstance(col, tuple):
                        new_columns.append('_'.join(str(x) for x in col))
                    else:
                        new_columns.append(str(col))
                
                dados.columns = new_columns
            
            # Ensure we have the 'Close' column
            if 'Close' not in dados.columns:
                price_cols = [col for col in dados.columns if 'close' in col.lower()]
                if price_cols:
                    dados['Close'] = dados[price_cols[0]]
                else:
                    dados['Close'] = dados[dados.columns[0]]
            
            self.dados = dados
            return True
            
        except Exception as e:
            print(f"Erro ao obter dados: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def executar_backtest(self):
        print(f"Iniciando backtest para {self.nome_ativo}...")
        
        # Setup tracking variables
        self.trades = []
        posicao_atual = None
        self.capital = 100000.0
        self.equity = [self.capital]
        self.datas = [self.dados.index[0]]
        
        # Create analyzer with our strategy
        analisador = AnalisadorMercado(self.ticker)
        
        # Process data chronologically
        for i in range(50, len(self.dados)):  # Start after enough data for indicators
            # Get data up to current time
            data_slice = self.dados.iloc[:i+1].copy()
            
            # Update analyzer with current data
            analisador.dados = data_slice
            
            # Calculate indicators and get signals
            try:
                analisador.calcular_indicadores()
                tendencia = analisador.analisar_tendencia()
                sinais = analisador.identificar_pontos_entrada()
                
                data_atual = data_slice.index[-1]
                preco = data_slice['Close'].iloc[-1]
                if isinstance(preco, pd.Series):
                    preco = preco.item()  # Convert to scalar if it's a Series
                
                # Check for exit conditions
                if posicao_atual is not None:
                    if posicao_atual['tipo'] == 'Compra':
                        # Take profit
                        if preco >= posicao_atual['preco_alvo']:
                            lucro = (preco / posicao_atual['preco_entrada'] - 1) * self.capital
                            self.capital += lucro
                            self.trades.append({
                                'tipo': 'Venda',
                                'entrada': posicao_atual['data_entrada'],
                                'saida': data_atual,
                                'preco_entrada': posicao_atual['preco_entrada'],
                                'preco_saida': preco,
                                'resultado': lucro,
                                'motivo': 'Take Profit',
                                'estrategia': posicao_atual['estrategia']
                            })
                            posicao_atual = None
                        
                        # Stop loss
                        elif preco <= posicao_atual['stop_loss']:
                            perda = (preco / posicao_atual['preco_entrada'] - 1) * self.capital
                            self.capital += perda
                            self.trades.append({
                                'tipo': 'Venda',
                                'entrada': posicao_atual['data_entrada'],
                                'saida': data_atual,
                                'preco_entrada': posicao_atual['preco_entrada'],
                                'preco_saida': preco,
                                'resultado': perda,
                                'motivo': 'Stop Loss',
                                'estrategia': posicao_atual['estrategia']
                            })
                            posicao_atual = None
                    
                    elif posicao_atual['tipo'] == 'Venda':
                        # Take profit (price went down)
                        if preco <= posicao_atual['preco_alvo']:
                            lucro = (posicao_atual['preco_entrada'] / preco - 1) * self.capital
                            self.capital += lucro
                            self.trades.append({
                                'tipo': 'Compra',
                                'entrada': posicao_atual['data_entrada'],
                                'saida': data_atual,
                                'preco_entrada': posicao_atual['preco_entrada'],
                                'preco_saida': preco,
                                'resultado': lucro,
                                'motivo': 'Take Profit',
                                'estrategia': posicao_atual['estrategia']
                            })
                            posicao_atual = None
                        
                        # Stop loss (price went up)
                        elif preco >= posicao_atual['stop_loss']:
                            perda = (posicao_atual['preco_entrada'] / preco - 1) * self.capital
                            self.capital += perda
                            self.trades.append({
                                'tipo': 'Compra',
                                'entrada': posicao_atual['data_entrada'],
                                'saida': data_atual,
                                'preco_entrada': posicao_atual['preco_entrada'],
                                'preco_saida': preco,
                                'resultado': perda,
                                'motivo': 'Stop Loss',
                                'estrategia': posicao_atual['estrategia']
                            })
                            posicao_atual = None
                
                # Check for new entry signals
                if posicao_atual is None and sinais:
                    for sinal in sinais:
                        posicao_atual = {
                            'tipo': sinal['tipo'],
                            'data_entrada': data_atual,
                            'preco_entrada': preco,
                            'preco_alvo': sinal['preco_alvo'],
                            'stop_loss': sinal['stop_loss'],
                            'estrategia': sinal['estrategia']
                        }
                        break  # Just take the first signal
                
                # Update equity curve
                self.equity.append(self.capital)
                self.datas.append(data_atual)
                
            except Exception as e:
                print(f"Erro na iteração {i}: {e}")
                continue
        
        # Calculate and show results
        self.mostrar_resultados()
        self.gerar_graficos()
        
        return True
        
    def mostrar_resultados(self):
        print("\n" + "="*50)
        print(f"RESULTADOS DO BACKTEST - {self.nome_ativo}")
        print("="*50)
        
        print(f"Capital inicial: R${100000:.2f}")
        print(f"Capital final: R${self.capital:.2f}")
        
        retorno_total = self.capital / 100000 - 1
        print(f"Retorno total: {retorno_total:.2%}")
        
        trades_df = pd.DataFrame(self.trades)
        if not trades_df.empty:
            total_operacoes = len(trades_df)
            vencedoras = len(trades_df[trades_df['resultado'] > 0])
            
            print(f"Total de operações: {total_operacoes}")
            print(f"Taxa de acerto: {vencedoras/total_operacoes:.2%}")
            
            print("\nOperações por estratégia:")
            if 'estrategia' in trades_df.columns:
                por_estrategia = trades_df.groupby('estrategia').size()
                print(por_estrategia)
            else:
                print("Informação de estratégia não disponível")
            
            print("\nMelhores operações:")
            top3 = trades_df.nlargest(3, 'resultado')
            for i, op in top3.iterrows():
                print(f"  {op['tipo']}: R${op['resultado']:.2f} ({op['motivo']})")
            
            print("\nPiores operações:")
            bottom3 = trades_df.nsmallest(3, 'resultado')
            for i, op in bottom3.iterrows():
                print(f"  {op['tipo']}: R${op['resultado']:.2f} ({op['motivo']})")
        else:
            print("Nenhuma operação realizada durante o período.")
    
    def gerar_graficos(self):
        print("\nGerando gráficos...")
        
        # Create output directory
        pasta_saida = 'resultados_backtest'
        if not os.path.exists(pasta_saida):
            os.makedirs(pasta_saida)
        
        # 1. Price chart with entry/exit points
        plt.figure(figsize=(15, 8))
        plt.plot(self.dados.index, self.dados['Close'], label='Preço', color='black')
        
        df_trades = pd.DataFrame(self.trades)
        if not df_trades.empty:
            # Plot buy points
            compras = df_trades[df_trades['tipo'] == 'Compra']
            if not compras.empty:
                plt.scatter(compras['entrada'], compras['preco_entrada'], 
                          marker='^', color='green', s=100, label='Compra')
            
            # Plot sell points
            vendas = df_trades[df_trades['tipo'] == 'Venda']
            if not vendas.empty:
                plt.scatter(vendas['entrada'], vendas['preco_entrada'], 
                          marker='v', color='red', s=100, label='Venda')
        
        plt.title(f'Preço e Operações - {self.nome_ativo}', fontsize=16)
        plt.xlabel('Data', fontsize=12)
        plt.ylabel('Preço', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.savefig(os.path.join(pasta_saida, f'{self.nome_ativo}_preco.png'))
        
        # 2. Equity curve
        plt.figure(figsize=(15, 8))
        plt.plot(self.datas, self.equity, label='Capital', color='blue')
        plt.title(f'Curva de Capital - {self.nome_ativo}', fontsize=16)
        plt.xlabel('Data', fontsize=12)
        plt.ylabel('Capital (R$)', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.savefig(os.path.join(pasta_saida, f'{self.nome_ativo}_equity.png'))
        
        print(f"Gráficos salvos em: {pasta_saida}")

def executar_backtests():
    print("\n==== BACKTESTING DE ESTRATÉGIAS - MERCADO BRASILEIRO ====")
    
    # List of assets to test
    ativos = [
        {"ticker": "^BVSP", "nome": "Ibovespa", "inicio": "2023-01-01", "fim": "2023-12-31", "intervalo": "1d"},
        {"ticker": "USDBRL=X", "nome": "USD/BRL", "inicio": "2023-01-01", "fim": "2023-12-31", "intervalo": "1d"}
    ]
    
    # Run backtest for each asset
    for ativo in ativos:
        print(f"\nTestando estratégia para: {ativo['nome']}")
        
        backtester = BacktesterIntegrado(
            ticker=ativo['ticker'],
            nome_ativo=ativo['nome'],
            periodo_inicio=ativo['inicio'],
            periodo_fim=ativo['fim'],
            intervalo=ativo['intervalo']
        )
        
        if backtester.obter_dados():
            backtester.executar_backtest()
        else:
            print(f"Não foi possível obter dados para {ativo['nome']}")
        
        print("-" * 50)

if __name__ == "__main__":
    executar_backtests()