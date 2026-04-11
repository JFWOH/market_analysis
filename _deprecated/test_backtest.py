print("Backtester Test - Starting...")

try:
    # Basic imports
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    import yfinance as yf
    
    print("Libraries imported successfully!")
    
    # Test downloading some data
    print("Testing data download...")
    data = yf.download("^BVSP", period="5d")
    print(f"Downloaded {len(data)} rows of data")
    print("First few rows:")
    print(data.head())
    
    # Try to create a simple chart
    print("Creating a test chart...")
    plt.figure(figsize=(10, 6))
    plt.plot(data.index, data['Close'])
    plt.title('Ibovespa - Last 5 Days')
    plt.savefig('test_chart.png')
    print("Test chart saved to test_chart.png")
    
    print("All tests completed successfully!")
    
except Exception as e:
    print(f"Error occurred: {e}")
    import traceback
    traceback.print_exc()