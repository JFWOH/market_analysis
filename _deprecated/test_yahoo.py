# test_yahoo.py
import yfinance as yf
import pandas as pd

def test_data_fetch():
    print("Testing Yahoo Finance data retrieval...")
    
    # Try to get Ibovespa data
    print("Fetching Ibovespa data...")
    ibov_data = yf.download(
        tickers="^BVSP",
        period="1d",
        interval="5m",
        progress=False
    )
    
    print(f"Received {len(ibov_data)} rows of Ibovespa data")
    if not ibov_data.empty:
        print("First few rows:")
        print(ibov_data.head())
    else:
        print("No data received for Ibovespa")
    
    # Try to get BRL/USD data
    print("\nFetching USD/BRL data...")
    brl_data = yf.download(
        tickers="BRL=X",
        period="1d",
        interval="5m",
        progress=False
    )
    
    print(f"Received {len(brl_data)} rows of USD/BRL data")
    if not brl_data.empty:
        print("First few rows:")
        print(brl_data.head())
    else:
        print("No data received for USD/BRL")

if __name__ == "__main__":
    test_data_fetch()