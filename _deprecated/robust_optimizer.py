# robust_optimizer.py
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

class SimpleStrategy:
    """Simplified strategy implementation focusing on robustness"""
    
    def __init__(self, ticker, nome_ativo, filtro_tendencia=True, min_strength=7):
        self.ticker = ticker
        self.nome_ativo = nome_ativo
        self.filtro_tendencia = filtro_tendencia
        self.min_strength = min_strength
        self.dados = None
    
    def get_scalar(self, series_or_value):
        """Safely convert pandas Series to scalar"""
        if isinstance(series_or_value, pd.Series):
            if len(series_or_value) > 0:
                return series_or_value.iloc[0]
            return np.nan
        return series_or_value
    
    def obter_dados(self, inicio, fim, intervalo):
        """Get historical data"""
        try:
            print(f"Baixando dados para {self.nome_ativo}...")
            dados = yf.download(
                tickers=self.ticker,
                start=inicio,
                end=fim,
                interval=intervalo,
                progress=False
            )
            
            if dados.empty:
                print("Nenhum dado encontrado")
                return False
                
            # Ensure we're working with simple columns
            if isinstance(dados.columns, pd.MultiIndex):
                # If we have a MultiIndex, flatten it
                dados.columns = [col[1] if isinstance(col, tuple) and len(col) > 1 else col 
                                for col in dados.columns]
            
            print(f"Dados baixados: {len(dados)} períodos")
            self.dados = dados
            return True
        except Exception as e:
            print(f"Erro ao baixar dados: {e}")
            return False
    
    def calcular_indicadores(self):
        """Calculate technical indicators"""
        if self.dados is None or self.dados.empty:
            return False
            
        dados = self.dados
        
        # Extract series safely
        close = dados['Close']
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:,0]
            
        high = dados['High']
        if isinstance(high, pd.DataFrame):
            high = high.iloc[:,0]
            
        low = dados['Low']
        if isinstance(low, pd.DataFrame):
            low = low.iloc[:,0]
            
        # EMAs for trend detection
        dados['EMA_8'] = close.ewm(span=8, adjust=False).mean()
        dados['EMA_21'] = close.ewm(span=21, adjust=False).mean()
        dados['EMA_55'] = close.ewm(span=55, adjust=False).mean()
        
        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        dados['RSI'] = 100 - (100 / (1 + rs)).fillna(50)
        
        # Simple buy/sell signals
        dados['Buy_Signal'] = ((close > dados['EMA_8']) & 
                              (dados['EMA_8'] > dados['EMA_21']) & 
                              (dados['RSI'] < 70)).astype(int)
        
        dados['Sell_Signal'] = ((close < dados['EMA_8']) & 
                               (dados['EMA_8'] < dados['EMA_21']) & 
                               (dados['RSI'] > 30)).astype(int)
        
        # ATR for stop loss
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        dados['ATR'] = tr.rolling(window=14).mean()
        
        self.dados = dados
        return True
    
    def backtest(self, capital_inicial=100000):
        """Run a simple backtest"""
        if self.dados is None or not self.calcular_indicadores():
            return None
            
        dados = self.dados
        
        # Initialize tracking variables
        capital = capital_inicial
        posicao_atual = None
        trades = []
        
        for i in range(1, len(dados)-1):
            data = dados.index[i]
            
            # Extract values safely
            high = self.get_scalar(dados['High'].iloc[i])
            low = self.get_scalar(dados['Low'].iloc[i])
            close = self.get_scalar(dados['Close'].iloc[i])
            atr = self.get_scalar(dados['ATR'].iloc[i])
            
            if pd.isna(atr):
                atr = close * 0.02  # Default to 2% of price
            
            # Check current position
            if posicao_atual is not None:
                # Check stop loss and take profit
                if posicao_atual['tipo'] == 'Compra':
                    # Stop loss hit
                    if low <= posicao_atual['stop_loss']:
                        resultado = (posicao_atual['stop_loss'] / posicao_atual['preco'] - 1) * posicao_atual['valor']
                        capital += posicao_atual['valor'] + resultado
                        
                        trades.append({
                            'tipo': 'Compra',
                            'entrada': posicao_atual['data'],
                            'saida': data,
                            'resultado': resultado,
                            'resultado_pct': resultado / posicao_atual['valor']
                        })
                        
                        posicao_atual = None
                        
                    # Take profit hit
                    elif high >= posicao_atual['take_profit']:
                        resultado = (posicao_atual['take_profit'] / posicao_atual['preco'] - 1) * posicao_atual['valor']
                        capital += posicao_atual['valor'] + resultado
                        
                        trades.append({
                            'tipo': 'Compra',
                            'entrada': posicao_atual['data'],
                            'saida': data,
                            'resultado': resultado,
                            'resultado_pct': resultado / posicao_atual['valor']
                        })
                        
                        posicao_atual = None
                
                elif posicao_atual['tipo'] == 'Venda':
                    # Stop loss hit
                    if high >= posicao_atual['stop_loss']:
                        resultado = (posicao_atual['preco'] / posicao_atual['stop_loss'] - 1) * posicao_atual['valor']
                        capital += posicao_atual['valor'] + resultado
                        
                        trades.append({
                            'tipo': 'Venda',
                            'entrada': posicao_atual['data'],
                            'saida': data,
                            'resultado': resultado,
                            'resultado_pct': resultado / posicao_atual['valor']
                        })
                        
                        posicao_atual = None
                        
                    # Take profit hit
                    elif low <= posicao_atual['take_profit']:
                        resultado = (posicao_atual['preco'] / posicao_atual['take_profit'] - 1) * posicao_atual['valor']
                        capital += posicao_atual['valor'] + resultado
                        
                        trades.append({
                            'tipo': 'Venda',
                            'entrada': posicao_atual['data'],
                            'saida': data,
                            'resultado': resultado,
                            'resultado_pct': resultado / posicao_atual['valor']
                        })
                        
                        posicao_atual = None
            
            # Look for new signals if no position
            if posicao_atual is None:
                buy_signal = self.get_scalar(dados['Buy_Signal'].iloc[i])
                sell_signal = self.get_scalar(dados['Sell_Signal'].iloc[i])
                
                # Buy signal
                if buy_signal == 1:
                    valor_operacao = capital * 0.1  # 10% of capital
                    
                    posicao_atual = {
                        'tipo': 'Compra',
                        'data': data,
                        'preco': close,
                        'stop_loss': close - (atr * 1.5),
                        'take_profit': close + (atr * 3.0),
                        'valor': valor_operacao
                    }
                    
                    capital -= valor_operacao
                    
                # Sell signal
                elif sell_signal == 1:
                    valor_operacao = capital * 0.1  # 10% of capital
                    
                    posicao_atual = {
                        'tipo': 'Venda',
                        'data': data,
                        'preco': close,
                        'stop_loss': close + (atr * 1.5),
                        'take_profit': close - (atr * 3.0),
                        'valor': valor_operacao
                    }
                    
                    capital -= valor_operacao
        
        # Close any open position at the end
        if posicao_atual is not None:
            last_close = self.get_scalar(dados['Close'].iloc[-1])
            
            if posicao_atual['tipo'] == 'Compra':
                resultado = (last_close / posicao_atual['preco'] - 1) * posicao_atual['valor']
            else:
                resultado = (posicao_atual['preco'] / last_close - 1) * posicao_atual['valor']
                
            capital += posicao_atual['valor'] + resultado
            
            trades.append({
                'tipo': posicao_atual['tipo'],
                'entrada': posicao_atual['data'],
                'saida': dados.index[-1],
                'resultado': resultado,
                'resultado_pct': resultado / posicao_atual['valor']
            })
        
        # Calculate performance metrics
        retorno_total = capital / capital_inicial - 1
        win_rate = len([t for t in trades if t['resultado'] > 0]) / max(1, len(trades))
        
        return {
            'retorno_total': retorno_total,
            'win_rate': win_rate,
            'num_trades': len(trades),
            'capital_final': capital,
            'trades': trades
        }

def otimizar_estrategia_simples(ativo):
    """Optimize strategy for an asset"""
    combinacoes = [
        {'filtro_tendencia': True, 'min_strength': 7},
        {'filtro_tendencia': False, 'min_strength': 7},
        {'filtro_tendencia': True, 'min_strength': 6},
        {'filtro_tendencia': False, 'min_strength': 6},
    ]
    
    resultados = []
    
    # Create strategy object
    estrategia = SimpleStrategy(ativo['ticker'], ativo['nome'])
    
    # Get data
    if not estrategia.obter_dados(ativo['inicio'], ativo['fim'], ativo['intervalo']):
        return None
    
    # Test each parameter combination
    for i, params in enumerate(combinacoes):
        print(f"Testando combinação {i+1}/{len(combinacoes)}: {params}")
        
        # Update parameters
        estrategia.filtro_tendencia = params['filtro_tendencia']
        estrategia.min_strength = params['min_strength']
        
        # Run backtest
        resultado = estrategia.backtest()
        
        if resultado:
            resultado['params'] = params
            resultados.append(resultado)
            print(f"Retorno: {resultado['retorno_total']:.2%}, Win Rate: {resultado['win_rate']:.2%}")
    
    # Sort by return
    if resultados:
        resultados.sort(key=lambda x: x['retorno_total'], reverse=True)
        
        print("\n=== MELHORES RESULTADOS PARA", ativo['nome'], "===")
        for i, res in enumerate(resultados[:2]):
            print(f"{i+1}. Retorno: {res['retorno_total']:.2%}, Win Rate: {res['win_rate']:.2%}")
            print(f"   Parâmetros: {res['params']}")
        
        return resultados[0]['params']
    
    return None

# Main execution
if __name__ == "__main__":
    # Assets to test
    ativos = [
        {"ticker": "^BVSP", "nome": "Ibovespa", "inicio": "2022-01-01", "fim": "2023-12-31", "intervalo": "1d"},
        {"ticker": "USDBRL=X", "nome": "USD/BRL", "inicio": "2022-01-01", "fim": "2023-12-31", "intervalo": "1d"}
    ]
    
    for ativo in ativos:
        print(f"\n{'='*50}")
        print(f"OTIMIZANDO {ativo['nome']}")
        print(f"{'='*50}")
        
        otimizar_estrategia_simples(ativo)
        
        print(f"\n{'-'*50}")
    
    print("\nOtimização concluída!")