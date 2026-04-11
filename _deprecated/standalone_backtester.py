# standalone_backtester.py
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import yfinance as yf
from datetime import datetime, timedelta
import matplotlib.dates as mdates
import os

print("Standalone Backtester - Starting...")

# Simple moving average crossover strategy
def calcular_sinais_sma(dados):
    """Calculate buy/sell signals based on SMA crossover"""
    dados['SMA_Curta'] = dados['Close'].rolling(window=10).mean()
    dados['SMA_Longa'] = dados['Close'].rolling(window=30).mean()
    
    sinais = []
    
    for i in range(1, len(dados)):
        if pd.isna(dados['SMA_Curta'].iloc[i]) or pd.isna(dados['SMA_Longa'].iloc[i]):
            continue
            
        curta_anterior = dados['SMA_Curta'].iloc[i-1]
        longa_anterior = dados['SMA_Longa'].iloc[i-1]
        curta_atual = dados['SMA_Curta'].iloc[i]
        longa_atual = dados['SMA_Longa'].iloc[i]
        
        # Crossover up - buy signal
        if curta_anterior <= longa_anterior and curta_atual > longa_atual:
            preco = dados['Close'].iloc[i]
            sinais.append({
                'data': dados.index[i],
                'tipo': 'Compra',
                'preco': preco,
                'preco_alvo': preco * 1.03,
                'stop_loss': preco * 0.98
            })
        
        # Crossover down - sell signal
        elif curta_anterior >= longa_anterior and curta_atual < longa_atual:
            preco = dados['Close'].iloc[i]
            sinais.append({
                'data': dados.index[i],
                'tipo': 'Venda',
                'preco': preco,
                'preco_alvo': preco * 0.97,
                'stop_loss': preco * 1.02
            })
    
    return sinais

def executar_backtest_simplificado():
    try:
        print("\n====== BACKTESTING SIMPLIFICADO ======")
        
        # 1. Download data
        print("Baixando dados históricos do Ibovespa...")
        dados = yf.download("^BVSP", start="2023-01-01", end="2023-12-31")
        print(f"Dados baixados: {len(dados)} dias")
        
        # 2. Calculate signals
        print("Calculando sinais de negociação...")
        sinais = calcular_sinais_sma(dados)
        print(f"Total de sinais gerados: {len(sinais)}")
        
        # 3. Simulate trading
        print("Simulando operações...")
        capital = 100000  # R$100k initial capital
        posicao_atual = None
        trades = []
        equity = [capital]
        datas = [dados.index[0]]
        
        for i in range(len(dados)):
            data_atual = dados.index[i]
            preco = dados['Close'].iloc[i]
            
            # Check for exit conditions
            if posicao_atual is not None:
                if posicao_atual['tipo'] == 'Compra':
                    # Take profit
                    if preco >= posicao_atual['preco_alvo']:
                        lucro = (preco / posicao_atual['preco_entrada'] - 1) * capital
                        capital += lucro
                        trades.append({
                            'tipo': 'Venda',
                            'entrada': posicao_atual['data_entrada'],
                            'saida': data_atual,
                            'preco_entrada': posicao_atual['preco_entrada'],
                            'preco_saida': preco,
                            'resultado': lucro
                        })
                        posicao_atual = None
                    
                    # Stop loss
                    elif preco <= posicao_atual['stop_loss']:
                        perda = (preco / posicao_atual['preco_entrada'] - 1) * capital
                        capital += perda
                        trades.append({
                            'tipo': 'Venda',
                            'entrada': posicao_atual['data_entrada'],
                            'saida': data_atual,
                            'preco_entrada': posicao_atual['preco_entrada'],
                            'preco_saida': preco,
                            'resultado': perda
                        })
                        posicao_atual = None
                
                elif posicao_atual['tipo'] == 'Venda':
                    # Take profit (price went down)
                    if preco <= posicao_atual['preco_alvo']:
                        lucro = (posicao_atual['preco_entrada'] / preco - 1) * capital
                        capital += lucro
                        trades.append({
                            'tipo': 'Compra',
                            'entrada': posicao_atual['data_entrada'],
                            'saida': data_atual,
                            'preco_entrada': posicao_atual['preco_entrada'],
                            'preco_saida': preco,
                            'resultado': lucro
                        })
                        posicao_atual = None
                    
                    # Stop loss (price went up)
                    elif preco >= posicao_atual['stop_loss']:
                        perda = (posicao_atual['preco_entrada'] / preco - 1) * capital
                        capital += perda
                        trades.append({
                            'tipo': 'Compra',
                            'entrada': posicao_atual['data_entrada'],
                            'saida': data_atual,
                            'preco_entrada': posicao_atual['preco_entrada'],
                            'preco_saida': preco,
                            'resultado': perda
                        })
                        posicao_atual = None
            
            # Check for entry signals
            if posicao_atual is None:
                for sinal in sinais:
                    if sinal['data'] == data_atual:
                        posicao_atual = {
                            'tipo': sinal['tipo'],
                            'data_entrada': data_atual,
                            'preco_entrada': preco,
                            'preco_alvo': sinal['preco_alvo'],
                            'stop_loss': sinal['stop_loss']
                        }
                        break
            
            # Update equity
            equity.append(capital)
            datas.append(data_atual)
        
        # 4. Calculate metrics
        print("\n=== RESULTADOS DO BACKTEST ===")
        print(f"Capital inicial: R${100000:.2f}")
        print(f"Capital final: R${capital:.2f}")
        retorno_total = capital / 100000 - 1
        print(f"Retorno total: {retorno_total:.2%}")
        
        total_operacoes = len(trades)
        print(f"Total de operações: {total_operacoes}")
        
        if total_operacoes > 0:
            operacoes_vencedoras = len([t for t in trades if t['resultado'] > 0])
            taxa_acerto = operacoes_vencedoras / total_operacoes
            print(f"Taxa de acerto: {taxa_acerto:.2%}")
            
            resultado_medio = sum(t['resultado'] for t in trades) / total_operacoes
            print(f"Resultado médio por operação: R${resultado_medio:.2f}")
        
        # 5. Create charts
        print("\nGerando gráficos...")
        
        # Price chart with signals
        plt.figure(figsize=(15, 8))
        plt.plot(dados.index, dados['Close'], label='Ibovespa', color='black')
        
        # Plot buy signals
        compras = [t for t in trades if t['tipo'] == 'Compra']
        if compras:
            plt.scatter([t['entrada'] for t in compras], 
                        [t['preco_entrada'] for t in compras],
                        marker='^', color='green', s=100, label='Compra')
        
        # Plot sell signals
        vendas = [t for t in trades if t['tipo'] == 'Venda']
        if vendas:
            plt.scatter([t['entrada'] for t in vendas], 
                        [t['preco_entrada'] for t in vendas],
                        marker='v', color='red', s=100, label='Venda')
        
        plt.title('Ibovespa - Sinais de Trading (2023)', fontsize=16)
        plt.xlabel('Data')
        plt.ylabel('Preço')
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.savefig('backtest_preco.png')
        
        # Equity curve
        plt.figure(figsize=(15, 8))
        plt.plot(datas, equity, label='Capital', color='blue')
        plt.title('Curva de Capital', fontsize=16)
        plt.xlabel('Data')
        plt.ylabel('Capital (R$)')
        plt.grid(True, alpha=0.3)
        plt.savefig('backtest_equity.png')
        
        print("\nBacktest concluído!")
        print("Gráficos salvos: backtest_preco.png e backtest_equity.png")
        
    except Exception as e:
        print(f"Erro no backtest: {e}")
        import traceback
        traceback.print_exc()

# Run the test
if __name__ == "__main__":
    executar_backtest_simplificado()