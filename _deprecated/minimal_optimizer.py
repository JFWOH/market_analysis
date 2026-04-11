# minimal_optimizer.py
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

def analyze_data(ticker, start_date, end_date, interval="1d"):
    """Simple function to download and analyze data structure"""
    print(f"Downloading data for {ticker}...")
    try:
        data = yf.download(ticker, start=start_date, end=end_date, interval=interval)
        print(f"Downloaded {len(data)} periods")
        
        # Print column structure details
        print("\nColumn structure analysis:")
        print(f"Type of columns: {type(data.columns)}")
        print(f"Columns: {data.columns.tolist()}")
        
        if isinstance(data.columns, pd.MultiIndex):
            print("\nThis is a MultiIndex structure!")
            print("First level values:", data.columns.get_level_values(0).tolist())
            if data.columns.nlevels > 1:
                print("Second level values:", data.columns.get_level_values(1).tolist())
        
        # Check if we have any data
        if data.empty:
            print("No data returned for this ticker")
            return None
            
        # Print first row to see data format
        print("\nFirst row sample:")
        print(data.iloc[0])
        
        # Identify which column would be closest to 'Close'
        close_candidates = [col for col in data.columns if 'close' in str(col).lower()]
        if close_candidates:
            print(f"\nPossible 'Close' columns: {close_candidates}")
        else:
            print("\nNo column name containing 'close' found.")
            
        return data
    except Exception as e:
        print(f"Error downloading data: {e}")
        return None

def run_simple_test():
    """Run tests for each market"""
    print("=" * 50)
    print("TESTING BRAZILIAN MARKET DATA STRUCTURE")
    print("=" * 50)
    
    # Test Ibovespa
    print("\nTesting Ibovespa (^BVSP):")
    ibov_data = analyze_data("^BVSP", "2023-01-01", "2023-01-10")
    
    # Test USD/BRL
    print("\nTesting USD/BRL (USDBRL=X):")
    usdbrl_data = analyze_data("USDBRL=X", "2023-01-01", "2023-01-10")
    
    # Test alternative tickers if needed
    print("\nTesting alternative Ibovespa ticker (IBOV.SA):")
    ibov_alt_data = analyze_data("IBOV.SA", "2023-01-01", "2023-01-10")

if __name__ == "__main__":
    run_simple_test()