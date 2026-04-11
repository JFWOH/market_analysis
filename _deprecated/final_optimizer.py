# final_optimizer.py
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

class RobustStrategy:
    """Strategy class that handles MultiIndex columns correctly"""
    
    def __init__(self, ticker, name):
        self.ticker = ticker
        self.name = name
        self.data = None
        
    def download_data(self, start_date, end_date, interval="1d"):
        """Download data and handle MultiIndex columns"""
        print(f"Downloading data for {self.name} ({self.ticker})...")
        
        try:
            # Download data
            data = yf.download(self.ticker, start=start_date, end=end_date, interval=interval, progress=False)
            
            if data.empty:
                print("No data returned")
                return False
                
            print(f"Downloaded {len(data)} periods")
            
            # Flatten MultiIndex columns if present
            if isinstance(data.columns, pd.MultiIndex):
                print("Flattening MultiIndex columns...")
                # Create new column names by joining the levels
                new_columns = []
                for col in data.columns:
                    if isinstance(col, tuple) and len(col) > 1:
                        # Use only the first level (price type) for simplicity
                        new_columns.append(col[0])
                    else:
                        new_columns.append(str(col))
                
                # Replace columns with flattened version
                data.columns = new_columns
                print(f"New columns: {data.columns.tolist()}")
            
            self.data = data
            return True
            
        except Exception as e:
            print(f"Error downloading data: {e}")
            return False
    
    def calculate_indicators(self):
        """Calculate basic technical indicators"""
        if self.data is None or self.data.empty:
            return False
            
        try:
            # Extract price columns
            close = self.data['Close']
            high = self.data['High']
            low = self.data['Low']
            
            # Moving Averages
            self.data['SMA_20'] = close.rolling(window=20).mean()
            self.data['SMA_50'] = close.rolling(window=50).mean()
            self.data['SMA_200'] = close.rolling(window=200).mean()
            
            # EMA
            self.data['EMA_8'] = close.ewm(span=8, adjust=False).mean()
            self.data['EMA_21'] = close.ewm(span=21, adjust=False).mean()
            
            # ATR - Average True Range
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            self.data['ATR'] = tr.rolling(window=14).mean()
            
            # RSI
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(window=14).mean()
            avg_loss = loss.rolling(window=14).mean()
            
            # Avoid division by zero
            rs = avg_gain / avg_loss.replace(0, np.nan)
            self.data['RSI'] = 100 - (100 / (1 + rs)).fillna(50)
            
            # MACD
            self.data['MACD'] = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
            self.data['MACD_Signal'] = self.data['MACD'].ewm(span=9, adjust=False).mean()
            
            # Basic signals
            self.data['Above_EMA21'] = (close > self.data['EMA_21']).astype(int)
            self.data['Below_EMA21'] = (close < self.data['EMA_21']).astype(int)
            
            self.data['RSI_High'] = (self.data['RSI'] > 70).astype(int)
            self.data['RSI_Low'] = (self.data['RSI'] < 30).astype(int)
            
            # Trend status
            self.data['Uptrend'] = ((close > self.data['SMA_50']) & 
                                  (self.data['SMA_20'] > self.data['SMA_50'])).astype(int)
            
            self.data['Downtrend'] = ((close < self.data['SMA_50']) & 
                                    (self.data['SMA_20'] < self.data['SMA_50'])).astype(int)
            
            print("Indicators calculated successfully")
            return True
            
        except Exception as e:
            print(f"Error calculating indicators: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_backtest(self, initial_capital=100000, risk_pct=0.01):
        """Run a simplified backtest"""
        if not self.calculate_indicators():
            return None
            
        data = self.data
        capital = initial_capital
        position = None
        trades = []
        equity = [initial_capital]
        dates = [data.index[0]]
        
        print("Running backtest...")
        
        # Process each day
        for i in range(20, len(data)-1):  # Start after indicators have enough data
            current_date = data.index[i]
            next_date = data.index[i+1]
            
            # Get current values
            close = data['Close'].iloc[i]
            next_open = data['Open'].iloc[i+1]
            next_high = data['High'].iloc[i+1]
            next_low = data['Low'].iloc[i+1]
            atr = data['ATR'].iloc[i]
            
            # Check for signal
            uptrend = data['Uptrend'].iloc[i] == 1
            downtrend = data['Downtrend'].iloc[i] == 1
            rsi_low = data['RSI_Low'].iloc[i] == 1
            rsi_high = data['RSI_High'].iloc[i] == 1
            
            # Default ATR if NaN
            if pd.isna(atr):
                atr = close * 0.02  # Use 2% of price as default
            
            # Handle open position
            if position is not None:
                if position['type'] == 'long':
                    # Check if stop loss hit
                    if next_low <= position['stop_loss']:
                        pct_change = (position['stop_loss'] / position['entry_price']) - 1
                        profit_loss = position['amount'] * pct_change
                        capital += position['amount'] + profit_loss
                        
                        trades.append({
                            'entry_date': position['entry_date'],
                            'exit_date': next_date,
                            'type': 'long',
                            'entry': position['entry_price'],
                            'exit': position['stop_loss'],
                            'profit_loss': profit_loss,
                            'pct_change': pct_change,
                            'exit_reason': 'stop_loss'
                        })
                        
                        position = None
                        
                    # Check if take profit hit
                    elif next_high >= position['take_profit']:
                        pct_change = (position['take_profit'] / position['entry_price']) - 1
                        profit_loss = position['amount'] * pct_change
                        capital += position['amount'] + profit_loss
                        
                        trades.append({
                            'entry_date': position['entry_date'],
                            'exit_date': next_date,
                            'type': 'long',
                            'entry': position['entry_price'],
                            'exit': position['take_profit'],
                            'profit_loss': profit_loss,
                            'pct_change': pct_change,
                            'exit_reason': 'take_profit'
                        })
                        
                        position = None
                
                elif position['type'] == 'short':
                    # Check if stop loss hit
                    if next_high >= position['stop_loss']:
                        pct_change = (position['entry_price'] / position['stop_loss']) - 1
                        profit_loss = position['amount'] * pct_change
                        capital += position['amount'] + profit_loss
                        
                        trades.append({
                            'entry_date': position['entry_date'],
                            'exit_date': next_date,
                            'type': 'short',
                            'entry': position['entry_price'],
                            'exit': position['stop_loss'],
                            'profit_loss': profit_loss,
                            'pct_change': pct_change,
                            'exit_reason': 'stop_loss'
                        })
                        
                        position = None
                        
                    # Check if take profit hit
                    elif next_low <= position['take_profit']:
                        pct_change = (position['entry_price'] / position['take_profit']) - 1
                        profit_loss = position['amount'] * pct_change
                        capital += position['amount'] + profit_loss
                        
                        trades.append({
                            'entry_date': position['entry_date'],
                            'exit_date': next_date,
                            'type': 'short',
                            'entry': position['entry_price'],
                            'exit': position['take_profit'],
                            'profit_loss': profit_loss,
                            'pct_change': pct_change,
                            'exit_reason': 'take_profit'
                        })
                        
                        position = None
            
            # Check for new entry if no position
            if position is None:
                # Long entry: Uptrend + RSI oversold
                if uptrend and rsi_low:
                    # Calculate position size (1% risk)
                    stop_loss = next_open - (atr * 1.5)
                    risk_per_share = next_open - stop_loss
                    shares = (capital * risk_pct) / risk_per_share
                    position_amount = shares * next_open
                    
                    # Cap at 10% of capital
                    position_amount = min(position_amount, capital * 0.1)
                    
                    if position_amount >= 1000:  # Minimum position size
                        position = {
                            'type': 'long',
                            'entry_date': next_date,
                            'entry_price': next_open,
                            'stop_loss': stop_loss,
                            'take_profit': next_open + (atr * 3),  # 2:1 reward/risk
                            'amount': position_amount
                        }
                        capital -= position_amount
                
                # Short entry: Downtrend + RSI overbought
                elif downtrend and rsi_high:
                    # Calculate position size (1% risk)
                    stop_loss = next_open + (atr * 1.5)
                    risk_per_share = stop_loss - next_open
                    shares = (capital * risk_pct) / risk_per_share
                    position_amount = shares * next_open
                    
                    # Cap at 10% of capital
                    position_amount = min(position_amount, capital * 0.1)
                    
                    if position_amount >= 1000:  # Minimum position size
                        position = {
                            'type': 'short',
                            'entry_date': next_date,
                            'entry_price': next_open,
                            'stop_loss': stop_loss,
                            'take_profit': next_open - (atr * 3),  # 2:1 reward/risk
                            'amount': position_amount
                        }
                        capital -= position_amount
            
            # Track equity
            current_equity = capital
            if position is not None:
                current_equity += position['amount']
            
            equity.append(current_equity)
            dates.append(current_date)
        
        # Close any open position at the end
        if position is not None:
            last_close = data['Close'].iloc[-1]
            
            if position['type'] == 'long':
                pct_change = (last_close / position['entry_price']) - 1
            else:  # short
                pct_change = (position['entry_price'] / last_close) - 1
                
            profit_loss = position['amount'] * pct_change
            capital += position['amount'] + profit_loss
            
            trades.append({
                'entry_date': position['entry_date'],
                'exit_date': data.index[-1],
                'type': position['type'],
                'entry': position['entry_price'],
                'exit': last_close,
                'profit_loss': profit_loss,
                'pct_change': pct_change,
                'exit_reason': 'backtest_end'
            })
        
        # Calculate metrics
        if len(trades) > 0:
            win_count = sum(1 for t in trades if t['profit_loss'] > 0)
            win_rate = win_count / len(trades)
            
            profit_trades = [t for t in trades if t['profit_loss'] > 0]
            loss_trades = [t for t in trades if t['profit_loss'] <= 0]
            
            avg_win = sum(t['profit_loss'] for t in profit_trades) / max(1, len(profit_trades))
            avg_loss = sum(t['profit_loss'] for t in loss_trades) / max(1, len(loss_trades))
            
            profit_factor = abs(sum(t['profit_loss'] for t in profit_trades) / 
                             sum(t['profit_loss'] for t in loss_trades)) if loss_trades else float('inf')
        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0
        
        # Calculate drawdown
        max_equity = pd.Series(equity).cummax()
        drawdown = ((pd.Series(equity) / max_equity) - 1) * 100
        max_drawdown = abs(drawdown.min())
        
        return {
            'initial_capital': initial_capital,
            'final_capital': capital,
            'return': (capital / initial_capital) - 1,
            'trades': trades,
            'win_rate': win_rate,
            'trade_count': len(trades),
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'equity': equity,
            'dates': dates
        }

def optimize_simple(ticker, name, start_date, end_date, interval="1d"):
    """Run a simplified optimization"""
    # Create strategy
    strategy = RobustStrategy(ticker, name)
    
    # Download data
    if not strategy.download_data(start_date, end_date, interval):
        print(f"Failed to download data for {name}")
        return None
    
    # Run backtest
    results = strategy.run_backtest()
    
    if results:
        print("\n" + "=" * 40)
        print(f"BACKTEST RESULTS FOR {name}")
        print("=" * 40)
        print(f"Initial Capital: ${results['initial_capital']:.2f}")
        print(f"Final Capital: ${results['final_capital']:.2f}")
        print(f"Return: {results['return']:.2%}")
        print(f"Number of Trades: {results['trade_count']}")
        print(f"Win Rate: {results['win_rate']:.2%}")
        print(f"Profit Factor: {results['profit_factor']:.2f}")
        print(f"Maximum Drawdown: {results['max_drawdown']:.2%}")
        
        # Print some sample trades
        if results['trades']:
            print("\nSample trades:")
            for i, trade in enumerate(results['trades'][:5]):
                print(f"{i+1}. {trade['type']} from {trade['entry_date'].date()} to {trade['exit_date'].date()}: {trade['pct_change']:.2%}")
        
        return results
    
    return None

if __name__ == "__main__":
    # Test assets
    assets = [
        {"ticker": "^BVSP", "name": "Ibovespa", "start": "2022-01-01", "end": "2023-12-31"},
        {"ticker": "USDBRL=X", "name": "USD/BRL", "start": "2022-01-01", "end": "2023-12-31"}
    ]
    
    for asset in assets:
        print(f"\n{'='*50}")
        print(f"TESTING {asset['name']}")
        print(f"{'='*50}")
        
        result = optimize_simple(
            asset['ticker'], 
            asset['name'],
            asset['start'],
            asset['end']
        )
        
        print("\n")