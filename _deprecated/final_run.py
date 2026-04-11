from final_analyzer import analisar_mercado_tempo_real

if __name__ == "__main__":
    print("Starting Market Analysis System...")
    
    try:
        print("Calling analysis function...")
        analisar_mercado_tempo_real(loop=False)
        print("Analysis completed successfully.")
    except Exception as e:
        print(f"ERROR: An exception occurred: {e}")
        import traceback
        traceback.print_exc()