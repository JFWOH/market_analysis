# test_imports.py
try:
    import pandas as pd
    print("Pandas imported successfully, version:", pd.__version__)
except ImportError:
    print("Failed to import pandas")

try:
    import yfinance as yf
    print("yfinance imported successfully, version:", yf.__version__)
except ImportError:
    print("Failed to import yfinance")