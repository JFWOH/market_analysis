# test_data.py
import yfinance as yf
import pandas as pd

print("Testing data availability for Brazilian market...")

# Test various ticker formats for Ibovespa
ibov_tickers = ["^BVSP", "IBOV.SA", "IBOV"]
for ticker in ibov_tickers:
    print(f"\nTrying ticker: {ticker}")
    try:
        data = yf.download(ticker, period="1d", interval="1h")
        print(f"Success! Rows: {len(data)}, Columns: {data.columns.tolist()}")
        if not data.empty:
            print("Sample data:")
            print(data.head(1))
    except Exception as e:
        print(f"Error: {e}")

# Test various ticker formats for USD/BRL
usd_tickers = ["BRL=X", "USDBRL=X", "BRLUSD=X", "USD-BRL"]
for ticker in usd_tickers:
    print(f"\nTrying ticker: {ticker}")
    try:
        data = yf.download(ticker, period="1d", interval="1h")
        print(f"Success! Rows: {len(data)}, Columns: {data.columns.tolist()}")
        if not data.empty:
            print("Sample data:")
            print(data.head(1))
    except Exception as e:
        print(f"Error: {e}")