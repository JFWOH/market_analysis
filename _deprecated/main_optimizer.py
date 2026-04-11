# main_optimizer.py
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
from datetime import datetime
import os
import itertools
from tqdm import tqdm

from strategy_optimizer import OtimizadorEstrategia
from price_action import PriceActionAnalyzer
from sentiment_analyzer import AnalisadorSentimento
from advanced_strategy import EstrategiaAvancada

def criar_diretorios():
    """Cria diretórios para armazenar resultados"""
    diretorios = ['resultados', 'graficos', 'logs']
    for diretorio in diretorios:
        if not os.path.exists(diretorio):
            os.makedirs(diretorio)

def obter_dados(ticker, inicio='2020-01-01', fim=None, intervalo='1d'):
    """Obtém dados históricos para o ativo"""
    if fim is None:
        fim = datetime.now().strftime('%Y-%m-%d')
        
    print(f"Baixando dados para {ticker} de {inicio} até {fim}...")
    try:
        dados = yf.download(ticker, start=inicio, end=fim, interval=intervalo)
        print(f"Dados obtidos: {len(dados)} períodos")
        return dados
    except Exception as e:
        print(f"Erro ao obter dados: {e}")
        return None

def otimizar_estrategia(ticker, nome_ativo):
    """Executa otimização completa da estratégia"""
    # Parâmetros a serem otimizados (grid search)
    parametros_grid = {
        'ema_curta': [8, 9, 10, 13],
        'ema_media': [21, 34],
        'ema_longa': [55, 89],
        'atr_multiplicador_sl': [1.0, 1.5, 2.0],
        'atr_multiplicador_tp': [2.0, 3.0, 4.0],
        'filtro_tendencia': [True, False],
        'filtro_sentimento': [True, False],
        'min_price_action_strength': [6, 7, 8],
        'use_trailing_stop': [True, False]
    }
    
    # Criar todas as combinações possíveis
    chaves = list(parametros_grid.keys())
    combinacoes = list(itertools.product(*[parametros_grid[k] for k in chaves]))
    
    # Obter dados históricos
    dados_treino = obter_dados(ticker, inicio='2020-01-01', fim='2022-12-31')
    dados_teste = obter_dados(ticker, inicio='2023-01-01', fim=None)
    
    if dados_treino is None or dados_teste is None:
        print(f"Não foi possível obter dados para {ticker}")
        return None
    
    print(f"Iniciando otimização para {nome_ativo}...")
    print(f"Total de combinações a testar: {len(combinacoes)}")
    
    melhores_resultados = []
    
    # Testar combinações
    for i, valores in enumerate(tqdm(combinacoes, desc="Otimizando")):
        parametros = dict(zip(chaves, valores))
        
        # Criar estratégia com estes parâmetros
        estrategia = EstrategiaAvancada(dados_treino, parametros)
        
        try:
            # Executar backtest no período de treino
            metricas = estrategia.executar_backtest()
            
            # Registrar resultado
            resultado = {
                'parametros': parametros,
                'retorno_total': metricas['retorno_total'],
                'win_rate': metricas['win_rate'],
                'sharpe': metricas['sharpe'],
                'drawdown': metricas['max_drawdown'],
                'num_trades': metricas['num_trades']
            }
            
            melhores_resultados.append(resultado)
        except Exception as e:
            print(f"Erro ao testar combinação {i}: {e}")
            continue
    
    # Ordenar resultados pelo Sharpe Ratio (balanceando retorno e risco)
    melhores_resultados.sort(key=lambda x: x['sharpe'], reverse=True)
    
    # Exibir os melhores parâmetros
    print("\n--- TOP 5 MELHORES COMBINAÇÕES ---")
    for i, res in enumerate(melhores_resultados[:5]):
        print(f"{i+1}. Retorno: {res['retorno_total']:.2%}, Win Rate: {res['win_rate']:.2%}, Sharpe: {res['sharpe']:.2f}")
        print(f"   Parâmetros: {res['parametros']}")
    
    # Obter os melhores parâmetros
    melhores_parametros = melhores_resultados[0]['parametros']
    
    # Validar no conjunto de teste
    print("\nValidando melhores parâmetros no conjunto de teste...")
    estrategia_validacao = EstrategiaAvancada(dados_teste, melhores_parametros)
    metricas_validacao = estrategia_validacao.executar_backtest()
    
    print(f"Desempenho no conjunto de teste:")
    print(f"Retorno total: {metricas_validacao['retorno_total']:.2%}")
    print(f"Win rate: {metricas_validacao['win_rate']:.2%}")
    print(f"Sharpe ratio: {metricas_validacao['sharpe']:.2f}")
    print(f"Máximo drawdown: {metricas_validacao['max_drawdown']:.2%}")
    print(f"Número de trades: {metricas_validacao['num_trades']}")
    
    # Gerar gráficos
    estrategia_validacao.plotar_resultados(metricas_validacao, nome_ativo)
    
    return {
        'melhores_parametros': melhores_parametros,
        'metricas_treino': melhores_resultados[0],
        'metricas_teste': metricas_validacao
    }

def executar_otimizacao_full():
    """Executa otimização para múltiplos ativos"""
    criar_diretorios()
    
    # Ativos a serem otimizados
    ativos = [
        {"ticker": "^BVSP", "nome": "Ibovespa"},
        {"ticker": "USDBRL=X", "nome": "USD/BRL"}
    ]
    
    resultados = {}
    
    for ativo in ativos:
        print(f"\n{'='*50}")
        print(f"INICIANDO OTIMIZAÇÃO PARA {ativo['nome']}")
        print(f"{'='*50}")
        
        resultado = otimizar_estrategia(ativo['ticker'], ativo['nome'])
        
        if resultado:
            resultados[ativo['nome']] = resultado
            
            # Salvar resultado
            with open(f"resultados/otimizacao_{ativo['nome']}.txt", 'w') as f:
                f.write(f"Melhores parâmetros para {ativo['nome']}:\n")
                for param, valor in resultado['melhores_parametros'].items():
                    f.write(f"{param}: {valor}\n")
                    
                f.write("\nMétricas no conjunto de treino:\n")
                for metrica, valor in resultado['metricas_treino'].items():
                    if metrica != 'parametros':
                        f.write(f"{metrica}: {valor}\n")
                        
                f.write("\nMétricas no conjunto de teste:\n")
                for metrica, valor in resultado['metricas_teste'].items():
                    if not isinstance(valor, (list, dict)):
                        f.write(f"{metrica}: {valor}\n")
    
    return resultados

if __name__ == "__main__":
    print("INICIANDO OTIMIZAÇÃO DE ESTRATÉGIA AVANÇADA")
    print("===========================================")
    
    resultados = executar_otimizacao_full()
    
    print("\nOTIMIZAÇÃO CONCLUÍDA")
    print("===================")
    
    # Resumo final
    print("\nRESUMO DOS RESULTADOS:")
    for ativo, resultado in resultados.items():
        print(f"\n{ativo}:")
        print(f"  Retorno no teste: {resultado['metricas_teste']['retorno_total']:.2%}")
        print(f"  Win rate no teste: {resultado['metricas_teste']['win_rate']:.2%}")