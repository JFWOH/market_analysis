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
        cooldown_bars: int | None = None,
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
            cooldown_bars: Número de barras de silêncio após fechar um trade.
                           Sinais gerados dentro desta janela são ignorados.
                           Se None, usa ``config.SIGNAL_COOLDOWN_BARS``.
                           0 = sem cooldown (comportamento antigo).
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
        self.cooldown_bars = int(
            cooldown_bars if cooldown_bars is not None
            else getattr(_cfg, "SIGNAL_COOLDOWN_BARS", 0)
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
        # Verificação de dados antes de prepare()
        if self.strategy.data is None or self.strategy.data.empty:
            logger.error("Sem dados para backtesting")
            return {}

        # Preparar dados e gerar sinais (prepare() adiciona indicadores,
        # incluindo Realized_Vol. data deve ser capturado APÓS prepare().)
        self.strategy.prepare()
        signals = self.strategy.generate_signals()

        # Referência pós-prepare (contém ATR, Realized_Vol, ADX, Hurst, etc.)
        data = self.strategy.data

        params = self.strategy.params
        capital = self.initial_capital
        position = None
        # Cooldown: índice da última barra de saída.
        # Começa em -inf para permitir o primeiro trade sem restrição.
        last_exit_bar = -10**9
        cooldown_skipped = 0   # contador diagnóstico
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

                # ── Partial Exit + Breakeven (Sprint-1 passo 3) ───────────
                # Ao atingir +R×initial_risk, fecha fração da posição e move
                # stop do restante para breakeven (entry + offset). Ataca
                # Profit Factor convertendo quase-losers em scratches.
                # Flag: se partial disparou nesta barra, não aplicamos stop/TP
                # na mesma barra (ordem high/low dentro da barra é ambígua).
                partial_fired_this_bar = False
                if (params.get('use_partial_exit', False)
                        and not position.get('partial_done', False)):
                    partial_r   = float(params.get('partial_exit_r', 1.0))
                    partial_frc = float(params.get('partial_exit_fraction', 0.5))
                    be_offset   = float(params.get('breakeven_offset_atr', 0.0))
                    init_risk   = position['initial_risk_abs']

                    if position['type'] == 'long':
                        trigger = position['entry_price'] + partial_r * init_risk
                        if high_val >= trigger:
                            self._partial_exit(position, trigger, current_date,
                                               i, partial_frc)
                            capital += position['_partial_released']
                            position['partial_done'] = True
                            partial_fired_this_bar = True
                            # Move stop para breakeven (só aperta, nunca afrouxa)
                            be_stop = position['entry_price'] + be_offset * atr_val
                            if be_stop > position['stop_loss']:
                                position['stop_loss'] = be_stop
                                position['breakeven_moved'] = True
                    else:  # short
                        trigger = position['entry_price'] - partial_r * init_risk
                        if low_val <= trigger:
                            self._partial_exit(position, trigger, current_date,
                                               i, partial_frc)
                            capital += position['_partial_released']
                            position['partial_done'] = True
                            partial_fired_this_bar = True
                            be_stop = position['entry_price'] - be_offset * atr_val
                            if be_stop < position['stop_loss']:
                                position['stop_loss'] = be_stop
                                position['breakeven_moved'] = True

                if partial_fired_this_bar:
                    # Evita stop/TP na mesma barra do partial (ordem intra-bar ambígua)
                    pass
                elif position['type'] == 'long':
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
                        reason = ('Breakeven Stop'
                                  if position.get('breakeven_moved') else 'Stop Loss')
                        self._close_position(position, position['stop_loss'],
                                             current_date, reason, i)
                        capital += position['amount'] + position['_pnl']
                        position = None
                        last_exit_bar = i
                    elif high_val >= position['take_profit']:
                        self._close_position(position, position['take_profit'],
                                             current_date, 'Take Profit', i)
                        capital += position['amount'] + position['_pnl']
                        position = None
                        last_exit_bar = i

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
                        reason = ('Breakeven Stop'
                                  if position.get('breakeven_moved') else 'Stop Loss')
                        self._close_position(position, position['stop_loss'],
                                             current_date, reason, i)
                        capital += position['amount'] + position['_pnl']
                        position = None
                        last_exit_bar = i
                    elif low_val <= position['take_profit']:
                        self._close_position(position, position['take_profit'],
                                             current_date, 'Take Profit', i)
                        capital += position['amount'] + position['_pnl']
                        position = None
                        last_exit_bar = i

            # ── Abrir nova posição ────────────────────────────────────────────
            # Cooldown: ignora sinais se ainda estamos dentro da janela de
            # silêncio pós-saída. Ataca overtrading/custos.
            in_cooldown = (i - last_exit_bar) < self.cooldown_bars

            if position is None and in_cooldown and current_date in signal_lookup:
                cooldown_skipped += len(signal_lookup[current_date])

            if position is None and not in_cooldown and current_date in signal_lookup:
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

                    # ── Vol Targeting (Sprint-2 passo 2) ─────────────────────
                    # Escala o tamanho da posição para manter vol da carteira
                    # próxima de vol_target_annual, independente do regime de
                    # volatilidade do ativo.
                    #   scalar = target_vol / realized_vol
                    #   scalar clampado em [vol_scalar_min, vol_scalar_max]
                    # Resultado: posições menores em períodos voláteis (protege
                    # capital) e maiores em períodos calmos (captura mais edge).
                    if params.get('use_vol_targeting', False):
                        rv_val = (data['Realized_Vol'].iloc[i]
                                  if 'Realized_Vol' in data.columns else None)
                        if rv_val is not None and not pd.isna(rv_val) and rv_val > 1e-6:
                            target_vol = float(params.get('vol_target_annual', 0.15))
                            scalar = target_vol / rv_val
                            scalar = max(
                                float(params.get('vol_scalar_min', 0.25)),
                                min(float(params.get('vol_scalar_max', 2.0)), scalar),
                            )
                            pos_amount *= scalar

                    if pos_amount < 1000.0:
                        continue

                    position = {
                        'type':             'long' if is_long else 'short',
                        'entry_date':       current_date,
                        'entry_bar':        i,
                        'entry_price':      entry_price,
                        'stop_loss':        sig['stop_loss'],
                        'take_profit':      sig['preco_alvo'],
                        'amount':           pos_amount,
                        'original_amount':  pos_amount,
                        'initial_risk_abs': abs(entry_price - sig['stop_loss']),
                        'partial_done':     False,
                        'breakeven_moved':  False,
                        'pattern':          sig['estrategia'],
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
        self.metrics["cooldown_bars"]    = self.cooldown_bars
        self.metrics["signals_skipped_cooldown"] = cooldown_skipped
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

    def _partial_exit(
        self,
        position: dict,
        exit_price: float,
        exit_date,
        exit_bar: int,
        fraction: float,
    ) -> None:
        """Fecha uma fração da posição e deixa o restante aberto.

        Usado pelo *partial exit* do Sprint-1 (passo 3): ao atingir +R×risco
        inicial, fecha ``fraction`` da posição (tipicamente 50%), registra
        como trade separado e reduz ``position['amount']``. O chamador deve
        então mover ``position['stop_loss']`` para breakeven.

        Contabilidade de custos (por trade completo: entrada + parcial + final
        = 3 execuções de comissão):
            - Trade parcial: 'commission' = commission_per_trade (só saída)
            - Trade final:   'commission' = 2 × commission_per_trade (entrada+saída)

        Side-effect: define ``position['_partial_released']`` com o valor
        (amount_fechado + pnl_parcial) a ser devolvido ao capital.
        """
        fraction = max(0.01, min(0.99, fraction))  # clamp defensivo
        closed_amount = position['amount'] * fraction

        # Slippage adverso na saída parcial
        if position['type'] == 'long':
            effective_exit = exit_price * (1.0 - self.slippage_pct)
            pct = effective_exit / position['entry_price'] - 1.0
        else:
            effective_exit = exit_price * (1.0 + self.slippage_pct)
            pct = position['entry_price'] / effective_exit - 1.0

        gross_pnl = closed_amount * pct
        pnl       = gross_pnl - self.commission_per_trade   # comissão saída parcial

        duration = max(0, exit_bar - position.get('entry_bar', exit_bar))

        self.trades.append({
            'entry_date':    position['entry_date'],
            'exit_date':     exit_date,
            'duration_bars': duration,
            'type':          position['type'],
            'entry_price':   position['entry_price'],
            'exit_price':    effective_exit,
            'amount':        closed_amount,
            'pnl':           pnl,
            'gross_pnl':     gross_pnl,
            'commission':    self.commission_per_trade,      # só saída (entrada compartilhada)
            'pct_change':    pct,
            'reason':        'Partial Exit',
            'pattern':       position['pattern'],
        })

        # Reduzir a posição e devolver capital da parte fechada
        position['amount']           -= closed_amount
        position['_partial_released'] = closed_amount + pnl

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
    def deflated_sharpe_ratio(
        sharpe_obs: float,
        n_obs: int,
        n_trials: int,
        skew: float = 0.0,
        kurt: float = 3.0,
        sharpe_variance: float | None = None,
    ) -> float:
        """Calcula o Deflated Sharpe Ratio (Bailey & López de Prado 2014).

        Responde à pergunta: "dado que testei N configurações de parâmetros,
        qual a probabilidade de que o Sharpe observado seja realmente > 0
        (e não ruído de múltiplos testes + não-normalidade)?"

        Fórmulas (per-period Sharpe):
            t_ratio = (SR_obs - SR_0) * sqrt(n_obs - 1) /
                      sqrt(1 - skew*SR_obs + ((kurt - 1) / 4) * SR_obs²)
            DSR = Φ(t_ratio)

        onde SR_0 (Sharpe esperado do melhor de N trials sob a nula):
            SR_0 = sqrt(V[SR]) × [(1-γ)·Z⁻¹(1 - 1/N) + γ·Z⁻¹(1 - 1/(N·e))]

        γ ≈ 0.5772 (Euler-Mascheroni); e ≈ 2.7183.

        Args:
            sharpe_obs:      Sharpe observado *por período* (não anualizado).
            n_obs:           Número de observações (retornos) usados no Sharpe.
            n_trials:        Número de configurações testadas (≥ 1).
            skew:            Skewness dos retornos (normal = 0).
            kurt:            Kurtosis *não-excesso* (normal = 3.0).
            sharpe_variance: Variância amostral dos Sharpes dos trials.
                             Se None, usa o valor teórico sob a nula = 1 / n_obs
                             (conforme Bailey & López de Prado 2014, eq. 4).

        Returns:
            Probabilidade DSR ∈ [0, 1]. Convencionalmente:
                ≥ 0.95 → confiança estatística (threshold recomendado);
                < 0.50 → Sharpe provavelmente é ruído.

        Riscos:
            - n_obs < 30 torna o teste muito pouco confiável.
            - n_trials = 1 recupera o teste de Sharpe clássico.
        """
        import math
        from math import erf, sqrt, log, exp

        if n_obs < 4 or n_trials < 1:
            return 0.0

        # Variância teórica do Sharpe estimador sob a hipótese nula.
        if sharpe_variance is None or sharpe_variance <= 0:
            sharpe_variance = 1.0 / max(n_obs, 1)

        # Inversa da normal padrão (aproximação de Peter Acklam). Essa função
        # é extremamente precisa em [1e-15, 1 - 1e-15] e evita dependência
        # de scipy. Fonte: https://web.archive.org/web/...peter.acklam/
        def _norm_ppf(p: float) -> float:
            if p <= 0.0 or p >= 1.0:
                return 0.0
            a = [-3.969683028665376e+01,  2.209460984245205e+02,
                 -2.759285104469687e+02,  1.383577518672690e+02,
                 -3.066479806614716e+01,  2.506628277459239e+00]
            b = [-5.447609879822406e+01,  1.615858368580409e+02,
                 -1.556989798598866e+02,  6.680131188771972e+01,
                 -1.328068155288572e+01]
            c = [-7.784894002430293e-03, -3.223964580411365e-01,
                 -2.400758277161838e+00, -2.549732539343734e+00,
                  4.374664141464968e+00,  2.938163982698783e+00]
            d = [ 7.784695709041462e-03,  3.224671290700398e-01,
                  2.445134137142996e+00,  3.754408661907416e+00]
            p_low  = 0.02425
            p_high = 1 - p_low
            if p < p_low:
                q = math.sqrt(-2 * math.log(p))
                return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) \
                       / ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
            if p <= p_high:
                q = p - 0.5
                r = q*q
                return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q \
                       / (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
            q = math.sqrt(-2 * math.log(1 - p))
            return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) \
                   / ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)

        # Normal CDF via erf (stdlib)
        def _norm_cdf(x: float) -> float:
            return 0.5 * (1.0 + erf(x / sqrt(2.0)))

        euler_gamma = 0.5772156649015329

        # SR esperado do *melhor* de N trials sob a nula
        if n_trials <= 1:
            expected_max_sr = 0.0
        else:
            term1 = (1 - euler_gamma) * _norm_ppf(1 - 1.0 / n_trials)
            term2 = euler_gamma * _norm_ppf(1 - 1.0 / (n_trials * exp(1)))
            expected_max_sr = sqrt(sharpe_variance) * (term1 + term2)

        # Denominador (correção por skew/kurt). Clamp para evitar sqrt de neg.
        denom_sq = 1.0 - skew * sharpe_obs + ((kurt - 1.0) / 4.0) * sharpe_obs ** 2
        denom_sq = max(denom_sq, 1e-12)
        denom    = sqrt(denom_sq)

        t_stat = (sharpe_obs - expected_max_sr) * sqrt(max(n_obs - 1, 1)) / denom
        return float(_norm_cdf(t_stat))

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

        # Sharpe por-período (não anualizado) — necessário para Deflated Sharpe.
        sharpe_per_period = (period_returns.mean() /
                             max(period_returns.std(), 1e-9))

        # Skew e kurt dos retornos — usados no cálculo do Deflated Sharpe Ratio
        # (Bailey & López de Prado 2014). kurtosis aqui é o valor *não-excesso*
        # (normal = 3.0), conforme exige a fórmula.
        n_obs = int(len(period_returns))
        if n_obs >= 4:
            ret_skew = float(period_returns.skew())
            ret_kurt = float(period_returns.kurt()) + 3.0   # pandas retorna excesso
        else:
            ret_skew = 0.0
            ret_kurt = 3.0

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
            'sharpe_per_period':  sharpe_per_period,
            'return_skew':        ret_skew,
            'return_kurt':        ret_kurt,
            'n_return_obs':       n_obs,
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
        if m.get('cooldown_bars', 0) > 0:
            print(f"  Cooldown (barras):     {m.get('cooldown_bars', 0):>11d}")
            print(f"  Sinais ignorados:      {m.get('signals_skipped_cooldown', 0):>11d}")
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