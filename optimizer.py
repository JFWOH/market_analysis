# optimizer.py — Otimizador de parâmetros consolidado
from __future__ import annotations

import itertools
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import pandas as pd

from strategy import CombinedStrategy
from backtester import Backtester

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Worker isolado (thread-safe — cada thread cria suas próprias instâncias)
# ──────────────────────────────────────────────────────────────────────────────

def _eval_combo(
    ticker: str,
    name: str,
    params: dict,
    data: pd.DataFrame,
    initial_capital: float,
) -> dict | None:
    """Avalia uma combinação de parâmetros.

    Função de nível de módulo para compatibilidade com ProcessPoolExecutor
    (picklable). Cada chamada cria instâncias independentes de Strategy e
    Backtester, garantindo thread/process safety.
    """
    strategy = CombinedStrategy(ticker, name, params)
    strategy.set_data(data)      # set_data faz .copy() internamente
    bt = Backtester(strategy, initial_capital)
    metrics = bt.run()
    if metrics:
        metrics["params"] = params
    return metrics


# ──────────────────────────────────────────────────────────────────────────────
# Otimizador
# ──────────────────────────────────────────────────────────────────────────────

class StrategyOptimizer:
    """
    Otimizador de parâmetros via Grid Search com validação walk-forward.

    Melhorias em relação à versão anterior:
      • Métrica de ranking configurável (default: sharpe_ratio)
      • Filtros de qualidade: min_trades, max_drawdown_pct
      • Early stopping por paciência (sem melhoria após N combos)
      • Paralelismo via ThreadPoolExecutor (n_jobs > 1)
      • Validação walk-forward com N folds

    Consolidado de: enhanced_strategy.py, strategy_optimizer.py,
    final_optimizer.py, robust_optimizer.py, main_optimizer.py,
    minimal_optimizer.py, simple_optimizer.py.
    """

    DEFAULT_GRID: dict = {
        "ema_short":            [8, 9, 13],
        "ema_medium":           [21, 34],
        "use_trend_filter":     [True, False],
        "min_pattern_strength": [6, 7, 8],
        "atr_stop_multiplier":  [1.0, 1.5, 2.0],
    }

    # Métricas válidas para ordenação (higher = better)
    _VALID_METRICS = {
        "return_pct", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
        "profit_factor", "win_rate", "expectancy",
    }

    def __init__(self, ticker: str, name: str = "") -> None:
        self.ticker = ticker
        self.name   = name or ticker
        self._cached_data: pd.DataFrame | None = None

    # ──────────────────────────────────────────────────────────────────────────
    # Grid Search principal
    # ──────────────────────────────────────────────────────────────────────────

    def optimize(
        self,
        start_train: str,
        end_train: str,
        interval: str = "1d",
        param_grid: dict | None = None,
        initial_capital: float = 100_000.0,
        metric: str = "sharpe_ratio",
        min_trades: int = 3,
        max_drawdown_pct: float = 50.0,
        n_jobs: int = 1,
        patience: int | None = None,
    ) -> list[dict]:
        """Grid search com filtros de qualidade e paralelismo opcional.

        Args:
            start_train:     Início do período de treino ('YYYY-MM-DD').
            end_train:       Fim do período de treino ('YYYY-MM-DD').
            interval:        Intervalo dos candles ('1d', '1h', etc.).
            param_grid:      Grid de parâmetros (dict de listas). Usa DEFAULT_GRID se None.
            initial_capital: Capital inicial para backtesting.
            metric:          Métrica de ranking. Uma de: return_pct, sharpe_ratio,
                             sortino_ratio, calmar_ratio, profit_factor, win_rate,
                             expectancy. Default: sharpe_ratio.
            min_trades:      Combos com menos que este número de trades são descartados.
            max_drawdown_pct: Combos com drawdown maior que este % são descartados.
            n_jobs:          Threads paralelas. 1 = sequencial. -1 = todos os cores.
            patience:        Número de combos consecutivos sem melhoria antes de parar.
                             None = sem early stopping.

        Returns:
            Lista de resultados válidos ordenados pela métrica (melhor primeiro).
        """
        if metric not in self._VALID_METRICS:
            logger.warning("Métrica '%s' inválida; usando 'sharpe_ratio'", metric)
            metric = "sharpe_ratio"

        grid   = param_grid or self.DEFAULT_GRID
        keys   = list(grid.keys())
        combos = list(itertools.product(*[grid[k] for k in keys]))
        n      = len(combos)

        logger.info("Grid search %s: %d combinações | metric=%s | n_jobs=%d",
                    self.name, n, metric, n_jobs)
        print(f"\nOtimizando {self.name}: {n} combinações | "
              f"metric={metric} | n_jobs={n_jobs}")

        # Carregar dados uma vez
        data = self._load_data(start_train, end_train, interval)
        if data is None:
            return []

        param_dicts = [{keys[j]: combo[j] for j in range(len(keys))} for combo in combos]

        # Execução
        if n_jobs == 1:
            raw = self._run_sequential(param_dicts, data, initial_capital, patience, metric)
        else:
            workers = self._resolve_n_jobs(n_jobs)
            raw     = self._run_parallel(param_dicts, data, initial_capital, workers)

        # Filtrar resultados de qualidade
        results = self._filter_results(raw, min_trades, max_drawdown_pct)

        # Ordenar
        results.sort(key=lambda x: x.get(metric, float("-inf")), reverse=True)

        self._print_top_results(results, metric=metric)
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Validação out-of-sample (simples)
    # ──────────────────────────────────────────────────────────────────────────

    def validate(
        self,
        best_params: dict,
        start_test: str,
        end_test: str,
        interval: str = "1d",
        initial_capital: float = 100_000.0,
        output_dir: str = "validation",
    ) -> dict | None:
        """Valida os melhores parâmetros em período out-of-sample.

        Args:
            best_params: Parâmetros a validar.
            start_test:  Início do período de teste ('YYYY-MM-DD').
            end_test:    Fim do período de teste ('YYYY-MM-DD').
            interval:    Intervalo dos candles.
            initial_capital: Capital inicial.
            output_dir:  Pasta para salvar gráficos.

        Returns:
            Métricas de validação ou None em caso de falha.
        """
        print(f"\nValidando {self.name} ({start_test} -> {end_test})...")

        strategy = CombinedStrategy(self.ticker, self.name, best_params)
        if not strategy.load_historical(start_test, end_test, interval):
            print("Falha ao baixar dados de validação")
            return None

        bt = Backtester(strategy, initial_capital)
        metrics = bt.run()

        if metrics:
            bt.print_results()
            os.makedirs(output_dir, exist_ok=True)
            bt.plot_results(output_dir)
            self._save_params(best_params)

        return metrics

    # ──────────────────────────────────────────────────────────────────────────
    # Walk-forward validation
    # ──────────────────────────────────────────────────────────────────────────

    def walk_forward(
        self,
        start: str,
        end: str,
        n_folds: int = 4,
        train_pct: float = 0.70,
        interval: str = "1d",
        param_grid: dict | None = None,
        initial_capital: float = 100_000.0,
        metric: str = "sharpe_ratio",
        min_trades: int = 3,
        n_jobs: int = 1,
    ) -> dict:
        """Validação walk-forward com N folds não sobrepostos.

        Divide o período total em N folds; em cada fold otimiza no
        subperíodo de treino e valida no subperíodo de teste imediatamente
        seguinte. Retorna métricas consolidadas de todos os folds.

        Estrutura dos folds (n_folds=4, train_pct=0.7):
            |----fold0----|----fold1----|----fold2----|----fold3----|
            |--train--|tst|--train--|tst|--train--|tst|--train--|tst|

        Args:
            start:      Início total ('YYYY-MM-DD').
            end:        Fim total ('YYYY-MM-DD').
            n_folds:    Número de folds. Default: 4.
            train_pct:  Fração de cada fold usado para treino. Default: 0.70.
            interval:   Intervalo dos candles.
            param_grid: Grid de parâmetros.
            initial_capital: Capital inicial.
            metric:     Métrica de ranking para otimização interna.
            min_trades: Mínimo de trades por combo.
            n_jobs:     Threads para o grid search de cada fold.

        Returns:
            Dict com 'folds' (lista de resultados por fold), 'summary'
            (métricas médias) e 'best_params' (parâmetros mais frequentes
            no top-1 de cada fold).
        """
        splits = self._make_splits(start, end, n_folds, train_pct)
        if not splits:
            return {"folds": [], "summary": {}, "best_params": {}}

        print(f"\nWalk-Forward: {self.name} | {n_folds} folds | metric={metric}")
        print(f"  Período total: {start} -> {end}")
        print(f"  Train: {train_pct:.0%} | Test: {1-train_pct:.0%} por fold")

        fold_results: list[dict] = []

        for k, (tr_start, tr_end, ts_start, ts_end) in enumerate(splits):
            print(f"\n  Fold {k+1}/{n_folds}: train={tr_start}->{tr_end} | "
                  f"test={ts_start}->{ts_end}")

            # Otimizar no período de treino
            train_res = self.optimize(
                tr_start, tr_end, interval, param_grid,
                initial_capital, metric, min_trades,
                n_jobs=n_jobs,
            )
            if not train_res:
                print(f"  [!] Fold {k+1}: nenhum resultado válido no treino — pulando")
                continue

            best_params = train_res[0]["params"]

            # Validar no período de teste
            test_metrics = self._eval_single(best_params, ts_start, ts_end,
                                              interval, initial_capital)

            fold_results.append({
                "fold":        k + 1,
                "train_start": tr_start,
                "train_end":   tr_end,
                "test_start":  ts_start,
                "test_end":    ts_end,
                "best_params": best_params,
                "train_metric":train_res[0].get(metric, float("nan")),
                "test_metrics":test_metrics or {},
            })

            if test_metrics:
                r   = test_metrics.get("return_pct", 0)
                sh  = test_metrics.get("sharpe_ratio", 0)
                dd  = test_metrics.get("max_drawdown", 0)
                nt  = test_metrics.get("trade_count", 0)
                print(f"  Fold {k+1} TEST: retorno={r:.2%} | "
                      f"sharpe={sh:.2f} | DD={dd:.1f}% | trades={nt}")

        summary = self._summarize_folds(fold_results, metric)
        best_params = self._most_common_params(fold_results)

        print(f"\n  Walk-Forward Summary:")
        for k, v in summary.items():
            print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")

        return {
            "folds":       fold_results,
            "summary":     summary,
            "best_params": best_params,
        }

    # ────────────────────────────────────────────────────────────────────────��─
    # Pipeline completo
    # ──────────────────────────────────────────────────────────────────────────

    def run_full_pipeline(
        self,
        train_start: str,
        train_end: str,
        test_start: str,
        test_end: str,
        interval: str = "1d",
        param_grid: dict | None = None,
        metric: str = "sharpe_ratio",
        n_jobs: int = 1,
    ) -> dict:
        """Otimização + validação out-of-sample em um único passo.

        Returns:
            Dict com 'train' (top 5), 'validation' (métricas OOS) e 'best_params'.
        """
        results = self.optimize(
            train_start, train_end, interval, param_grid,
            metric=metric, n_jobs=n_jobs,
        )
        if not results:
            print(f"Sem resultados válidos para {self.name}")
            return {"train": [], "validation": None}

        best_params = results[0]["params"]
        val_metrics = self.validate(best_params, test_start, test_end, interval)

        return {
            "train":       results[:5],
            "validation":  val_metrics,
            "best_params": best_params,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Internos
    # ──────────────────────────────────────────────────────────────────────────

    def _load_data(
        self, start: str, end: str, interval: str
    ) -> pd.DataFrame | None:
        """Carrega (e cacheia) dados históricos."""
        base = CombinedStrategy(self.ticker, self.name)
        if not base.load_historical(start, end, interval):
            logger.error("Falha ao baixar dados para %s (%s -> %s)", self.name, start, end)
            return None
        self._cached_data = base.data.copy()
        return self._cached_data

    def _run_sequential(
        self,
        param_dicts: list[dict],
        data: pd.DataFrame,
        initial_capital: float,
        patience: int | None,
        metric: str,
    ) -> list[dict]:
        """Avalia combos sequencialmente com early stopping por paciência."""
        results: list[dict] = []
        best_val   = float("-inf")
        no_improve = 0
        n          = len(param_dicts)

        for i, params in enumerate(param_dicts):
            m = _eval_combo(self.ticker, self.name, params, data, initial_capital)
            if m:
                results.append(m)
                val = m.get(metric, float("-inf"))
                if val > best_val:
                    best_val   = val
                    no_improve = 0
                else:
                    no_improve += 1

                if patience and no_improve >= patience:
                    logger.info("Early stopping após %d combos sem melhoria", patience)
                    print(f"  [early stop] sem melhoria em {patience} combos consecutivos "
                          f"({i+1}/{n} avaliados)")
                    break

            if (i + 1) % max(1, n // 5) == 0 or i == n - 1:
                pct = (i + 1) / n * 100
                print(f"  Progresso: {i+1}/{n} ({pct:.0f}%)")

        return results

    def _run_parallel(
        self,
        param_dicts: list[dict],
        data: pd.DataFrame,
        initial_capital: float,
        n_workers: int,
    ) -> list[dict]:
        """Avalia combos em paralelo com ThreadPoolExecutor."""
        results: list[dict] = []
        n = len(param_dicts)
        done = 0

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(
                    _eval_combo,
                    self.ticker, self.name, p, data, initial_capital
                ): p
                for p in param_dicts
            }
            for fut in as_completed(futures):
                done += 1
                try:
                    m = fut.result()
                    if m:
                        results.append(m)
                except Exception as exc:
                    logger.warning("Combo falhou: %s", exc)

                if done % max(1, n // 5) == 0 or done == n:
                    pct = done / n * 100
                    print(f"  Progresso: {done}/{n} ({pct:.0f}%)")

        return results

    @staticmethod
    def _filter_results(
        results: list[dict],
        min_trades: int,
        max_drawdown_pct: float,
    ) -> list[dict]:
        """Remove combos abaixo dos critérios mínimos de qualidade."""
        valid = []
        pruned = 0
        for r in results:
            if r.get("trade_count", 0) < min_trades:
                pruned += 1
                continue
            if r.get("max_drawdown", 0) > max_drawdown_pct:
                pruned += 1
                continue
            if r.get("return_pct", -999) < -0.90:   # perda catastrófica > 90%
                pruned += 1
                continue
            valid.append(r)
        if pruned:
            logger.info("Filtro qualidade: %d combos removidos, %d válidos", pruned, len(valid))
        return valid

    @staticmethod
    def _resolve_n_jobs(n_jobs: int) -> int:
        """Converte n_jobs=-1 para número de CPUs disponíveis."""
        if n_jobs == -1:
            import os as _os
            return _os.cpu_count() or 4
        return max(1, n_jobs)

    def _eval_single(
        self,
        params: dict,
        start: str,
        end: str,
        interval: str,
        initial_capital: float,
    ) -> dict | None:
        """Avalia parâmetros em um período específico (sem cache)."""
        data = self._load_data(start, end, interval)
        if data is None:
            return None
        return _eval_combo(self.ticker, self.name, params, data, initial_capital)

    @staticmethod
    def _make_splits(
        start: str,
        end: str,
        n_folds: int,
        train_pct: float,
    ) -> list[tuple[str, str, str, str]]:
        """Divide o período em N folds não sobrepostos.

        Returns:
            Lista de (train_start, train_end, test_start, test_end).
        """
        start_dt = pd.Timestamp(start)
        end_dt   = pd.Timestamp(end)
        total_days = (end_dt - start_dt).days

        if total_days < n_folds * 30:
            logger.warning("Período muito curto para %d folds (%d dias)", n_folds, total_days)
            return []

        fold_days = total_days / n_folds
        fmt = "%Y-%m-%d"
        splits = []

        for k in range(n_folds):
            fold_start = start_dt + pd.Timedelta(days=k * fold_days)
            fold_end   = start_dt + pd.Timedelta(days=(k + 1) * fold_days)
            train_end  = fold_start + pd.Timedelta(days=fold_days * train_pct)
            test_start = train_end + pd.Timedelta(days=1)

            splits.append((
                fold_start.strftime(fmt),
                train_end.strftime(fmt),
                test_start.strftime(fmt),
                fold_end.strftime(fmt),
            ))

        return splits

    @staticmethod
    def _summarize_folds(fold_results: list[dict], metric: str) -> dict:
        """Calcula médias e desvios-padrão das métricas de teste entre folds."""
        if not fold_results:
            return {}

        test_metrics_list = [f["test_metrics"] for f in fold_results if f.get("test_metrics")]
        if not test_metrics_list:
            return {}

        keys = ["return_pct", "sharpe_ratio", "max_drawdown", "win_rate",
                "trade_count", "profit_factor", metric]
        keys = list(dict.fromkeys(keys))   # deduplica mantendo ordem

        import numpy as np
        summary: dict = {}
        for k in keys:
            vals = [m.get(k, float("nan")) for m in test_metrics_list]
            vals = [v for v in vals if not (isinstance(v, float) and v != v)]
            if vals:
                summary[f"avg_{k}"]    = float(np.mean(vals))
                summary[f"std_{k}"]    = float(np.std(vals))
                summary[f"median_{k}"] = float(np.median(vals))

        summary["n_folds_completed"] = len(fold_results)
        summary["n_folds_with_test"] = len(test_metrics_list)

        # Consistência: fração de folds com retorno positivo
        rets = [m.get("return_pct", float("nan")) for m in test_metrics_list]
        positive = sum(1 for r in rets if isinstance(r, float) and r > 0)
        summary["positive_fold_pct"] = positive / len(rets) if rets else 0.0

        return summary

    @staticmethod
    def _most_common_params(fold_results: list[dict]) -> dict:
        """Retorna os parâmetros que aparecem mais vezes no top-1 de cada fold."""
        from collections import Counter

        if not fold_results:
            return {}

        param_votes: dict[str, Counter] = {}
        for f in fold_results:
            bp = f.get("best_params", {})
            for k, v in bp.items():
                if k not in param_votes:
                    param_votes[k] = Counter()
                param_votes[k][v] += 1

        return {k: cnt.most_common(1)[0][0] for k, cnt in param_votes.items()}

    def _print_top_results(
        self, results: list[dict], top_n: int = 5, metric: str = "sharpe_ratio"
    ) -> None:
        """Exibe os melhores resultados."""
        print(f"\n{'='*52}")
        print(f"  TOP {min(top_n, len(results))} — {self.name} (ordenado por {metric})")
        print("="*52)

        for i, r in enumerate(results[:top_n]):
            print(f"\n  {i+1}. {metric}={r.get(metric, 0):.3f} | "
                  f"retorno={r['return_pct']:.2%} | "
                  f"win={r['win_rate']:.2%} | "
                  f"trades={r['trade_count']}")
            print(f"     sharpe={r.get('sharpe_ratio',0):.2f} | "
                  f"calmar={r.get('calmar_ratio',0):.2f} | "
                  f"DD={r.get('max_drawdown',0):.1f}%")
            print(f"     params: {r['params']}")

    def _save_params(self, params: dict) -> None:
        """Salva os melhores parâmetros em arquivo."""
        filename = f"best_params_{self.name}.txt"
        with open(filename, "w", encoding="utf-8") as fh:
            for k, v in params.items():
                fh.write(f"{k}: {v}\n")
        print(f"Parâmetros salvos em {filename}")
