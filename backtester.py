# backtester.py — Motor de backtesting consolidado
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from strategy import CombinedStrategy

logger = logging.getLogger(__name__)


class Backtester:
    """
    Motor de backtesting unificado.

    Consolida as funcionalidades de backtester.py, final_backtester.py,
    integrated_backtester.py, advanced_strategy.py e enhanced_strategy.py.
    Suporta long/short, stop loss, take profit e trailing stop.
    """

    def __init__(
        self,
        strategy: "CombinedStrategy",
        initial_capital: float = 100_000.0,
        commission_per_trade: float | None = None,
        slippage_pct: float | None = None,
    ) -> None:
        """
        Args:
            strategy: Estratégia a ser testada (qualquer objeto com a interface
                      .data, .params, .name, .prepare(), .generate_signals()).
            initial_capital: Capital inicial em R$.
            commission_per_trade: Custo fixo por execução (entrada OU saída).
                                  Se None, usa ``config.COMMISSION_PER_TRADE``.
            slippage_pct: Slippage fracionário aplicado ao preço de execução
                          (ex: 0.0005 = 5 bps). Se None, usa ``config.SLIPPAGE_PCT``.
        """
        import config as _cfg  # import local evita ciclo caso config importe este módulo

        self.strategy = strategy
        self.initial_capital = initial_capital
        self.commission_per_trade = (
            commission_per_trade if commission_per_trade is not None
            else getattr(_cfg, "COMMISSION_PER_TRADE", 0.0)
        )
        self.slippage_pct = (
            slippage_pct if slippage_pct is not None
            else getattr(_cfg, "SLIPPAGE_PCT", 0.0)
        )
        self.trades: list[dict] = []
        self.equity: list[float] = []
        self.equity_dates: list = []
        self.metrics: dict = {}

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------

    def run(self) -> dict:
        """Executa o backtesting completo.

        Returns:
            Dicionário com métricas de performance.
        """
        data = self.strategy.data
        if data is None or data.empty:
            logger.error("Sem dados para backtesting")
            return {}

        # Preparar dados e gerar sinais
        self.strategy.prepare()
        signals = self.strategy.generate_signals()

        params = self.strategy.params
        capital = self.initial_capital
        position = None
        self.trades = []
        self.equity = [capital]
        self.equity_dates = [data.index[0]]

        logger.info("Iniciando backtest: %d períodos, %d sinais",
                     len(data), len(signals))

        # Criar lookup de sinais por data
        signal_lookup = {}
        for s in signals:
            dt = s['data']
            if dt not in signal_lookup:
                signal_lookup[dt] = []
            signal_lookup[dt].append(s)

        # Processar cada período
        for i in range(1, len(data)):
            current_date = data.index[i]
            close    = float(data['Close'].iloc[i])
            high_val = float(data['High'].iloc[i])
            low_val  = float(data['Low'].iloc[i])

            atr_val = data['ATR'].iloc[i] if 'ATR' in data.columns else close * 0.02
            if pd.isna(atr_val):
                atr_val = close * 0.02

            # ── Gerenciar posição aberta ──────────────────────────────────────
            if position is not None:

                if position['type'] == 'long':
                    # Trailing stop update
                    if params.get('use_trailing_stop', False):
                        trail_threshold = (
                            position['entry_price']
                            + atr_val * params.get('trailing_start_atr', 1.0)
                        )
                        if high_val >= trail_threshold:
                            new_stop = max(
                                position['stop_loss'],
                                high_val - atr_val * params.get('trailing_step_atr', 0.5),
                            )
                            if new_stop > position['stop_loss']:
                                position['stop_loss'] = new_stop

                    if low_val <= position['stop_loss']:
                        self._close_position(position, position['stop_loss'],
                                             current_date, 'Stop Loss', i)
                        capital += position['amount'] + position['_pnl']
                        position = None
                    elif high_val >= position['take_profit']:
                        self._close_position(position, position['take_profit'],
                                             current_date, 'Take Profit', i)
                        capital += position['amount'] + position['_pnl']
                        position = None

                elif position['type'] == 'short':
                    # Trailing stop update
                    if params.get('use_trailing_stop', False):
                        trail_threshold = (
                            position['entry_price']
                            - atr_val * params.get('trailing_start_atr', 1.0)
                        )
                        if low_val <= trail_threshold:
                            new_stop = min(
                                position['stop_loss'],
                                low_val + atr_val * params.get('trailing_step_atr', 0.5),
                            )
                            if new_stop < position['stop_loss']:
                                position['stop_loss'] = new_stop

                    if high_val >= position['stop_loss']:
                        self._close_position(position, position['stop_loss'],
                                             current_date, 'Stop Loss', i)
                        capital += position['amount'] + position['_pnl']
                        position = None
                    elif low_val <= position['take_profit']:
                        self._close_position(position, position['take_profit'],
                                             current_date, 'Take Profit', i)
                        capital += position['amount'] + position['_pnl']
                        position = None

            # ── Abrir nova posição ────────────────────────────────────────────
            if position is None and current_date in signal_lookup:
                for sig in signal_lookup[current_date]:
                    is_long     = sig['tipo'] == 'Compra'
                    entry_price = (
                        close * (1.0 + self.slippage_pct)
                        if is_long
                        else close * (1.0 - self.slippage_pct)
                    )

                    pos_amount = self._size_position(
                        entry_price=entry_price,
                        stop_loss=sig['stop_loss'],
                        capital=capital,
                        max_position_pct=params.get('max_position_pct', 0.5),
                        max_risk_pct=params.get('max_risk_pct', 0.02),
                    )

                    if pos_amount < 1000.0:
                        continue

                    position = {
                        'type':         'long' if is_long else 'short',
                        'entry_date':   current_date,
                        'entry_bar':    i,
                        'entry_price':  entry_price,
                        'stop_loss':    sig['stop_loss'],
                        'take_profit':  sig['preco_alvo'],
                        'amount':       pos_amount,
                        'pattern':      sig['estrategia'],
                    }
                    # Deduzir capital alocado + comissão de entrada
                    capital -= pos_amount + self.commission_per_trade
                    break  # um sinal por período

            # Equity tracking
            current_equity = capital
            if position is not None:
                # Mark-to-market
                if position['type'] == 'long':
                    mtm = (close / position['entry_price'] - 1) * position['amount']
                else:
                    mtm = (position['entry_price'] / close - 1) * position['amount']
                current_equity += position['amount'] + mtm

            self.equity.append(current_equity)
            self.equity_dates.append(current_date)

        # ── Fechar posição aberta no final ──────────────────────────────────
        if position is not None:
            last_i     = len(data) - 1
            last_close = float(data['Close'].iloc[last_i])
            self._close_position(position, last_close, data.index[last_i],
                                 'Fim do Backtest', last_i)
            capital += position['amount'] + position['_pnl']

        # ── Calcular métricas ──
        self.metrics = self._compute_metrics(capital, data)
        return self.metrics

    # ──────────────────────────────────────────────────────────────────
    # API pública complementar
    # ──────────────────────────────────────────────────────────────────

    def trade_report(self) -> pd.DataFrame:
        """Retorna todas as operações como DataFrame.

        Colunas: entry_date, exit_date, duration_bars, type, pattern,
                 entry_price, exit_price, amount, gross_pnl, commission,
                 pnl, pct_change, reason.

        Returns:
            DataFrame indexado por inteiro; vazio se nenhuma operação.
        """
        if not self.trades:
            return pd.DataFrame()

        cols = [
            'entry_date', 'exit_date', 'duration_bars',
            'type', 'pattern',
            'entry_price', 'exit_price', 'amount',
            'gross_pnl', 'commission', 'pnl', 'pct_change',
            'reason',
        ]
        rows = []
        for t in self.trades:
            rows.append({c: t.get(c) for c in cols})
        return pd.DataFrame(rows)

    # ──────────────────────────────────────────────────────────────────
    # Internos
    # ──────────────────────────────────────────────────────────────────

    def _close_position(
        self,
        position: dict,
        exit_price: float,
        exit_date,
        reason: str,
        exit_bar: int = 0,
    ) -> None:
        """Fecha uma posição e registra o trade.

        Aplica slippage adverso no preço de saída e desconta a comissão de
        saída do P&L. A comissão de entrada já foi descontada do ``capital``
        no momento da abertura.

        Side-effect: define ``position['_pnl']`` para que o chamador possa
        atualizar o capital sem precisar re-calcular.
        """
        # Slippage adverso na saída
        if position['type'] == 'long':
            effective_exit = exit_price * (1.0 - self.slippage_pct)
            pct = effective_exit / position['entry_price'] - 1.0
        else:
            effective_exit = exit_price * (1.0 + self.slippage_pct)
            pct = position['entry_price'] / effective_exit - 1.0

        gross_pnl = position['amount'] * pct
        pnl       = gross_pnl - self.commission_per_trade  # comissão de saída
        position['_pnl'] = pnl

        duration = max(0, exit_bar - position.get('entry_bar', exit_bar))

        self.trades.append({
            'entry_date':    position['entry_date'],
            'exit_date':     exit_date,
            'duration_bars': duration,
            'type':          position['type'],
            'entry_price':   position['entry_price'],
            'exit_price':    effective_exit,
            'amount':        position['amount'],
            'pnl':           pnl,
            'gross_pnl':     gross_pnl,
            'commission':    2.0 * self.commission_per_trade,  # entrada + saída
            'pct_change':    pct,
            'reason':        reason,
            'pattern':       position['pattern'],
        })

    @staticmethod
    def _size_position(
        entry_price: float,
        stop_loss: float,
        capital: float,
        max_position_pct: float,
        max_risk_pct: float,
        min_amount: float = 1_000.0,
    ) -> float:
        """Calcula o tamanho da posição baseado em risco fixo por operação.

        Fórmula:
            risk_amount   = capital × max_risk_pct
            risk_per_unit = |entry - stop| / entry   (fracionário)
            size_by_risk  = risk_amount / max(risk_per_unit, 0.001)
            size          = min(size_by_risk, capital × max_position_pct)

        Args:
            entry_price:     Preço de entrada (já com slippage aplicado).
            stop_loss:       Preço do stop loss.
            capital:         Capital disponível no momento.
            max_position_pct: Fração máxima do capital por posição (ex: 0.5).
            max_risk_pct:    Fração máxima do capital a arriscar (ex: 0.02).
            min_amount:      Valor mínimo abaixo do qual a posição é rejeitada.

        Returns:
            Valor em R$ a alocar na posição, ou 0.0 se < min_amount.
        """
        risk_per_unit = abs(entry_price - stop_loss) / entry_price
        risk_per_unit = max(risk_per_unit, 0.001)          # evita divisão por zero

        size_by_risk  = capital * max_risk_pct / risk_per_unit
        size_by_pct   = capital * max_position_pct
        size          = min(size_by_risk, size_by_pct)

        return size if size >= min_amount else 0.0

    @staticmethod
    def _annualization_factor(data: pd.DataFrame) -> float:
        """Calcula o fator de anualização correto para o Sharpe ratio.

        Infere a periodicidade a partir do delta mediano entre timestamps e
        retorna `sqrt(períodos por ano)`. Assume pregão da B3 de 8 horas.

        Exemplos: diário → √252, 1h → √(252*8), 5m → √(252*8*12).
        """
        if data is None or len(data) < 2:
            return float(np.sqrt(252))

        deltas = pd.Series(data.index).diff().dropna()
        if deltas.empty:
            return float(np.sqrt(252))

        median_sec = deltas.median().total_seconds()
        if median_sec <= 0:
            return float(np.sqrt(252))

        # Mapeamento discreto — mais robusto que aritmética de calendário
        # (calendário mistura fins de semana; queremos apenas horas de pregão).
        if median_sec <= 90:              # 1m
            periods_per_year = 252 * 8 * 60
        elif median_sec <= 360:           # 5m
            periods_per_year = 252 * 8 * 12
        elif median_sec <= 1080:          # 15m
            periods_per_year = 252 * 8 * 4
        elif median_sec <= 2100:          # 30m
            periods_per_year = 252 * 8 * 2
        elif median_sec <= 5400:          # 1h
            periods_per_year = 252 * 8
        elif median_sec <= 21600:         # 4h
            periods_per_year = 252 * 2
        elif median_sec <= 129600:        # 1d (até 1.5 dia tolerância)
            periods_per_year = 252
        elif median_sec <= 777600:        # 1 semana
            periods_per_year = 52
        else:                              # mensal ou maior
            periods_per_year = 12

        return float(np.sqrt(periods_per_year))

    def _compute_metrics(self, final_capital: float,
                         data: pd.DataFrame) -> dict:
        """Calcula todas as métricas de performance."""
        n_trades = len(self.trades)

        if n_trades == 0:
            return {
                'initial_capital': self.initial_capital,
                'final_capital': final_capital,
                'return_pct': 0,
                'trade_count': 0,
                'win_rate': 0,
            }

        wins = [t for t in self.trades if t['pnl'] > 0]
        losses = [t for t in self.trades if t['pnl'] <= 0]
        win_rate = len(wins) / n_trades

        avg_win = sum(t['pnl'] for t in wins) / max(len(wins), 1)
        avg_loss = sum(t['pnl'] for t in losses) / max(len(losses), 1)

        total_loss = sum(t['pnl'] for t in losses)
        total_win = sum(t['pnl'] for t in wins)
        profit_factor = abs(total_win / total_loss) if total_loss != 0 else float('inf')

        # Drawdown
        eq = pd.Series(self.equity)
        peak = eq.cummax()
        drawdown = ((eq / peak) - 1) * 100
        max_drawdown = abs(drawdown.min())

        # Returns
        days = (data.index[-1] - data.index[0]).days
        years = max(days / 365.0, 0.1)
        annualized = ((final_capital / self.initial_capital) ** (1 / years)) - 1

        # Sharpe anualizado corretamente em função da granularidade dos dados
        eq_series = pd.Series(self.equity, index=self.equity_dates)
        period_returns = eq_series.pct_change().dropna()
        ann_factor = self._annualization_factor(data)
        sharpe = (ann_factor * period_returns.mean() /
                  max(period_returns.std(), 1e-9))

        # Pattern stats
        pattern_stats = {}
        for t in self.trades:
            p = t.get('pattern', 'unknown')
            if p not in pattern_stats:
                pattern_stats[p] = {'count': 0, 'wins': 0, 'profit': 0}
            pattern_stats[p]['count'] += 1
            if t['pnl'] > 0:
                pattern_stats[p]['wins'] += 1
            pattern_stats[p]['profit'] += t['pnl']

        total_commission = sum(t.get('commission', 0.0) for t in self.trades)

        # ── Calmar ──────────────────────────────────────────────────────────
        # Calmar = retorno anualizado / max drawdown (percentual absoluto)
        calmar = annualized / (max_drawdown / 100.0) if max_drawdown > 0 else float('inf')

        # ── Sortino ─────────────────────────────────────────────────────────
        # Usa apenas retornos negativos para o desvio padrão
        neg_returns    = period_returns[period_returns < 0]
        downside_std   = float(neg_returns.std()) if len(neg_returns) > 1 else 1e-9
        sortino        = (ann_factor * period_returns.mean() /
                          max(downside_std, 1e-9))

        # ── Expectativa ─────────────────────────────────────────────────────
        # E[trade] = win_rate × avg_win + (1 - win_rate) × avg_loss
        expectancy = win_rate * avg_win + (1.0 - win_rate) * avg_loss

        # ── Sequências ──────────────────────────────────────────────────────
        max_consec_wins = max_consec_losses = 0
        cur_w = cur_l = 0
        for t in self.trades:
            if t['pnl'] > 0:
                cur_w += 1; cur_l = 0
            else:
                cur_l += 1; cur_w = 0
            max_consec_wins   = max(max_consec_wins,   cur_w)
            max_consec_losses = max(max_consec_losses, cur_l)

        # ── Duração média ────────────────────────────────────────────────────
        durations     = [t.get('duration_bars', 0) for t in self.trades]
        avg_duration  = float(np.mean(durations)) if durations else 0.0

        return {
            # Capital
            'initial_capital':    self.initial_capital,
            'final_capital':      final_capital,
            'return_pct':         final_capital / self.initial_capital - 1.0,
            'annualized_return':  annualized,
            # Operações
            'trade_count':        n_trades,
            'win_rate':           win_rate,
            'avg_win':            avg_win,
            'avg_loss':           avg_loss,
            'expectancy':         expectancy,
            'avg_duration_bars':  avg_duration,
            # Risco
            'profit_factor':      profit_factor,
            'max_drawdown':       max_drawdown,
            'sharpe_ratio':       sharpe,
            'sortino_ratio':      sortino,
            'calmar_ratio':       calmar,
            # Sequências
            'max_consec_wins':    max_consec_wins,
            'max_consec_losses':  max_consec_losses,
            # Custos
            'total_commission':   total_commission,
            'slippage_pct':       self.slippage_pct,
            # Padrões
            'pattern_stats':      pattern_stats,
        }

    # ------------------------------------------------------------------
    # Visualização
    # ------------------------------------------------------------------

    def plot_results(self, output_dir: str = 'resultados_backtest') -> list[str]:
        """Gera gráficos de resultado do backtest.

        Returns:
            Lista de caminhos dos arquivos gerados.
        """
        os.makedirs(output_dir, exist_ok=True)
        name = self.strategy.name
        files = []

        # 1. Curva de Equity + Drawdown
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10),
                                        gridspec_kw={'height_ratios': [3, 1]})

        ax1.plot(self.equity_dates, self.equity, linewidth=2, color='#2196F3')
        ax1.set_title(f'Curva de Capital — {name}', fontsize=14)
        ax1.set_ylabel('Capital (R$)', fontsize=12)
        ax1.grid(True, alpha=0.3)

        eq = pd.Series(self.equity, index=self.equity_dates)
        dd = ((eq / eq.cummax()) - 1) * 100
        ax2.fill_between(self.equity_dates, dd.values, 0, color='red', alpha=0.3)
        ax2.set_title('Drawdown', fontsize=12)
        ax2.set_ylabel('Drawdown (%)', fontsize=11)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        path = os.path.join(output_dir, f'{name}_equity_drawdown.png')
        plt.savefig(path, dpi=100)
        plt.close()
        files.append(path)

        # 2. Preço + Operações
        if self.strategy.data is not None and self.trades:
            fig, ax = plt.subplots(figsize=(15, 8))
            ax.plot(self.strategy.data.index, self.strategy.data['Close'],
                    color='black', linewidth=1, label='Preço')

            for t in self.trades:
                color_entry = 'green' if t['type'] == 'long' else 'red'
                marker_entry = '^' if t['type'] == 'long' else 'v'
                ax.scatter(t['entry_date'], t['entry_price'],
                           marker=marker_entry, color=color_entry, s=80, zorder=5)
                color_exit = 'green' if t['pnl'] > 0 else 'red'
                ax.scatter(t['exit_date'], t['exit_price'],
                           marker='x', color=color_exit, s=80, zorder=5)

            ax.set_title(f'Preço e Operações — {name}', fontsize=14)
            ax.set_ylabel('Preço', fontsize=12)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            path = os.path.join(output_dir, f'{name}_preco_operacoes.png')
            plt.savefig(path, dpi=100)
            plt.close()
            files.append(path)

        # 3. Performance por padrão
        ps = self.metrics.get('pattern_stats', {})
        if ps:
            fig, ax = plt.subplots(figsize=(12, 6))
            patterns = list(ps.keys())
            profits = [ps[p]['profit'] for p in patterns]
            counts = [ps[p]['count'] for p in patterns]

            sorted_idx = np.argsort(profits)
            patterns = [patterns[i] for i in sorted_idx]
            profits = [profits[i] for i in sorted_idx]
            counts = [counts[i] for i in sorted_idx]

            bars = ax.bar(patterns, profits,
                          color=['#4CAF50' if p > 0 else '#F44336' for p in profits])
            for i, bar in enumerate(bars):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f'n={counts[i]}', ha='center', va='bottom', fontsize=9)

            ax.set_title(f'Performance por Padrão — {name}', fontsize=14)
            ax.set_ylabel('Lucro (R$)', fontsize=12)
            plt.xticks(rotation=45, ha='right')
            ax.grid(True, alpha=0.3, axis='y')
            plt.tight_layout()
            path = os.path.join(output_dir, f'{name}_patterns.png')
            plt.savefig(path, dpi=100)
            plt.close()
            files.append(path)

        logger.info("Gráficos salvos em %s: %s", output_dir, files)
        return files

    def print_results(self) -> None:
        """Imprime resumo dos resultados no console."""
        m = self.metrics
        if not m:
            print("Nenhum resultado disponível.")
            return

        print("\n" + "=" * 55)
        print(f"  RESULTADOS DO BACKTEST — {self.strategy.name}")
        print("=" * 55)
        print(f"  Capital Inicial:    R$ {m['initial_capital']:>12,.2f}")
        print(f"  Capital Final:      R$ {m['final_capital']:>12,.2f}")
        print(f"  Retorno Total:         {m['return_pct']:>11.2%}")
        print(f"  Retorno Anualizado:    {m.get('annualized_return', 0):>11.2%}")
        print(f"  Total de Operações:    {m['trade_count']:>11d}")
        print(f"  Win Rate:              {m['win_rate']:>11.2%}")
        print(f"  Profit Factor:         {m.get('profit_factor', 0):>11.2f}")
        print(f"  Max Drawdown:          {m.get('max_drawdown', 0):>11.2f}%")
        print(f"  Sharpe Ratio:          {m.get('sharpe_ratio', 0):>11.2f}")
        print(f"  Sortino Ratio:         {m.get('sortino_ratio', 0):>11.2f}")
        print(f"  Calmar Ratio:          {m.get('calmar_ratio', 0):>11.2f}")
        print(f"  Expectativa (R$/op):   {m.get('expectancy', 0):>11,.2f}")
        print(f"  Seq. Vitórias:         {m.get('max_consec_wins', 0):>11d}")
        print(f"  Seq. Perdas:           {m.get('max_consec_losses', 0):>11d}")
        print(f"  Duração Média (bars):  {m.get('avg_duration_bars', 0):>11.1f}")
        print(f"  Custos Totais (R$):    {m.get('total_commission', 0):>11,.2f}")
        print(f"  Slippage (por lado):   {m.get('slippage_pct', 0) * 100:>10.3f}%")
        print("=" * 55)

        if self.trades:
            print("\n  Melhores operações:")
            sorted_trades = sorted(self.trades, key=lambda t: t['pnl'], reverse=True)
            for t in sorted_trades[:3]:
                print(f"    {t['type']:>5s} | {t['pct_change']:>+7.2%} | "
                      f"{t['reason']} | {t['pattern']}")

            print("\n  Piores operações:")
            for t in sorted_trades[-3:]:
                print(f"    {t['type']:>5s} | {t['pct_change']:>+7.2%} | "
                      f"{t['reason']} | {t['pattern']}")