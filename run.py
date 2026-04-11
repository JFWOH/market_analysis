# run.py — Script principal unificado do sistema de análise de mercado
"""
Ponto de entrada do sistema. Modos de operação:
  1. Análise única — executa e mostra resultado
  2. Monitoramento — loop contínuo com alertas
  3. Backtesting — executa backtest com parâmetros padrão
  4. Otimização — grid search + validação out-of-sample
"""
import sys
import time
import logging
from datetime import datetime

import config
from strategy import CombinedStrategy
from backtester import Backtester
from optimizer import StrategyOptimizer
from alerts import AlertProcessor


def setup_logging():
    """Configura logging global."""
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format=config.LOG_FORMAT,
    )


def print_header():
    """Exibe cabeçalho do sistema."""
    print("\n" + "=" * 60)
    print("  SISTEMA DE ANÁLISE DE MERCADO BRASILEIRO")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 60)


# ------------------------------------------------------------------
# Modo 1: Análise única
# ------------------------------------------------------------------

def run_single_analysis():
    """Executa uma análise única de todos os ativos configurados."""
    print("\n>>> ANÁLISE ÚNICA\n")

    for key, asset in config.ASSETS.items():
        print(f"\n{'─' * 50}")
        print(f"  {asset['name']} ({asset['ticker']})")
        print(f"{'─' * 50}")

        strategy = CombinedStrategy(asset['ticker'], asset['name'])
        if not strategy.load_data(period=config.DEFAULT_PERIOD,
                                   interval=config.DEFAULT_INTERVAL):
            print(f"  ⚠ Não foi possível obter dados para {asset['name']}")
            continue

        result = strategy.analyze()
        dp = asset['decimal_places']

        print(f"  Tendência:    {result['trend']}")
        print(f"  Último Preço: {result['last_price']:.{dp}f}")
        if result['rsi']:
            print(f"  RSI:          {result['rsi']:.1f}")
        if result['atr']:
            print(f"  ATR:          {result['atr']:.{dp}f}")

        if result['signals']:
            print(f"\n  Sinais encontrados: {len(result['signals'])}")
            for s in result['signals'][-5:]:  # últimos 5
                print(f"    • {s['tipo']} | {s['estrategia']}")
                print(f"      Preço: {s['preco']:.{dp}f} → "
                      f"Alvo: {s['preco_alvo']:.{dp}f} | "
                      f"Stop: {s['stop_loss']:.{dp}f}")
        else:
            print(f"\n  Nenhum sinal de operação no momento.")


# ------------------------------------------------------------------
# Modo 2: Monitoramento contínuo
# ------------------------------------------------------------------

def run_monitoring():
    """Executa monitoramento contínuo com alertas."""
    interval_sec = config.MONITORING_INTERVAL_SECONDS
    processor = AlertProcessor()

    print(f"\n>>> MONITORAMENTO CONTÍNUO (atualização a cada {interval_sec}s)")
    print("    Pressione Ctrl+C para interromper\n")

    try:
        while True:
            print_header()

            for key, asset in config.ASSETS.items():
                strategy = CombinedStrategy(asset['ticker'], asset['name'])
                if not strategy.load_data(period=config.DEFAULT_PERIOD,
                                           interval=config.DEFAULT_INTERVAL):
                    print(f"  ⚠ Falha ao obter dados: {asset['name']}")
                    continue

                result = strategy.analyze()
                dp = asset['decimal_places']

                print(f"\n  {asset['name']}:")
                print(f"    Tendência: {result['trend']} | "
                      f"Preço: {result['last_price']:.{dp}f}")

                if result['signals']:
                    processor.process_signals(
                        result['signals'], asset['name'], result['last_price']
                    )

            next_update = datetime.now().timestamp() + interval_sec
            next_dt = datetime.fromtimestamp(next_update)
            print(f"\n  Próxima atualização: {next_dt.strftime('%H:%M:%S')}")

            time.sleep(interval_sec)

    except KeyboardInterrupt:
        print("\n\nMonitoramento interrompido pelo usuário.")


# ------------------------------------------------------------------
# Modo 3: Backtesting
# ------------------------------------------------------------------

def run_backtest():
    """Executa backtesting com parâmetros padrão."""
    print("\n>>> BACKTESTING\n")

    for key, asset in config.ASSETS.items():
        print(f"\n{'─' * 50}")
        print(f"  Backtest: {asset['name']}")
        print(f"{'─' * 50}")

        strategy = CombinedStrategy(asset['ticker'], asset['name'])
        if not strategy.load_historical('2024-01-01', '2025-12-31', '1d'):
            print(f"  ⚠ Falha ao obter dados: {asset['name']}")
            continue

        bt = Backtester(strategy, config.BACKTEST_INITIAL_CAPITAL)
        metrics = bt.run()

        if metrics:
            bt.print_results()
            files = bt.plot_results()
            if files:
                print(f"\n  Gráficos salvos: {', '.join(files)}")


# ------------------------------------------------------------------
# Modo 4: Otimização
# ------------------------------------------------------------------

def run_optimization():
    """Executa otimização grid search + validação."""
    print("\n>>> OTIMIZAÇÃO DE PARÂMETROS\n")

    for key, asset in config.ASSETS.items():
        print(f"\n{'─' * 50}")
        print(f"  Otimizando: {asset['name']}")
        print(f"{'─' * 50}")

        opt = StrategyOptimizer(asset['ticker'], asset['name'])
        result = opt.run_full_pipeline(
            train_start='2023-01-01',
            train_end='2024-12-31',
            test_start='2025-01-01',
            test_end='2025-12-31',
        )

        if result.get('best_params'):
            print(f"\n  Melhores parâmetros: {result['best_params']}")


# ------------------------------------------------------------------
# Menu principal
# ------------------------------------------------------------------

def main():
    setup_logging()
    print_header()

    print("\n  Modos de operação:")
    print("  1. Análise única")
    print("  2. Monitoramento contínuo")
    print("  3. Backtesting")
    print("  4. Otimização de parâmetros")

    try:
        option = input("\n  Selecione (1-4): ").strip()
    except (EOFError, KeyboardInterrupt):
        option = '1'

    if option == '1':
        run_single_analysis()
    elif option == '2':
        run_monitoring()
    elif option == '3':
        run_backtest()
    elif option == '4':
        run_optimization()
    else:
        print("  Opção inválida. Executando análise única.")
        run_single_analysis()

    print("\n  Análise finalizada.")


if __name__ == '__main__':
    main()