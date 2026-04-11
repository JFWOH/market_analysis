# enhanced_strategy.py
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import itertools
import os
from tqdm import tqdm

class PriceActionStrategy:
    """Enhanced trading strategy with price action patterns"""
    
    def __init__(self, ticker, name, params=None):
        self.ticker = ticker
        self.name = name
        self.data = None
        
        # Default parameters
        self.params = {
            # Technical indicators
            'ema_short': 8,      # Short EMA period
            'ema_medium': 21,    # Medium EMA period
            'ema_long': 55,      # Long EMA period
            
            # Price action
            'pin_bar_threshold': 0.6,   # Minimum wick ratio for pin bars
            'engulfing_strength': 1.2,  # Size multiplier for engulfing patterns
            
            # Risk management
            'atr_stop_multiplier': 1.5,    # ATR multiplier for stop loss
            'atr_target_multiplier': 3.0,  # ATR multiplier for take profit
            'max_risk_pct': 0.01,          # Maximum risk per trade
            'max_position_pct': 0.1,       # Maximum position size as % of capital
            
            # Filters
            'use_trend_filter': True,      # Use trend filter for entries
            'use_volume_filter': True,     # Use volume filter for confirmation
            'min_pattern_strength': 7,     # Minimum strength for pattern (1-10)
            
            # Trading rules
            'allow_long': True,            # Allow long positions
            'allow_short': True            # Allow short positions
        }
        
        # Update with custom parameters if provided
        if params:
            for key, value in params.items():
                if key in self.params:
                    self.params[key] = value
    
    def download_data(self, start_date, end_date, interval="1d"):
        """Download historical data and handle MultiIndex columns"""
        print(f"Downloading data for {self.name} ({self.ticker})...")
        
        try:
            data = yf.download(self.ticker, start=start_date, end=end_date, interval=interval, progress=False)
            
            if data.empty:
                print(f"No data available for {self.ticker}")
                return False
                
            print(f"Downloaded {len(data)} periods")
            
            # Flatten MultiIndex columns if present
            if isinstance(data.columns, pd.MultiIndex):
                print("Handling MultiIndex columns...")
                new_columns = []
                for col in data.columns:
                    if isinstance(col, tuple) and len(col) > 1:
                        new_columns.append(col[0])
                    else:
                        new_columns.append(str(col))
                
                data.columns = new_columns
            
            self.data = data
            return True
            
        except Exception as e:
            print(f"Error downloading data: {e}")
            return False
    
    def calculate_indicators(self):
        """Calculate all technical indicators and price action patterns"""
        if self.data is None or self.data.empty:
            return False
            
        try:
            data = self.data
            
            # Extract price series
            close = data['Close']
            open_price = data['Open']
            high = data['High']
            low = data['Low']
            
            # ===== BASIC INDICATORS =====
            
            # Moving Averages
            data['SMA_20'] = close.rolling(window=20).mean()
            data['SMA_50'] = close.rolling(window=50).mean()
            data['SMA_200'] = close.rolling(window=200).mean()
            
            # Exponential Moving Averages
            data['EMA_' + str(self.params['ema_short'])] = close.ewm(span=self.params['ema_short'], adjust=False).mean()
            data['EMA_' + str(self.params['ema_medium'])] = close.ewm(span=self.params['ema_medium'], adjust=False).mean()
            data['EMA_' + str(self.params['ema_long'])] = close.ewm(span=self.params['ema_long'], adjust=False).mean()
            
            # ATR - Average True Range
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            data['ATR'] = tr.rolling(window=14).mean()
            
            # RSI
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(window=14).mean()
            avg_loss = loss.rolling(window=14).mean()
            
            # Avoid division by zero
            rs = avg_gain / avg_loss.replace(0, np.nan)
            data['RSI'] = 100 - (100 / (1 + rs)).fillna(50)
            
            # MACD
            data['MACD'] = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
            data['MACD_Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
            data['MACD_Hist'] = data['MACD'] - data['MACD_Signal']
            
            # ===== PRICE ACTION PATTERNS =====
            
            # Candle classification
            data['Candle_Range'] = high - low
            data['Candle_Body'] = abs(close - open_price)
            data['Candle_Body_Ratio'] = data['Candle_Body'] / data['Candle_Range'].replace(0, np.nan).fillna(0.5)
            
            # Directional candles
            data['Bullish_Candle'] = (close > open_price).astype(int)
            data['Bearish_Candle'] = (close < open_price).astype(int)
            
            # Up/down movements
            data['Higher_High'] = (high > high.shift()).astype(int)
            data['Lower_Low'] = (low < low.shift()).astype(int)
            data['Higher_Close'] = (close > close.shift()).astype(int)
            data['Lower_Close'] = (close < close.shift()).astype(int)
            
            # Wicks calculation
            data['Upper_Wick'] = high - np.maximum(close, open_price)
            data['Lower_Wick'] = np.minimum(close, open_price) - low
            data['Upper_Wick_Ratio'] = data['Upper_Wick'] / data['Candle_Range'].replace(0, np.nan).fillna(0)
            data['Lower_Wick_Ratio'] = data['Lower_Wick'] / data['Candle_Range'].replace(0, np.nan).fillna(0)
            
            # Pin bars (price rejection)
            pin_bar_threshold = self.params['pin_bar_threshold']
            data['Bullish_Pin_Bar'] = ((data['Lower_Wick_Ratio'] > pin_bar_threshold) & 
                                     (data['Candle_Body_Ratio'] < 0.3) &
                                     (data['Lower_Low'] == 1)).astype(int)
            
            data['Bearish_Pin_Bar'] = ((data['Upper_Wick_Ratio'] > pin_bar_threshold) & 
                                      (data['Candle_Body_Ratio'] < 0.3) & 
                                      (data['Higher_High'] == 1)).astype(int)
            
            # Engulfing patterns
            engulfing_strength = self.params['engulfing_strength']
            
            # Bullish engulfing
            data['Bullish_Engulfing'] = (
                (data['Bullish_Candle'] == 1) & 
                (data['Bearish_Candle'].shift() == 1) & 
                (data['Candle_Body'] > data['Candle_Body'].shift() * engulfing_strength) &
                (open_price < close.shift()) & 
                (close > open_price.shift())
            ).astype(int)
            
            # Bearish engulfing
            data['Bearish_Engulfing'] = (
                (data['Bearish_Candle'] == 1) & 
                (data['Bullish_Candle'].shift() == 1) & 
                (data['Candle_Body'] > data['Candle_Body'].shift() * engulfing_strength) &
                (open_price > close.shift()) & 
                (close < open_price.shift())
            ).astype(int)
            
            # Inside bars (consolidation)
            data['Inside_Bar'] = (
                (high <= high.shift()) & 
                (low >= low.shift())
            ).astype(int)
            
            # Outside bars (volatility expansion)
            data['Outside_Bar'] = (
                (high > high.shift()) & 
                (low < low.shift())
            ).astype(int)
            
            # Trend identification
            ema_short = data['EMA_' + str(self.params['ema_short'])]
            ema_medium = data['EMA_' + str(self.params['ema_medium'])]
            ema_long = data['EMA_' + str(self.params['ema_long'])]
            
            data['Uptrend'] = ((close > ema_medium) & (ema_short > ema_medium) & (ema_medium > ema_long)).astype(int)
            data['Downtrend'] = ((close < ema_medium) & (ema_short < ema_medium) & (ema_medium < ema_long)).astype(int)
            data['Sideways'] = ((~data['Uptrend'].astype(bool)) & (~data['Downtrend'].astype(bool))).astype(int)
            
            # Volume analysis (if volume data is available)
            if 'Volume' in data.columns and not data['Volume'].isnull().all():
                data['Volume_SMA20'] = data['Volume'].rolling(window=20).mean()
                data['Volume_Ratio'] = data['Volume'] / data['Volume_SMA20']
                data['High_Volume'] = (data['Volume_Ratio'] > 1.5).astype(int)
                data['Low_Volume'] = (data['Volume_Ratio'] < 0.5).astype(int)
                
                # Classify volume direction
                data['Up_Volume'] = data['Volume'] * data['Bullish_Candle']
                data['Down_Volume'] = data['Volume'] * data['Bearish_Candle']
            else:
                # Create placeholder columns if volume data is unavailable
                data['High_Volume'] = 1  # Default to high volume
                data['Volume_Ratio'] = 1
            
            # ===== GENERATE TRADE SIGNALS =====
            
            # Long signals
            data['Long_Signal'] = 0
            
            # Bullish pin bar in uptrend or at support
            if self.params['allow_long']:
                data.loc[
                    (data['Bullish_Pin_Bar'] == 1) & 
                    ((~self.params['use_trend_filter']) | (data['Uptrend'] == 1)) &
                    ((~self.params['use_volume_filter']) | (data['Volume_Ratio'] >= 1.0)),
                    'Long_Signal'
                ] = 8  # Strength 8/10
                
                # Bullish engulfing
                data.loc[
                    (data['Bullish_Engulfing'] == 1) & 
                    ((~self.params['use_trend_filter']) | (data['Uptrend'] == 1)) &
                    ((~self.params['use_volume_filter']) | (data['Volume_Ratio'] >= 1.0)),
                    'Long_Signal'
                ] = max(data['Long_Signal'].max(), 7)  # Strength 7/10 (if not already higher)
                
                # Inside bar in uptrend (continuation)
                data.loc[
                    (data['Inside_Bar'] == 1) & 
                    (data['Uptrend'] == 1) &
                    (data['Higher_Close'].shift() == 1),
                    'Long_Signal'
                ] = max(data['Long_Signal'].max(), 6)  # Strength 6/10
            
            # Short signals
            data['Short_Signal'] = 0
            
            # Bearish pin bar in downtrend or at resistance
            if self.params['allow_short']:
                data.loc[
                    (data['Bearish_Pin_Bar'] == 1) & 
                    ((~self.params['use_trend_filter']) | (data['Downtrend'] == 1)) &
                    ((~self.params['use_volume_filter']) | (data['Volume_Ratio'] >= 1.0)),
                    'Short_Signal'
                ] = 8  # Strength 8/10
                
                # Bearish engulfing
                data.loc[
                    (data['Bearish_Engulfing'] == 1) & 
                    ((~self.params['use_trend_filter']) | (data['Downtrend'] == 1)) &
                    ((~self.params['use_volume_filter']) | (data['Volume_Ratio'] >= 1.0)),
                    'Short_Signal'
                ] = max(data['Short_Signal'].max(), 7)  # Strength 7/10
                
                # Inside bar in downtrend (continuation)
                data.loc[
                    (data['Inside_Bar'] == 1) & 
                    (data['Downtrend'] == 1) &
                    (data['Lower_Close'].shift() == 1),
                    'Short_Signal'
                ] = max(data['Short_Signal'].max(), 6)  # Strength 6/10
            
            # Filter by minimum pattern strength
            min_strength = self.params['min_pattern_strength']
            data.loc[data['Long_Signal'] < min_strength, 'Long_Signal'] = 0
            data.loc[data['Short_Signal'] < min_strength, 'Short_Signal'] = 0
            
            self.data = data
            print("Indicators and patterns calculated successfully")
            return True
            
        except Exception as e:
            print(f"Error calculating indicators: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_backtest(self, initial_capital=100000):
        """Run backtest with current parameters"""
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
                            'exit_reason': 'stop_loss',
                            'pattern': position['pattern']
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
                            'exit_reason': 'take_profit',
                            'pattern': position['pattern']
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
                            'exit_reason': 'stop_loss',
                            'pattern': position['pattern']
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
                            'exit_reason': 'take_profit',
                            'pattern': position['pattern']
                        })
                        
                        position = None
            
            # Check for new entry if no position
            if position is None:
                # Long signal
                if data['Long_Signal'].iloc[i] > 0:
                    # Calculate position size based on risk
                    stop_loss = next_open - (atr * self.params['atr_stop_multiplier'])
                    risk_per_share = next_open - stop_loss
                    
                    # Avoid division by zero
                    if risk_per_share > 0:
                        shares = (capital * self.params['max_risk_pct']) / risk_per_share
                        position_amount = shares * next_open
                        
                        # Cap at maximum position size
                        position_amount = min(position_amount, capital * self.params['max_position_pct'])
                        
                        if position_amount >= 1000:  # Minimum position size
                            pattern = 'Bullish_Pin_Bar' if data['Bullish_Pin_Bar'].iloc[i] == 1 else \
                                     ('Bullish_Engulfing' if data['Bullish_Engulfing'].iloc[i] == 1 else 'Other_Bullish')
                            
                            position = {
                                'type': 'long',
                                'entry_date': next_date,
                                'entry_price': next_open,
                                'stop_loss': stop_loss,
                                'take_profit': next_open + (atr * self.params['atr_target_multiplier']),
                                'amount': position_amount,
                                'pattern': pattern
                            }
                            capital -= position_amount
                
                # Short signal
                elif data['Short_Signal'].iloc[i] > 0:
                    # Calculate position size based on risk
                    stop_loss = next_open + (atr * self.params['atr_stop_multiplier'])
                    risk_per_share = stop_loss - next_open
                    
                    # Avoid division by zero
                    if risk_per_share > 0:
                        shares = (capital * self.params['max_risk_pct']) / risk_per_share
                        position_amount = shares * next_open
                        
                        # Cap at maximum position size
                        position_amount = min(position_amount, capital * self.params['max_position_pct'])
                        
                        if position_amount >= 1000:  # Minimum position size
                            pattern = 'Bearish_Pin_Bar' if data['Bearish_Pin_Bar'].iloc[i] == 1 else \
                                     ('Bearish_Engulfing' if data['Bearish_Engulfing'].iloc[i] == 1 else 'Other_Bearish')
                            
                            position = {
                                'type': 'short',
                                'entry_date': next_date,
                                'entry_price': next_open,
                                'stop_loss': stop_loss,
                                'take_profit': next_open - (atr * self.params['atr_target_multiplier']),
                                'amount': position_amount,
                                'pattern': pattern
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
                'exit_reason': 'backtest_end',
                'pattern': position['pattern']
            })
        
        # Calculate metrics
        if len(trades) > 0:
            win_count = sum(1 for t in trades if t['profit_loss'] > 0)
            win_rate = win_count / len(trades)
            
            profit_trades = [t for t in trades if t['profit_loss'] > 0]
            loss_trades = [t for t in trades if t['profit_loss'] <= 0]
            
            avg_win = sum(t['profit_loss'] for t in profit_trades) / max(1, len(profit_trades))
            avg_loss = sum(t['profit_loss'] for t in loss_trades) / max(1, len(loss_trades))
            
            # Avoid division by zero
            total_loss = sum(t['profit_loss'] for t in loss_trades)
            profit_factor = abs(sum(t['profit_loss'] for t in profit_trades) / total_loss) if total_loss != 0 else float('inf')
        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0
        
        # Calculate drawdown
        max_equity = pd.Series(equity).cummax()
        drawdown = ((pd.Series(equity) / max_equity) - 1) * 100
        max_drawdown = abs(drawdown.min())
        
        # Calculate annualized return
        days = (data.index[-1] - data.index[0]).days
        years = max(days / 365.0, 0.1)  # At least 0.1 years to avoid division by zero
        annualized_return = ((capital / initial_capital) ** (1/years)) - 1
        
        # Calculate Sharpe ratio (simplified)
        equity_series = pd.Series(equity, index=dates)
        daily_returns = equity_series.pct_change().dropna()
        sharpe_ratio = np.sqrt(252) * daily_returns.mean() / max(daily_returns.std(), 0.0001)
        
        # Pattern performance
        pattern_stats = {}
        if len(trades) > 0:
            # Group by pattern
            for trade in trades:
                pattern = trade['pattern']
                if pattern not in pattern_stats:
                    pattern_stats[pattern] = {
                        'count': 0,
                        'wins': 0,
                        'losses': 0,
                        'profit': 0
                    }
                
                pattern_stats[pattern]['count'] += 1
                if trade['profit_loss'] > 0:
                    pattern_stats[pattern]['wins'] += 1
                else:
                    pattern_stats[pattern]['losses'] += 1
                    
                pattern_stats[pattern]['profit'] += trade['profit_loss']
        
        return {
            'initial_capital': initial_capital,
            'final_capital': capital,
            'absolute_return': capital - initial_capital,
            'return_pct': (capital / initial_capital) - 1,
            'annualized_return': annualized_return,
            'trades': trades,
            'win_rate': win_rate,
            'trade_count': len(trades),
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'equity': equity,
            'dates': dates,
            'pattern_stats': pattern_stats
        }

def run_grid_optimization(ticker, name, start_train, end_train, params_grid):
    """Run grid search optimization"""
    print(f"Starting grid optimization for {name}...")
    print(f"Testing {len(params_grid)} parameter combinations")
    
    results = []
    
    # Create a progress bar
    for i, params in enumerate(tqdm(params_grid, desc="Optimizing")):
        # Create strategy with these parameters
        strategy = PriceActionStrategy(ticker, name, params)
        
        # Download data (only for the first iteration)
        if i == 0:
            if not strategy.download_data(start_train, end_train):
                print(f"Failed to download data for {name}")
                return None
            # Cache the data for reuse
            cached_data = strategy.data.copy()
        else:
            # Reuse cached data to save time
            strategy.data = cached_data.copy()
        
        # Run backtest
        result = strategy.run_backtest()
        
        if result:
            # Store parameters with results
            result['params'] = params
            results.append(result)
    
    # Sort results by return
    results.sort(key=lambda x: x['return_pct'], reverse=True)
    
    # Print top results
    print("\n" + "=" * 40)
    print(f"TOP OPTIMIZATION RESULTS FOR {name}")
    print("=" * 40)
    
    for i, result in enumerate(results[:5]):
        print(f"\n{i+1}. Return: {result['return_pct']:.2%}, Win Rate: {result['win_rate']:.2%}, Trades: {result['trade_count']}")
        print(f"   Sharpe: {result['sharpe_ratio']:.2f}, Max Drawdown: {result['max_drawdown']:.2%}")
        print(f"   Parameters: {result['params']}")
    
    # Create visualization for top result
    if results:
        best_result = results[0]
        visualize_results(best_result, name, "optimization")
    
    return results

def generate_parameter_grid():
    """Generate a grid of parameters to test"""
    param_grid = {
        'ema_short': [8, 9, 13],
        'ema_medium': [21, 34],
        'ema_long': [55, 89],
        'pin_bar_threshold': [0.5, 0.6, 0.7],
        'engulfing_strength': [1.0, 1.2, 1.5],
        'atr_stop_multiplier': [1.0, 1.5, 2.0],
        'atr_target_multiplier': [2.0, 3.0, 4.0],
        'use_trend_filter': [True, False],
        'use_volume_filter': [True, False],
        'min_pattern_strength': [6, 7, 8]
    }
    
    # Generate all combinations
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    
    # Limit number of combinations to prevent excessive runtime
    # We'll take a subset of parameters for efficiency
    limited_keys = ['ema_short', 'ema_medium', 'use_trend_filter', 'min_pattern_strength', 'atr_stop_multiplier']
    limited_grid = {k: param_grid[k] for k in limited_keys}
    
    # Generate combinations
    combinations = list(itertools.product(*[param_grid[k] for k in limited_keys]))
    
    # Convert to list of dictionaries
    param_list = []
    for combo in combinations:
        param_dict = {limited_keys[i]: combo[i] for i in range(len(limited_keys))}
        # Add default values for other parameters
        for k in param_grid:
            if k not in param_dict:
                param_dict[k] = param_grid[k][0]  # Use first value as default
        param_list.append(param_dict)
    
    return param_list

def visualize_results(result, asset_name, folder="results"):
    """Create visualization for backtest results"""
    if not os.path.exists(folder):
        os.makedirs(folder)
    
    # 1. Equity curve
    plt.figure(figsize=(12, 6))
    plt.plot(result['dates'], result['equity'], linewidth=2)
    plt.title(f'Equity Curve - {asset_name}', fontsize=14)
    plt.xlabel('Date', fontsize=12)
    plt.ylabel('Capital ($)', fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.savefig(os.path.join(folder, f'{asset_name}_equity.png'))
    
    # 2. Pattern performance
    if result['pattern_stats']:
        plt.figure(figsize=(12, 6))
        patterns = list(result['pattern_stats'].keys())
        profits = [result['pattern_stats'][p]['profit'] for p in patterns]
        counts = [result['pattern_stats'][p]['count'] for p in patterns]
        
        # Sort by profit
        sorted_indices = np.argsort(profits)
        patterns = [patterns[i] for i in sorted_indices]
        profits = [profits[i] for i in sorted_indices]
        counts = [counts[i] for i in sorted_indices]
        
        # Create bar chart
        bars = plt.bar(patterns, profits, color=['green' if p > 0 else 'red' for p in profits])
        
        # Add count labels
        for i, bar in enumerate(bars):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 500, 
                    f'n={counts[i]}', ha='center', va='bottom', fontsize=10)
        
        plt.title(f'Pattern Performance - {asset_name}', fontsize=14)
        plt.ylabel('Profit ($)', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.grid(True, alpha=0.3, axis='y')
        plt.tight_layout()
        plt.savefig(os.path.join(folder, f'{asset_name}_patterns.png'))
    
    # 3. Drawdown chart
    equity_series = pd.Series(result['equity'], index=result['dates'])
    max_equity = equity_series.cummax()
    drawdown = ((equity_series / max_equity) - 1) * 100
    
    plt.figure(figsize=(12, 6))
    plt.fill_between(drawdown.index, drawdown.values, 0, color='red', alpha=0.3)
    plt.title(f'Drawdown - {asset_name}', fontsize=14)
    plt.xlabel('Date', fontsize=12)
    plt.ylabel('Drawdown (%)', fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.savefig(os.path.join(folder, f'{asset_name}_drawdown.png'))
    
    print(f"Visualizations saved in {folder} folder")

def run_strategy_optimization():
    """Main function to run optimization"""
    print("=" * 50)
    print("PRICE ACTION STRATEGY OPTIMIZATION")
    print("=" * 50)
    
    # Assets to test
    assets = [
        {"ticker": "^BVSP", "name": "Ibovespa", "start_train": "2020-01-01", "end_train": "2023-06-30", 
         "start_test": "2023-07-01", "end_test": "2023-12-31"},
        {"ticker": "USDBRL=X", "name": "USD/BRL", "start_train": "2020-01-01", "end_train": "2023-06-30", 
         "start_test": "2023-07-01", "end_test": "2023-12-31"}
    ]
    
    # Generate parameter grid
    params_grid = generate_parameter_grid()
    print(f"Generated {len(params_grid)} parameter combinations for testing")
    
    for asset in assets:
        print(f"\n{'='*50}")
        print(f"OPTIMIZING {asset['name']}")
        print(f"{'='*50}")
        
        # Run optimization on training data
        results = run_grid_optimization(
            asset['ticker'],
            asset['name'],
            asset['start_train'],
            asset['end_train'],
            params_grid
        )
        
        if results and len(results) > 0:
            best_params = results[0]['params']
            
            print(f"\nBest parameters found for {asset['name']}:")
            for param, value in best_params.items():
                print(f"  {param}: {value}")
            
            # Validate on test data
            print(f"\nValidating on test period ({asset['start_test']} to {asset['end_test']})...")
            validation_strategy = PriceActionStrategy(asset['ticker'], asset['name'], best_params)
            
            if validation_strategy.download_data(asset['start_test'], asset['end_test']):
                validation_result = validation_strategy.run_backtest()
                
                if validation_result:
                    print("\n" + "=" * 40)
                    print(f"VALIDATION RESULTS FOR {asset['name']}")
                    print("=" * 40)
                    print(f"Return: {validation_result['return_pct']:.2%}")
                    print(f"Annualized Return: {validation_result['annualized_return']:.2%}")
                    print(f"Win Rate: {validation_result['win_rate']:.2%}")
                    print(f"Trades: {validation_result['trade_count']}")
                    print(f"Profit Factor: {validation_result['profit_factor']:.2f}")
                    print(f"Max Drawdown: {validation_result['max_drawdown']:.2%}")
                    print(f"Sharpe Ratio: {validation_result['sharpe_ratio']:.2f}")
                    
                    # Visualize validation results
                    visualize_results(validation_result, f"{asset['name']}_validation", "validation")
                    
                    # Save the best parameters
                    with open(f"best_params_{asset['name']}.txt", 'w') as f:
                        for param, value in best_params.items():
                            f.write(f"{param}: {value}\n")
            else:
                print("Failed to download test data for validation")
        else:
            print(f"No valid results found for {asset['name']}")
        
        print(f"\n{'-'*50}")
    
    print("\nOptimization completed!")

if __name__ == "__main__":
    run_strategy_optimization()