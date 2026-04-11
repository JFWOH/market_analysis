# advanced_strategy.py
import pandas as pd
import numpy as np
from price_action import PriceActionAnalyzer
from sentiment_analyzer import AnalisadorSentimento

class EstrategiaAvancada:
    """Estratégia avançada combinando análise técnica, price action e sentimento"""
    
    def __init__(self, dados, params=None):
        self.dados = dados
        
        # Parâmetros padrão que podem ser otimizados
        default_params = {
            'ema_curta': 8,
            'ema_media': 21,
            'ema_longa': 55,
            'atr_multiplicador_sl': 1.5,
            'atr_multiplicador_tp': 3.0,
            'limite_rsi_alto': 70,
            'limite_rsi_baixo': 30,
            'valor_minimo_trade': 5000,
            'filtro_tendencia': True,
            'filtro_sentimento': True,
            'filtro_volume': True,
            'use_trailing_stop': True,
            'trailing_start': 1.5,  # ATR multiplicador
            'trailing_step': 0.5,   # ATR multiplicador
            'min_price_action_strength': 7,
            'min_sentiment_score': 30
        }
        
        # Substituir parâmetros padrão por parâmetros personalizados
        self.params = default_params
        if params:
            for key, value in params.items():
                self.params[key] = value
    
    def preparar_dados(self):
        """Prepara os dados com todos os indicadores"""
        dados = self.dados.copy()
        
        # Calcular indicadores técnicos
        self._calcular_indicadores_tecnicos()
        
        # Adicionar análise de price action
        price_action = PriceActionAnalyzer(self.dados)
        self.dados = price_action.analisar_padroes()
        
        # Adicionar análise de sentimento
        sentimento = AnalisadorSentimento(self.dados)
        self.dados = sentimento.calcular_indicadores_sentimento()
        
        return self.dados
    
    def _calcular_indicadores_tecnicos(self):
        """Calcula indicadores técnicos para a estratégia"""
        dados = self.dados
        
        # EMAs
        dados[f'EMA_{self.params["ema_curta"]}'] = dados['Close'].ewm(span=self.params["ema_curta"], adjust=False).mean()
        dados[f'EMA_{self.params["ema_media"]}'] = dados['Close'].ewm(span=self.params["ema_media"], adjust=False).mean()
        dados[f'EMA_{self.params["ema_longa"]}'] = dados['Close'].ewm(span=self.params["ema_longa"], adjust=False).mean()
        
        # ATR para stops
        alto_baixo = dados['High'] - dados['Low']
        alto_fechamento = abs(dados['High'] - dados['Close'].shift())
        baixo_fechamento = abs(dados['Low'] - dados['Close'].shift())
        tr = pd.concat([alto_baixo, alto_fechamento, baixo_fechamento], axis=1).max(axis=1)
        dados['ATR_14'] = tr.rolling(window=14).mean()
        
        # RSI
        delta = dados['Close'].diff()
        ganhos = delta.copy()
        perdas = delta.copy()
        ganhos[ganhos < 0] = 0
        perdas[perdas > 0] = 0
        media_ganhos = ganhos.rolling(window=14).mean()
        media_perdas = abs(perdas.rolling(window=14).mean())
        rs = media_ganhos / media_perdas
        dados['RSI_14'] = 100 - (100 / (1 + rs))
        
        # MACD
        dados['MACD'] = dados['Close'].ewm(span=12, adjust=False).mean() - dados['Close'].ewm(span=26, adjust=False).mean()
        dados['MACD_Signal'] = dados['MACD'].ewm(span=9, adjust=False).mean()
        dados['MACD_Hist'] = dados['MACD'] - dados['MACD_Signal']
        
        # Filtros de tendência
        dados['Tendencia_Alta'] = (dados[f'EMA_{self.params["ema_curta"]}'] > dados[f'EMA_{self.params["ema_media"]}']) & \
                                (dados[f'EMA_{self.params["ema_media"]}'] > dados[f'EMA_{self.params["ema_longa"]}'])
        
        dados['Tendencia_Baixa'] = (dados[f'EMA_{self.params["ema_curta"]}'] < dados[f'EMA_{self.params["ema_media"]}']) & \
                                 (dados[f'EMA_{self.params["ema_media"]}'] < dados[f'EMA_{self.params["ema_longa"]}'])
        
        self.dados = dados
        return dados
    
    def gerar_sinais(self):
        """Gera sinais de trading combinando todos os elementos"""
        # Preparar dados se não foi feito
        if 'Sentiment_Index' not in self.dados.columns:
            self.preparar_dados()
            
        dados = self.dados
        sinais = []
        
        # Inicializar analisadores
        price_action = PriceActionAnalyzer(dados)
        sentimento = AnalisadorSentimento(dados)
        
        # Obter sinais de price action
        sinais_price_action = price_action.gerar_sinais_entrada(
            contexto_tendencia=self.params['filtro_tendencia'],
            min_strength=self.params['min_price_action_strength']
        )
        
        # Obter sinais de sentimento
        sinais_sentimento = sentimento.gerar_sinais_sentimento(
            threshold=self.params['min_sentiment_score']
        )
        
        # Combinar todos os sinais
        todos_sinais = sinais_price_action + sinais_sentimento
        
        # Filtrar sinais de acordo com os parâmetros
        for sinal in todos_sinais:
            data = sinal['data']
            i = dados.index.get_loc(data)
            
            # Aplicar filtros
            if self.params['filtro_tendencia']:
                # Para compras, confirmar tendência de alta ou reversão
                if sinal['tipo'] == 'Compra' and not (dados['Tendencia_Alta'].iloc[i] or 
                                                     (dados['Bullish_Divergence'].iloc[i])):
                    continue
                    
                # Para vendas, confirmar tendência de baixa ou reversão
                if sinal['tipo'] == 'Venda' and not (dados['Tendencia_Baixa'].iloc[i] or 
                                                    (dados['Bearish_Divergence'].iloc[i])):
                    continue
            
            # Filtro de sentimento
            if self.params['filtro_sentimento']:
                # Para compras, confirmar sentimento positivo
                if sinal['tipo'] == 'Compra' and dados['Sentiment_Index'].iloc[i] < 0:
                    continue
                    
                # Para vendas, confirmar sentimento negativo
                if sinal['tipo'] == 'Venda' and dados['Sentiment_Index'].iloc[i] > 0:
                    continue
            
            # Filtro de volume
            if self.params['filtro_volume'] and 'Volume' in dados.columns:
                # Confirmar volume acima da média
                if not dados['Volume'].iloc[i] > dados['Volume'].rolling(window=20).mean().iloc[i]:
                    continue
            
            # Ajustar stop loss e take profit baseado em ATR
            atr = dados['ATR_14'].iloc[i]
            if sinal['tipo'] == 'Compra':
                stop_loss = sinal['preco'] - atr * self.params['atr_multiplicador_sl']
                take_profit = sinal['preco'] + atr * self.params['atr_multiplicador_tp']
            else:  # Venda
                stop_loss = sinal['preco'] + atr * self.params['atr_multiplicador_sl']
                take_profit = sinal['preco'] - atr * self.params['atr_multiplicador_tp']
            
            # Atualizar sinal
            sinal['stop_loss'] = stop_loss
            sinal['take_profit'] = take_profit
            sinal['trailing_stop'] = self.params['use_trailing_stop']
            sinal['trailing_start'] = atr * self.params['trailing_start']
            sinal['trailing_step'] = atr * self.params['trailing_step']
            
            # Adicionar à lista de sinais filtrados
            sinais.append(sinal)
        
        return sinais
    
    def executar_backtest(self, capital_inicial=100000.0):
        """Executa backtest da estratégia"""
        if 'ATR_14' not in self.dados.columns:
            self.preparar_dados()
            
        dados = self.dados
        capital = capital_inicial
        posicoes = []
        trades_concluidos = []
        equity = [capital]
        datas_equity = [dados.index[0]]
        
        # Gerar sinais
        sinais = self.gerar_sinais()
        
        for i in range(1, len(dados)):
            data_atual = dados.index[i]
            preco_abertura = dados['Open'].iloc[i]
            preco_alto = dados['High'].iloc[i]
            preco_baixo = dados['Low'].iloc[i]
            preco_fechamento = dados['Close'].iloc[i]
            
            # Atualizar posições existentes
            novas_posicoes = []
            for pos in posicoes:
                # Verificar stop loss
                stop_atingido = False
                take_profit_atingido = False
                
                if pos['tipo'] == 'Compra':
                    # Verificar stop loss
                    if preco_baixo <= pos['stop_loss']:
                        # Stop loss atingido
                        resultado = (pos['stop_loss'] / pos['preco'] - 1) * pos['valor']
                        capital += resultado
                        
                        trades_concluidos.append({
                            'entrada': pos['data'],
                            'saida': data_atual,
                            'tipo': pos['tipo'],
                            'preco_entrada': pos['preco'],
                            'preco_saida': pos['stop_loss'],
                            'resultado': resultado,
                            'resultado_pct': pos['stop_loss'] / pos['preco'] - 1,
                            'motivo': 'Stop Loss',
                            'estrategia': pos['estrategia']
                        })
                        
                        stop_atingido = True
                    
                    # Verificar take profit
                    elif preco_alto >= pos['take_profit']:
                        # Take profit atingido
                        resultado = (pos['take_profit'] / pos['preco'] - 1) * pos['valor']
                        capital += resultado
                        
                        trades_concluidos.append({
                            'entrada': pos['data'],
                            'saida': data_atual,
                            'tipo': pos['tipo'],
                            'preco_entrada': pos['preco'],
                            'preco_saida': pos['take_profit'],
                            'resultado': resultado,
                            'resultado_pct': pos['take_profit'] / pos['preco'] - 1,
                            'motivo': 'Take Profit',
                            'estrategia': pos['estrategia']
                        })
                        
                        take_profit_atingido = True
                    
                    # Atualizar trailing stop se habilitado
                    elif pos['trailing_stop']:
                        # Verificar se preço moveu o suficiente para ativar trailing
                        if preco_alto >= pos['preco'] + pos['trailing_start']:
                            # Calcular novo stop loss (mais alto)
                            novo_stop = max(pos['stop_loss'], 
                                         preco_alto - pos['trailing_step'])
                            
                            # Atualizar stop loss
                            if novo_stop > pos['stop_loss']:
                                pos['stop_loss'] = novo_stop
                
                elif pos['tipo'] == 'Venda':
                    # Verificar stop loss
                    if preco_alto >= pos['stop_loss']:
                        # Stop loss atingido
                        resultado = (pos['preco'] / pos['stop_loss'] - 1) * pos['valor']
                        capital += resultado
                        
                        trades_concluidos.append({
                            'entrada': pos['data'],
                            'saida': data_atual,
                            'tipo': pos['tipo'],
                            'preco_entrada': pos['preco'],
                            'preco_saida': pos['stop_loss'],
                            'resultado': resultado,
                            'resultado_pct': pos['preco'] / pos['stop_loss'] - 1,
                            'motivo': 'Stop Loss',
                            'estrategia': pos['estrategia']
                        })
                        
                        stop_atingido = True
                    
                    # Verificar take profit
                    elif preco_baixo <= pos['take_profit']:
                        # Take profit atingido
                        resultado = (pos['preco'] / pos['take_profit'] - 1) * pos['valor']
                        capital += resultado
                        
                        trades_concluidos.append({
                            'entrada': pos['data'],
                            'saida': data_atual,
                            'tipo': pos['tipo'],
                            'preco_entrada': pos['preco'],
                            'preco_saida': pos['take_profit'],
                            'resultado': resultado,
                            'resultado_pct': pos['preco'] / pos['take_profit'] - 1,
                            'motivo': 'Take Profit',
                            'estrategia': pos['estrategia']
                        })
                        
                        take_profit_atingido = True
                    
                    # Atualizar trailing stop se habilitado
                    elif pos['trailing_stop']:
                        # Verificar se preço moveu o suficiente para ativar trailing
                        if preco_baixo <= pos['preco'] - pos['trailing_start']:
                            # Calcular novo stop loss (mais baixo)
                            novo_stop = min(pos['stop_loss'], 
                                         preco_baixo + pos['trailing_step'])
                            
                            # Atualizar stop loss
                            if novo_stop < pos['stop_loss']:
                                pos['stop_loss'] = novo_stop
                
                # Manter posição se não foi fechada
                if not stop_atingido and not take_profit_atingido:
                    novas_posicoes.append(pos)
            
            # Atualizar lista de posições
            posicoes = novas_posicoes
            
            # Verificar novos sinais
            for sinal in sinais:
                if sinal['data'] == data_atual:
                    # Calcular valor da posição
                    valor_posicao = min(self.params['valor_minimo_trade'], capital * 0.1)
                    
                    if valor_posicao > 100:  # Valor mínimo para operar
                        # Abrir nova posição
                        posicoes.append({
                            'data': data_atual,
                            'tipo': sinal['tipo'],
                            'preco': preco_fechamento,  # Assumindo execução no fechamento
                            'stop_loss': sinal['stop_loss'],
                            'take_profit': sinal['take_profit'],
                            'valor': valor_posicao,
                            'trailing_stop': sinal['trailing_stop'],
                            'trailing_start': sinal['trailing_start'],
                            'trailing_step': sinal['trailing_step'],
                            'estrategia': sinal['estrategia']
                        })
                        
                        # Deduzir valor da posição do capital
                        capital -= valor_posicao
            
            # Atualizar equity
            valor_posicoes = sum(pos['valor'] for pos in posicoes)
            equity.append(capital + valor_posicoes)
            datas_equity.append(data_atual)
        
        # Fechar posições restantes no final do período
        ultimo_preco = dados['Close'].iloc[-1]
        
        for pos in posicoes:
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
                'resultado_pct': resultado / pos['valor'],
                'motivo': 'Fechamento do Backtest',
                'estrategia': pos['estrategia']
            })
        
        # Calcular métricas
        retorno_total = capital / capital_inicial - 1
        trades_df = pd.DataFrame(trades_concluidos)
        
        metricas = {
            'capital_inicial': capital_inicial,
            'capital_final': capital,
            'retorno_total': retorno_total,
            'retorno_anualizado': self._calcular_retorno_anualizado(retorno_total, dados),
            'trades': trades_concluidos,
            'num_trades': len(trades_concluidos),
            'win_rate': sum(1 for t in trades_concluidos if t['resultado'] > 0) / len(trades_concluidos) if trades_concluidos else 0,
            'profit_factor': abs(sum(t['resultado'] for t in trades_concluidos if t['resultado'] > 0) / 
                               sum(t['resultado'] for t in trades_concluidos if t['resultado'] < 0)) if sum(t['resultado'] for t in trades_concluidos if t['resultado'] < 0) != 0 else float('inf'),
            'max_drawdown': self._calcular_drawdown(equity),
            'sharpe': self._calcular_sharpe(equity, datas_equity),
            'equity': equity,
            'datas_equity': datas_equity
        }
        
        return metricas
    
    def _calcular_retorno_anualizado(self, retorno_total, dados):
        """Calcula o retorno anualizado"""
        dias = (dados.index[-1] - dados.index[0]).days
        anos = dias / 365.0
        return (1 + retorno_total) ** (1 / anos) - 1
    
    def _calcular_drawdown(self, equity):
        """Calcula o máximo drawdown da curva de equity"""
        picos = pd.Series(equity).cummax()
        drawdowns = (pd.Series(equity) / picos - 1) * 100
        return abs(drawdowns.min())
    
    def _calcular_sharpe(self, equity, datas):
        """Calcula o Sharpe Ratio da estratégia"""
        retornos_diarios = pd.Series(equity, index=datas).pct_change().dropna()
        
        if len(retornos_diarios) < 2:
            return 0
            
        # Assumindo taxa livre de risco anual de 5%
        taxa_livre_risco_diaria = (1.05 ** (1/252)) - 1
        excesso_retorno = retornos_diarios - taxa_livre_risco_diaria
        
        sharpe = np.sqrt(252) * excesso_retorno.mean() / excesso_retorno.std()
        return sharpe
    
    def plotar_resultados(self, metricas, nome_ativo):
        """Plota os resultados do backtest"""
        import matplotlib.pyplot as plt
        
        # 1. Curva de Equity
        plt.figure(figsize=(15, 8))
        plt.plot(metricas['datas_equity'], metricas['equity'], label='Capital Total')
        plt.title(f'Curva de Capital - {nome_ativo}')
        plt.xlabel('Data')
        plt.ylabel('Capital (R$)')
        plt.grid(True, alpha=0.3)
        plt.savefig(f'equity_{nome_ativo}.png')
        
        # 2. Gráfico de transações
        trades_df = pd.DataFrame(metricas['trades'])
        plt.figure(figsize=(15, 10))
        
        # Gráfico de transações por resultado
        plt.subplot(2, 1, 1)
        trades_df['resultado_pct'] = trades_df['resultado_pct'] * 100
        trades_df = trades_df.sort_values('resultado_pct')
        plt.bar(range(len(trades_df)), trades_df['resultado_pct'], 
               color=['red' if r < 0 else 'green' for r in trades_df['resultado_pct']])
        plt.axhline(y=0, color='black', linestyle='-')
        plt.title('Resultado de Operações (%)')
        plt.ylabel('Retorno (%)')
        plt.grid(True, alpha=0.3)
        
        # Gráfico de estratégias por win rate
        plt.subplot(2, 1, 2)
        estrategias = trades_df.groupby('estrategia').agg({
            'resultado': ['count', lambda x: sum(1 for i in x if i > 0) / len(x) * 100 if len(x) > 0 else 0]
        })
        estrategias.columns = ['Quantidade', 'Win Rate (%)']
        estrategias = estrategias.sort_values('Win Rate (%)', ascending=False)
        
        plt.barh(estrategias.index, estrategias['Win Rate (%)'], color='skyblue')
        plt.xlabel('Win Rate (%)')
        plt.title('Performance por Estratégia')
        plt.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(f'trades_{nome_ativo}.png')
        
        # 3. Resumo de métricas
        plt.figure(figsize=(12, 6))
        principais_metricas = {
            'Retorno Total (%)': metricas['retorno_total'] * 100,
            'Retorno Anualizado (%)': metricas['retorno_anualizado'] * 100,
            'Win Rate (%)': metricas['win_rate'] * 100,
            'Número de Trades': metricas['num_trades'],
            'Profit Factor': metricas['profit_factor'],
            'Max Drawdown (%)': metricas['max_drawdown'],
            'Sharpe Ratio': metricas['sharpe']
        }
        
        plt.barh(list(principais_metricas.keys()), list(principais_metricas.values()), color='lightblue')
        plt.axvline(x=0, color='black', linestyle='-')
        plt.title(f'Métricas de Performance - {nome_ativo}')
        plt.grid(True, alpha=0.3)
        
        # Adicionar valores às barras
        for i, valor in enumerate(principais_metricas.values()):
            plt.text(max(valor + 1, 1), i, f'{valor:.2f}', va='center')
        
        plt.tight_layout()
        plt.savefig(f'metricas_{nome_ativo}.png')
        
        # Retornar paths dos gráficos
        return [
            f'equity_{nome_ativo}.png',
            f'trades_{nome_ativo}.png',
            f'metricas_{nome_ativo}.png'
        ]