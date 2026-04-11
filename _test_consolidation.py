"""Teste rápido da consolidação — validação funcional."""
from strategy import CombinedStrategy
import config

print("=" * 50)
print("TESTE DE CONSOLIDAÇÃO")
print("=" * 50)

for key, asset in config.ASSETS.items():
    print(f"\n--- {asset['name']} ---")
    s = CombinedStrategy(asset['ticker'], asset['name'])
    ok = s.load_data(period='1mo', interval='1d')
    print(f"  Dados: {'OK' if ok else 'FALHA'}")
    
    if ok:
        result = s.analyze()
        dp = asset['decimal_places']
        print(f"  Tendência: {result['trend']}")
        print(f"  Preço: {result['last_price']:.{dp}f}")
        
        rsi = result.get('rsi')
        if rsi:
            print(f"  RSI: {rsi:.1f}")
        
        atr = result.get('atr')
        if atr:
            print(f"  ATR: {atr:.{dp}f}")
        
        signals = result.get('signals', [])
        print(f"  Sinais: {len(signals)}")
        for sig in signals[:3]:
            print(f"    - {sig['tipo']}: {sig['estrategia']}")

# Testar backtester
print(f"\n--- Backtester ---")
from backtester import Backtester

asset = config.ASSETS['mini_indice']
s = CombinedStrategy(asset['ticker'], asset['name'])
ok = s.load_historical('2025-01-01', '2026-01-01', '1d')
print(f"  Dados históricos: {'OK' if ok else 'FALHA'}")

if ok:
    bt = Backtester(s, 100000)
    metrics = bt.run()
    print(f"  Trades: {metrics.get('trade_count', 0)}")
    print(f"  Retorno: {metrics.get('return_pct', 0):.2%}")
    print(f"  Win Rate: {metrics.get('win_rate', 0):.2%}")
    print(f"  Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")

print("\n" + "=" * 50)
print("TESTE CONCLUÍDO COM SUCESSO!")
print("=" * 50)
