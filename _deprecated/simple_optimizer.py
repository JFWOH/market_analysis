# simple_optimizer.py
from market_strategy import otimizar_estrategia

# Ativos para otimizar
ativos = [
    {"ticker": "^BVSP", "nome": "Ibovespa", "inicio": "2022-01-01", "fim": "2023-12-31", "intervalo": "1d"},
    {"ticker": "USDBRL=X", "nome": "USD/BRL", "inicio": "2022-01-01", "fim": "2023-12-31", "intervalo": "1d"}
]

# Executar otimização
for ativo in ativos:
    print(f"\n{'='*50}")
    print(f"OTIMIZANDO {ativo['nome']}")
    print(f"{'='*50}")
    
    melhores_params = otimizar_estrategia(
        ticker=ativo['ticker'],
        nome_ativo=ativo['nome'],
        periodo_inicio=ativo['inicio'],
        periodo_fim=ativo['fim'],
        intervalo=ativo['intervalo']
    )
    
    if melhores_params:
        print(f"\nParâmetros ótimos para {ativo['nome']}:")
        for param, valor in melhores_params.items():
            print(f"  {param}: {valor}")
    else:
        print(f"Não foi possível otimizar parâmetros para {ativo['nome']}")
    
    print(f"\n{'-'*50}")

print("\nOtimização concluída!")