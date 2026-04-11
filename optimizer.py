# optimizer.py — Otimizador de parâmetros consolidado
import itertools
import logging
import os

from strategy import CombinedStrategy
from backtester import Backtester

logger = logging.getLogger(__name__)


class StrategyOptimizer:
    """
    Otimizador de parâmetros via Grid Search com validação out-of-sample.

    Consolida enhanced_strategy.py, strategy_optimizer.py, final_optimizer.py,
    robust_optimizer.py, main_optimizer.py, minimal_optimizer.py e simple_optimizer.py.
    """

    DEFAULT_GRID = {
        'ema_short': [8, 9, 13],
        'ema_medium': [21, 34],
        'use_trend_filter': [True, False],
        'min_pattern_strength': [6, 7, 8],
        'atr_stop_multiplier': [1.0, 1.5, 2.0],
    }

    def __init__(self, ticker: str, name: str = ''):
        self.ticker = ticker
        self.name = name or ticker
        self._cached_data = None

    def optimize(self, start_train: str, end_train: str,
                 interval: str = '1d',
                 param_grid: dict | None = None,
                 initial_capital: float = 100_000.0) -> list[dict]:
        """Executa otimização por grid search no período de treino.

        Args:
            start_train: Início do período de treino.
            end_train: Fim do período de treino.
            interval: Intervalo dos dados.
            param_grid: Grid de parâmetros (dict de listas). Usa DEFAULT_GRID se None.
            initial_capital: Capital inicial para backtesting.

        Returns:
            Lista de resultados ordenados por retorno (melhor primeiro).
        """
        grid = param_grid or self.DEFAULT_GRID

        # Gerar combinações
        keys = list(grid.keys())
        combos = list(itertools.product(*[grid[k] for k in keys]))
        logger.info("Otimizando %s: %d combinações", self.name, len(combos))
        print(f"\nOtimizando {self.name}: {len(combos)} combinações de parâmetros")

        # Baixar dados uma vez
        base_strategy = CombinedStrategy(self.ticker, self.name)
        if not base_strategy.load_historical(start_train, end_train, interval):
            logger.error("Falha ao baixar dados para %s", self.ticker)
            return []
        self._cached_data = base_strategy.data.copy()

        results = []
        for i, combo in enumerate(combos):
            params = {keys[j]: combo[j] for j in range(len(keys))}

            # Criar estratégia com estes parâmetros e dados em cache
            strategy = CombinedStrategy(self.ticker, self.name, params)
            strategy.set_data(self._cached_data)

            # Backtest
            bt = Backtester(strategy, initial_capital)
            metrics = bt.run()

            if metrics and metrics.get('trade_count', 0) > 0:
                metrics['params'] = params
                results.append(metrics)

            if (i + 1) % 10 == 0 or i == len(combos) - 1:
                print(f"  Progresso: {i + 1}/{len(combos)}")

        # Ordenar por retorno
        results.sort(key=lambda x: x['return_pct'], reverse=True)

        # Exibir top 5
        self._print_top_results(results)

        return results

    def validate(self, best_params: dict, start_test: str, end_test: str,
                 interval: str = '1d',
                 initial_capital: float = 100_000.0,
                 output_dir: str = 'validation') -> dict | None:
        """Valida os melhores parâmetros no período de teste (out-of-sample).

        Args:
            best_params: Parâmetros otimizados.
            start_test: Início do período de teste.
            end_test: Fim do período de teste.
            interval: Intervalo dos dados.
            initial_capital: Capital inicial.
            output_dir: Pasta para salvar gráficos.

        Returns:
            Métricas de validação ou None em caso de falha.
        """
        print(f"\nValidando {self.name} ({start_test} → {end_test})...")

        strategy = CombinedStrategy(self.ticker, self.name, best_params)
        if not strategy.load_historical(start_test, end_test, interval):
            print("Falha ao baixar dados de validação")
            return None

        bt = Backtester(strategy, initial_capital)
        metrics = bt.run()

        if metrics:
            bt.print_results()
            bt.plot_results(output_dir)

            # Salvar parâmetros
            self._save_params(best_params)

        return metrics

    def run_full_pipeline(self, train_start: str, train_end: str,
                          test_start: str, test_end: str,
                          interval: str = '1d',
                          param_grid: dict | None = None) -> dict:
        """Executa otimização + validação completa.

        Returns:
            Dict com resultados de treino e validação.
        """
        # Otimizar
        results = self.optimize(train_start, train_end, interval, param_grid)

        if not results:
            print(f"Sem resultados válidos para {self.name}")
            return {'train': [], 'validation': None}

        best_params = results[0]['params']

        # Validar
        val_metrics = self.validate(best_params, test_start, test_end, interval)

        return {
            'train': results[:5],
            'validation': val_metrics,
            'best_params': best_params,
        }

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _print_top_results(self, results: list[dict], top_n: int = 5) -> None:
        """Exibe os melhores resultados."""
        print(f"\n{'=' * 50}")
        print(f"TOP {min(top_n, len(results))} RESULTADOS — {self.name}")
        print('=' * 50)

        for i, r in enumerate(results[:top_n]):
            print(f"\n  {i + 1}. Retorno: {r['return_pct']:.2%} | "
                  f"Win Rate: {r['win_rate']:.2%} | "
                  f"Trades: {r['trade_count']}")
            print(f"     Sharpe: {r.get('sharpe_ratio', 0):.2f} | "
                  f"Max DD: {r.get('max_drawdown', 0):.2f}%")
            print(f"     Params: {r['params']}")

    def _save_params(self, params: dict) -> None:
        """Salva os melhores parâmetros em arquivo."""
        filename = f"best_params_{self.name}.txt"
        with open(filename, 'w') as f:
            for k, v in params.items():
                f.write(f"{k}: {v}\n")
        print(f"Parâmetros salvos em {filename}")
