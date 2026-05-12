# strategy.py — Estratégia combinada consolidada (indicadores + price action + sentimento)
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

# Importa preferencialmente da nova camada de dados; mantém fallback para legado
try:
    from data.providers import YFinanceProvider as _Provider
    _USE_NEW_PROVIDER = True
except ImportError:
    from data_provider import DataProvider as _Provider   # type: ignore[assignment]
    _USE_NEW_PROVIDER = False

from indicators import TechnicalIndicators
from price_action import PriceActionAnalyzer
from sentiment_analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)


class CombinedStrategy:
    """
    Estratégia de trading combinando análise técnica, price action e sentimento.

    Consolida as funcionalidades de market_strategy.py, advanced_strategy.py
    e enhanced_strategy.py em um único módulo coerente.

    Garantias de idempotência:
      • prepare() é no-op se já chamado (use force=True para re-calcular).
      • generate_signals() deduplica por (data, tipo) — maior força vence.
    """

    DEFAULT_PARAMS: dict = {
        # EMAs
        "ema_short":              8,
        "ema_medium":             21,
        "ema_long":               55,
        # Gerenciamento de risco
        "atr_stop_multiplier":    1.5,
        "atr_target_multiplier":  3.0,
        "max_risk_pct":           0.01,
        "max_position_pct":       0.10,
        # Filtros
        "use_trend_filter":       True,
        "use_sentiment_filter":   True,
        "use_volume_filter":      False,
        "min_pattern_strength":   7,
        "min_sentiment_threshold":30,
        # Direção
        "allow_long":             True,
        "allow_short":            True,
        # Trailing stop
        "use_trailing_stop":      True,
        "trailing_start_atr":     1.5,
        "trailing_step_atr":      0.5,
        # ── Filtro de horário intraday (Sprint-1 passo 4) ─────────────
        # Ativa apenas em dados intraday (auto-detectado). Bloqueia sinais
        # em janelas de baixa liquidez / alta volatilidade espúria.
        #   Abertura B3: 10:00 — primeiros 15min = spread largo, stop hunt
        #   Fechamento B3: 17:00 — últimos 15min = gap risk, thin book
        #   Almoço: 12:00-14:00 — low liquidity, whipsaws frequentes
        "use_time_filter":        False,   # opt-in
        # ── Filtro de regime (Sprint-2 passo 1) ───────────────────────
        # Só gera sinais quando ADX > adx_threshold (tendência confirmada)
        # E Hurst > hurst_threshold (mercado persistente, não mean-reverting).
        # Usar ambos em conjunto reduz whipsaws em mercados laterais.
        "use_regime_filter":      False,   # opt-in
        "adx_threshold":          25.0,    # ADX mínimo para operar
        "hurst_threshold":        0.50,    # Hurst mínimo (0.5 = random walk)
        # ── Volatility Targeting (Sprint-2 passo 2) ───────────────────
        # Escala tamanho de posição pela vol realizada para manter exposição
        # ao risco constante. Reduz posição em regimes voláteis (proteção),
        # aumenta em regimes calmos (captura mais edge).
        "use_vol_targeting":      False,   # opt-in
        "vol_target_annual":      0.15,    # vol alvo anualizada (15%)
        "vol_window":             20,      # janela de vol realizada (barras)
        "vol_scalar_min":         0.25,    # floor do scalar (max redução: 75%)
        "vol_scalar_max":         2.0,     # cap do scalar (max alavancagem: 2x)
        # ── Ensemble de Sinais (Sprint-2 passo 3) ─────────────────────
        # Combina múltiplos geradores de sinal via union+dedup para aumentar
        # frequência de sinais qualificados sem degradar qualidade.
        # Cada sinal ainda passa por todos os filtros (regime, horário, etc.)
        "use_ensemble":           False,   # opt-in
        "ensemble_ema_cross":     True,    # usar EMA crossover
        "ensemble_breakout":      True,    # usar breakout N-barras
        "ensemble_breakout_window": 20,    # janela de máximas/mínimas
        "ensemble_signal_strength": 7,     # forca mínima dos novos sinais
        # ── Fibonacci (Sprint-8) ──────────────────────────────────────
        # Retracementos como sinalizador primário em regimes de tendência.
        # Long entra em pullback a 38.2/50/61.8 em uptrend; Short simétrico.
        # Stop no swing oposto, alvo na extensao 161.8%.
        "ensemble_fibonacci":       False,  # opt-in
        "fib_swing_window":         20,     # barras p/ identificar swing high/low
        "fib_min_swing_atr":        3.0,    # amplitude mínima do swing (em ATRs)
        "fib_tolerance_atr":        0.5,    # proximidade ao nível Fib (em ATRs)
        "fib_min_strength":         7,      # força do sinal Fibonacci
        "fib_regime_bypass":        False,  # opt-in: Fib ignora ADX/Hurst point-in-time
                                            # (fib_trend!=0 já valida swing local,
                                            # mas pode expor a ranges macro — ativar
                                            # somente após validacao por instrumento)
        # Sprint-10: regime macro retrospectivo. Quando > 0, ADX/Hurst são
        # avaliados pela MÉDIA sobre [ts - window, ts], em vez do valor
        # pontual no bar do pullback (que naturalmente cai). Aplica-se a
        # sinais Fibonacci quando fib_regime_bypass=False.
        "fib_regime_macro_window":  0,      # barras (0 = desativa modo macro)
        "fib_macro_adx_min":        20.0,   # threshold relaxado p/ média
        "fib_macro_hurst_min":      0.50,
        # ── Macro Direction Lock (Sprint-11) ───────────────────────────
        # Bloqueia entradas contrárias ao regime macro confirmado.
        # Em uptrend macro (retorno cumulativo > X% E Hurst médio > Y),
        # bloqueia Vendas. Em downtrend simétrico, bloqueia Compras.
        # Objetivo: recuperar alpha em bull/bear sustentados onde sinais
        # de reversão sangram capital contra a direção dominante.
        "macro_direction_lock":     False,  # opt-in
        "macro_direction_window":   60,     # barras de lookback
        "macro_direction_ret_min":  0.05,   # 5% acumulado para "confirmado"
        "macro_direction_hurst_min": 0.55,  # Hurst médio mínimo
        # ── Meta-Labeler (Sprint-4 passo 1) ───────────────────────────────
        # Classificador secundário (RandomForest) que filtra sinais do modelo
        # primário pelos de maior probabilidade de acerto estimada.
        # Requer chamada prévia a train_meta_labeler() (ou fit automático se
        # meta_auto_train=True, que usa os dados já carregados em self.data).
        "use_meta_labeler":       False,   # opt-in
        "meta_min_prob":          0.55,    # P(lucrativo) mínimo para aceitar
        "meta_pt":                2.0,     # mult TP (triple-barrier)
        "meta_sl":                1.0,     # mult SL (triple-barrier)
        "meta_max_holding":       20,      # barras máx barreira vertical
        "meta_n_estimators":      200,     # árvores do RandomForest
        "meta_auto_train":        True,    # treina automaticamente na 1ª vez
        # ── Kelly Criterion sizing (Sprint-6 passo 3) ─────────────────────
        # Escala tamanho de posição pelo f* de Kelly com histórico de trades.
        # Kelly puro é agressivo; kelly_fraction=0.5 (half-Kelly) é padrão.
        # Requer >= 10 trades no histórico para ativar (usa fixed sizing antes).
        "use_kelly_sizing":       False,   # opt-in
        "kelly_fraction":         0.5,     # fração do Kelly ótimo (0.5 = half)
        "kelly_min":              0.10,    # scalar mínimo (floor)
        "kelly_max":              2.0,     # scalar máximo (cap)
        "time_filter_start_hour": 10,
        "time_filter_start_minute": 15,
        "time_filter_end_hour":   16,
        "time_filter_end_minute": 45,
        "time_filter_skip_lunch": False,
        "time_filter_lunch_start_hour": 12,
        "time_filter_lunch_end_hour":   14,
    }

    def __init__(
        self,
        ticker: str,
        name: str = "",
        params: dict | None = None,
    ) -> None:
        self.ticker = ticker
        self.name   = name or ticker
        self.data:  pd.DataFrame | None = None
        self.params = dict(self.DEFAULT_PARAMS)
        if params:
            self.params.update(params)
        self._prepared:      bool = False
        self._meta_labeler          = None   # MetaLabeler instance (lazy)
        self._training_meta: bool = False   # flag anti-reentrada

    # ──────────────────────────────────────────────────────────────────────────
    # Dados
    # ──────────────────────────────────────────────────────────────────────────

    def load_data(self, period: str = "1mo", interval: str = "1d") -> bool:
        """Carrega dados usando o período relativo."""
        self._prepared = False
        if _USE_NEW_PROVIDER:
            provider = _Provider()
            self.data = provider.get_ohlcv(self.ticker, interval, period=period)
        else:
            provider = _Provider(self.ticker, interval=interval, period=period)
            self.data = provider.download()
        return self.data is not None

    def load_historical(
        self, start: str, end: str, interval: str = "1d"
    ) -> bool:
        """Carrega dados históricos para backtesting."""
        self._prepared = False
        if _USE_NEW_PROVIDER:
            provider = _Provider()
            self.data = provider.get_ohlcv(self.ticker, interval, start=start, end=end)
        else:
            provider = _Provider(self.ticker, interval=interval)
            self.data = provider.download_historical(start, end)
        return self.data is not None

    def set_data(self, data: pd.DataFrame) -> None:
        """Define dados externos (útil para testes e otimização com cache)."""
        self.data     = data.copy()
        self._prepared = False

    # ──────────────────────────────────────────────────────────────────────────
    # Preparação
    # ──────────────────────────────────────────────────────────────────────────

    def prepare(self, *, force: bool = False) -> pd.DataFrame | None:
        """Calcula indicadores, padrões e sentimento.

        Idempotente: pula o cálculo se já foi feito. Use ``force=True``
        para forçar re-cálculo (ex: após atualização de dados em tempo real).

        Args:
            force: Se True, recalcula mesmo que prepare() já tenha sido chamado.

        Returns:
            DataFrame atualizado ou None se não há dados.
        """
        if self._prepared and not force:
            logger.debug("prepare() já executado — pulando (use force=True para forçar)")
            return self.data

        if self.data is None or self.data.empty:
            logger.warning("prepare(): nenhum dado carregado")
            return None

        p = self.params

        # 1. Indicadores técnicos (retorna cópia — não muta self.data)
        self.data = TechnicalIndicators.compute_all(self.data, {
            "ema_short":  p["ema_short"],
            "ema_medium": p["ema_medium"],
            "ema_long":   p["ema_long"],
        })

        # 2. Price action (muta self.data in-place via PriceActionAnalyzer)
        pa        = PriceActionAnalyzer(self.data)
        self.data = pa.analisar_padroes()

        # 3. Sentimento
        sa        = SentimentAnalyzer(self.data)
        self.data = sa.calcular_sentimento()

        self._prepared = True
        logger.debug("prepare() concluído: %d períodos, %d colunas",
                     len(self.data), len(self.data.columns))
        return self.data

    # ──────────────────────────────────────────────────────────────────────────
    # Geração de sinais
    # ──────────────────────────────────────────────────────────────────────────

    def generate_signals(self) -> list[dict]:
        """Gera sinais de trading idempotentes.

        • Garante que prepare() foi chamado antes de gerar sinais.
        • Deduplica por (data, tipo): quando dois padrões sinalizam a mesma
          direção no mesmo bar, mantém o de maior ``forca``.
        • Respeita ``allow_long``, ``allow_short`` e ``use_sentiment_filter``.

        Returns:
            Lista de dicts com campos: data, tipo, preco, stop_loss,
            preco_alvo, estrategia, forca.
        """
        if self.data is None or self.data.empty:
            return []

        if not self._prepared:
            self.prepare()

        p = self.params

        # ── Price action signals ──────────────────────────────────────────────
        pa = PriceActionAnalyzer(self.data)
        pa_signals = pa.gerar_sinais_entrada(
            contexto_tendencia=p["use_trend_filter"],
            min_strength=p["min_pattern_strength"],
            ema_short_period=p["ema_medium"],    # usa medium como "referência curta"
            ema_long_period=p["ema_long"],
            atr_stop_mult=p["atr_stop_multiplier"],
            atr_target_mult=p["atr_target_multiplier"],
        )

        # ── Sentiment signals ─────────────────────────────────────────────────
        sa = SentimentAnalyzer(self.data)
        sent_signals = sa.gerar_sinais_sentimento(
            threshold=p["min_sentiment_threshold"],
        )

        all_signals = pa_signals + sent_signals

        # ── Ensemble de sinais (Sprint-2 passo 3) ────────────────────────────
        # Adiciona EMA crossover e/ou Breakout ao pool de sinais.
        # Aumenta frequência mantendo qualidade porque cada gerador tem lógica
        # independente — confluence implícita via deduplicação posterior.
        if p.get("use_ensemble", False):
            if p.get("ensemble_ema_cross", True):
                all_signals += self._ema_crossover_signals()
            if p.get("ensemble_breakout", True):
                all_signals += self._breakout_signals()
            if p.get("ensemble_fibonacci", False):
                all_signals += self._fibonacci_signals()

        # ── Filtro de sentimento ──────────────────────────────────────────────
        if p["use_sentiment_filter"] and "Sentiment_Index" in self.data.columns:
            filtered = []
            for s in all_signals:
                try:
                    loc = self.data.index.get_loc(s["data"])
                    sentiment = float(self.data["Sentiment_Index"].iloc[loc])
                except (KeyError, IndexError):
                    sentiment = 0.0

                if s["tipo"] == "Compra" and sentiment < 0:
                    continue
                if s["tipo"] == "Venda" and sentiment > 0:
                    continue
                filtered.append(s)
            all_signals = filtered

        # ── Filtro de direção ─────────────────────────────────────────────────
        if not p["allow_long"]:
            all_signals = [s for s in all_signals if s["tipo"] != "Compra"]
        if not p["allow_short"]:
            all_signals = [s for s in all_signals if s["tipo"] != "Venda"]

        # ── Macro Direction Lock (Sprint-11) ──────────────────────────────────
        if p.get("macro_direction_lock", False) and all_signals:
            before = len(all_signals)
            all_signals = [s for s in all_signals
                           if self._macro_direction_allows(s)]
            logger.debug("macro_direction_lock: %d -> %d sinais (%d bloqueados)",
                         before, len(all_signals), before - len(all_signals))

        # ── Filtro de horário intraday (Sprint-1 passo 4) ─────────────────────
        # Ataca ruído de abertura/fechamento/almoço. No-op para dados diários.
        if p.get("use_time_filter", False) and self._is_intraday():
            before = len(all_signals)
            all_signals = [s for s in all_signals if self._in_trading_window(s["data"])]
            logger.debug("time_filter: %d -> %d sinais (%d bloqueados)",
                         before, len(all_signals), before - len(all_signals))

        # ── Filtro de regime (Sprint-2 passo 1) ──────────────────────────────
        # Bloqueia sinais quando o mercado não está em regime de tendência.
        # ADX mede força da tendência (> threshold = trend confirmada).
        # Hurst mede persistência (> 0.5 = trending, < 0.5 = mean-reverting).
        # Usar ambos em conjunto reduz falsos positivos (ADX alto em ranges
        # laterais acidentais é detectado por Hurst baixo).
        if p.get("use_regime_filter", False):
            before = len(all_signals)
            all_signals = [s for s in all_signals
                           if self._in_trending_regime(s["data"], signal=s)]
            logger.debug("regime_filter: %d -> %d sinais (%d bloqueados)",
                         before, len(all_signals), before - len(all_signals))

        # ── Deduplicação: um sinal por (data, tipo) — mantém maior forca ──────
        best: dict[tuple, dict] = {}
        for s in all_signals:
            key = (s["data"], s["tipo"])
            if key not in best or s.get("forca", 0) > best[key].get("forca", 0):
                best[key] = s

        deduped = sorted(best.values(), key=lambda s: s["data"])
        logger.debug("generate_signals: %d sinais brutos → %d após deduplicação",
                     len(all_signals), len(deduped))

        # ── Meta-labeler (Sprint-4 passo 1) ──────────────────────────────
        # Filtra sinais com baixa probabilidade de acerto estimada pelo RF.
        # Se meta_auto_train=True e o modelo ainda não foi treinado, treina
        # agora sobre os dados disponíveis (lookback completo).
        if p.get("use_meta_labeler", False) and deduped and not self._training_meta:
            if self._meta_labeler is None and p.get("meta_auto_train", True):
                self.train_meta_labeler()
            if self._meta_labeler is not None and self._meta_labeler._fitted:
                before = len(deduped)
                deduped = self._meta_labeler.filter_signals(deduped, self.data)
                logger.debug("meta_labeler: %d → %d sinais (min_prob=%.2f)",
                             before, len(deduped), p["meta_min_prob"])

        return deduped

    # ──────────────────────────────────────────────────────────────────────────
    # Análise rápida (monitoramento em tempo real)
    # ──────────────────────────────────────────────────────────────────────────

    def analyze(self) -> dict:
        """Executa análise completa e retorna resumo."""
        if self.data is None:
            return {"error": "Sem dados carregados"}

        self.prepare()
        signals = self.generate_signals()
        trend   = self._determine_trend()

        last_price = float(self.data["Close"].iloc[-1])
        rsi_raw    = self.data["RSI"].iloc[-1]
        atr_raw    = self.data["ATR"].iloc[-1]
        rsi_val    = float(rsi_raw) if not pd.isna(rsi_raw) else None
        atr_val    = float(atr_raw) if not pd.isna(atr_raw) else None

        return {
            "ticker":    self.ticker,
            "name":      self.name,
            "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "trend":     trend,
            "last_price":last_price,
            "rsi":       rsi_val,
            "atr":       atr_val,
            "signals":   signals,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Meta-Labeler (Sprint-4 passo 1)
    # ──────────────────────────────────────────────────────────────────────────

    def train_meta_labeler(self, *, force: bool = False) -> bool:
        """Treina o meta-labeler nos dados disponíveis em self.data.

        Chama MetaLabeler.fit_from_strategy() com os params atuais.
        Idempotente: pula se já treinado (use force=True para re-treinar).

        Returns
        -------
        True se o treino foi concluído; False se não havia dados suficientes.
        """
        if self._meta_labeler is not None and self._meta_labeler._fitted and not force:
            return True

        if self.data is None or self.data.empty:
            logger.warning("train_meta_labeler: sem dados")
            return False

        if not self._prepared:
            self.prepare()

        try:
            from meta_labeler import MetaLabeler  # import local p/ evitar dep circular
        except ImportError:
            logger.error("meta_labeler.py não encontrado — MetaLabeler indisponível")
            return False

        p = self.params
        ml = MetaLabeler(
            n_estimators=int(p.get("meta_n_estimators", 200)),
            min_prob=float(p.get("meta_min_prob", 0.55)),
            pt_sl=(float(p.get("meta_pt", 2.0)), float(p.get("meta_sl", 1.0))),
            max_holding=int(p.get("meta_max_holding", 20)),
        )
        self._training_meta = True
        try:
            ml.fit_from_strategy(self, eval_cv=False)   # eval_cv=False p/ velocidade
        finally:
            self._training_meta = False
        self._meta_labeler = ml
        logger.info("train_meta_labeler: fitted=%s cv_roc_auc=%s",
                    ml._fitted, ml.cv_roc_auc)
        return ml._fitted

    def calibrate_meta_labeler(
        self,
        val_fraction: float = 0.25,
        target_recall: float = 0.30,
        metric: str = "f1",
    ) -> float | None:
        """Calibra min_prob do meta-labeler via precision-recall no set de validação.

        Requer que train_meta_labeler() já tenha sido chamado.
        O conjunto de validação são os últimos `val_fraction` dos dados.

        Returns
        -------
        Novo min_prob calibrado, ou None se meta-labeler não treinado.
        """
        if self._meta_labeler is None or not self._meta_labeler._fitted:
            logger.warning("calibrate_meta_labeler: meta-labeler nao treinado")
            return None
        new_prob = self._meta_labeler.calibrate_from_strategy(
            self,
            val_fraction=val_fraction,
            target_recall=target_recall,
            metric=metric,
        )
        logger.info("calibrate_meta_labeler: min_prob -> %.3f", new_prob)
        return new_prob

    # ──────────────────────────────────────────────────────────────────────────
    # Ensemble de sinais (Sprint-2 passo 3)
    # ──────────────────────────────────────────────────────────────────────────

    def _ema_crossover_signals(self) -> list[dict]:
        """Gera sinais de cruzamento de EMAs (rápida x lenta).

        Long:  EMA_short cruza acima de EMA_long (golden cross)
        Short: EMA_short cruza abaixo de EMA_long (death cross)
        Stop  = entry -/+ ATR * atr_stop_multiplier
        Alvo  = entry +/- ATR * atr_target_multiplier
        """
        data = self.data
        if data is None or len(data) < 3:
            return []

        p        = self.params
        strength = int(p.get("ensemble_signal_strength", 7))
        atr_stop = float(p.get("atr_stop_multiplier",  1.5))
        atr_tgt  = float(p.get("atr_target_multiplier", 3.0))

        ema_s_col = f"EMA_{p['ema_short']}"
        ema_l_col = f"EMA_{p['ema_long']}"
        if ema_s_col not in data.columns or ema_l_col not in data.columns:
            return []
        if "ATR" not in data.columns:
            return []

        ema_s = data[ema_s_col]
        ema_l = data[ema_l_col]
        atr   = data["ATR"]
        close = data["Close"]
        signals: list[dict] = []

        for i in range(1, len(data)):
            curr_s = float(ema_s.iloc[i]);   curr_l = float(ema_l.iloc[i])
            prev_s = float(ema_s.iloc[i-1]); prev_l = float(ema_l.iloc[i-1])
            atr_v  = float(atr.iloc[i])
            ts     = data.index[i]
            c      = float(close.iloc[i])

            if pd.isna(curr_s) or pd.isna(curr_l) or pd.isna(atr_v) or atr_v <= 0:
                continue

            if prev_s <= prev_l and curr_s > curr_l and p.get("allow_long", True):
                signals.append({
                    "data":       ts,
                    "tipo":       "Compra",
                    "preco":      c,
                    "stop_loss":  c - atr_v * atr_stop,
                    "preco_alvo": c + atr_v * atr_tgt,
                    "estrategia": "EMA_Cross",
                    "forca":      strength,
                })
            elif prev_s >= prev_l and curr_s < curr_l and p.get("allow_short", True):
                signals.append({
                    "data":       ts,
                    "tipo":       "Venda",
                    "preco":      c,
                    "stop_loss":  c + atr_v * atr_stop,
                    "preco_alvo": c - atr_v * atr_tgt,
                    "estrategia": "EMA_Cross",
                    "forca":      strength,
                })

        return signals

    def _breakout_signals(self) -> list[dict]:
        """Gera sinais de rompimento de N-barras (Donchian-style).

        Long:  Close > max(High[-N:]) da janela anterior
        Short: Close < min(Low[-N:])  da janela anterior
        Stop  = entry -/+ ATR * atr_stop_multiplier
        Alvo  = entry +/- ATR * atr_target_multiplier
        """
        data = self.data
        if data is None or len(data) < 3:
            return []

        p        = self.params
        n        = max(4, int(p.get("ensemble_breakout_window", 20)))
        strength = int(p.get("ensemble_signal_strength", 7))
        atr_stop = float(p.get("atr_stop_multiplier",  1.5))
        atr_tgt  = float(p.get("atr_target_multiplier", 3.0))

        if "ATR" not in data.columns:
            return []

        high  = data["High"]
        low   = data["Low"]
        close = data["Close"]
        atr   = data["ATR"]
        signals: list[dict] = []

        # Máximas/mínimas da janela anterior (exclui barra atual via shift(1))
        roll_high = high.shift(1).rolling(window=n, min_periods=n).max()
        roll_low  = low.shift(1).rolling(window=n, min_periods=n).min()

        for i in range(n + 1, len(data)):
            c     = float(close.iloc[i])
            rh    = roll_high.iloc[i]
            rl    = roll_low.iloc[i]
            atr_v = float(atr.iloc[i])
            ts    = data.index[i]

            if pd.isna(rh) or pd.isna(rl) or pd.isna(atr_v) or atr_v <= 0:
                continue

            if c > float(rh) and p.get("allow_long", True):
                signals.append({
                    "data":       ts,
                    "tipo":       "Compra",
                    "preco":      c,
                    "stop_loss":  c - atr_v * atr_stop,
                    "preco_alvo": c + atr_v * atr_tgt,
                    "estrategia": "Breakout",
                    "forca":      strength,
                })
            elif c < float(rl) and p.get("allow_short", True):
                signals.append({
                    "data":       ts,
                    "tipo":       "Venda",
                    "preco":      c,
                    "stop_loss":  c + atr_v * atr_stop,
                    "preco_alvo": c - atr_v * atr_tgt,
                    "estrategia": "Breakout",
                    "forca":      strength,
                })

        return signals

    # ──────────────────────────────────────────────────────────────────────────
    # Fibonacci retracement entries (Sprint-8)
    # ──────────────────────────────────────────────────────────────────────────

    def _fibonacci_signals(self) -> list[dict]:
        """Gera sinais de entrada em retracements de Fibonacci.

        Long  (uptrend, fib_trend > 0): close se aproxima de 38.2/50/61.8
                                        a partir de cima → comprar pullback.
                                        Stop = swing_low. Alvo = fib_161 ext.
        Short (downtrend, fib_trend < 0): close se aproxima dos mesmos níveis
                                        a partir de baixo → vender rejeição.
                                        Stop = swing_high. Alvo = fib_161 ext.

        Tolerância: |close - level| <= fib_tolerance_atr * ATR.
        Requer indicadores 'fib_*' já calculados em compute_all().
        """
        data = self.data
        if data is None or len(data) < 3:
            return []
        required = {"fib_trend", "fib_38", "fib_50", "fib_61",
                    "fib_swing_high", "fib_swing_low", "fib_161", "ATR"}
        if not required.issubset(data.columns):
            return []

        p         = self.params
        tol_atr   = float(p.get("fib_tolerance_atr", 0.5))
        strength  = int(p.get("fib_min_strength", 7))
        allow_l   = bool(p.get("allow_long", True))
        allow_s   = bool(p.get("allow_short", True))

        close = data["Close"]
        atr   = data["ATR"]
        trend = data["fib_trend"]
        sw_hi = data["fib_swing_high"]
        sw_lo = data["fib_swing_low"]
        f38   = data["fib_38"]
        f50   = data["fib_50"]
        f61   = data["fib_61"]
        f161  = data["fib_161"]

        signals: list[dict] = []
        for i in range(len(data)):
            tr = trend.iloc[i]
            if not np.isfinite(tr) or tr == 0:
                continue
            c     = float(close.iloc[i])
            atr_v = float(atr.iloc[i])
            if not np.isfinite(atr_v) or atr_v <= 0:
                continue
            tol = tol_atr * atr_v
            levels = [f38.iloc[i], f50.iloc[i], f61.iloc[i]]
            hit = any(np.isfinite(lv) and abs(c - float(lv)) <= tol for lv in levels)
            if not hit:
                continue

            ts   = data.index[i]
            ext  = float(f161.iloc[i]) if np.isfinite(f161.iloc[i]) else None
            shi  = float(sw_hi.iloc[i]) if np.isfinite(sw_hi.iloc[i]) else None
            slo  = float(sw_lo.iloc[i]) if np.isfinite(sw_lo.iloc[i]) else None

            if tr > 0 and allow_l and slo is not None and slo < c:
                signals.append({
                    "data":       ts,
                    "tipo":       "Compra",
                    "preco":      c,
                    "stop_loss":  slo,
                    "preco_alvo": ext if (ext is not None and ext > c) else c + 2.0 * (c - slo),
                    "estrategia": "Fibonacci",
                    "forca":      strength,
                })
            elif tr < 0 and allow_s and shi is not None and shi > c:
                signals.append({
                    "data":       ts,
                    "tipo":       "Venda",
                    "preco":      c,
                    "stop_loss":  shi,
                    "preco_alvo": ext if (ext is not None and ext < c) else c - 2.0 * (shi - c),
                    "estrategia": "Fibonacci",
                    "forca":      strength,
                })

        return signals

    # ──────────────────────────────────────────────────────────────────────────
    # Filtro de horário (Sprint-1 passo 4)
    # ──────────────────────────────────────────────────────────────────────────

    def _is_intraday(self) -> bool:
        """Detecta se os dados têm granularidade intraday (< 1 dia).

        Usa a mediana dos deltas entre timestamps consecutivos — robusto a
        gaps de feriado/fim-de-semana. Se delta mediano < 20h, considera
        intraday (permite tolerância para dados 1h que podem ter gaps).
        """
        if self.data is None or len(self.data) < 2:
            return False
        try:
            deltas = pd.Series(self.data.index).diff().dropna()
            if deltas.empty:
                return False
            median_sec = deltas.median().total_seconds()
            return 0 < median_sec < 20 * 3600   # < 20h = intraday
        except (TypeError, AttributeError):
            return False

    def _macro_direction_allows(self, signal: dict) -> bool:
        """Sprint-11 — bloqueia sinal contrário ao regime macro confirmado.

        Computa o retorno cumulativo nos últimos ``macro_direction_window``
        bars antes de ``signal["data"]`` e o Hurst médio na mesma janela.
        Se ambos confirmam uptrend (ret > ret_min E Hurst > hurst_min),
        sinais de Venda são bloqueados. Simétrico para downtrend.

        Retorna True (permite) por padrão — só bloqueia quando o regime
        macro está claramente confirmado e o sinal o contraria.
        """
        if self.data is None:
            return True
        p = self.params
        try:
            loc = self.data.index.get_loc(signal["data"])
        except KeyError:
            return True

        w = int(p.get("macro_direction_window", 60))
        if w <= 0 or loc < 2:
            return True
        lo = max(0, loc - w + 1)
        hi = loc + 1
        close_seg = self.data["Close"].iloc[lo:hi]
        if len(close_seg) < 3:
            return True
        c0 = float(close_seg.iloc[0])
        c1 = float(close_seg.iloc[-1])
        if c0 <= 0:
            return True
        cum_ret = (c1 / c0) - 1.0
        ret_min = float(p.get("macro_direction_ret_min", 0.05))
        h_min = float(p.get("macro_direction_hurst_min", 0.55))

        hurst_mean = None
        if "Hurst" in self.data.columns:
            h_seg = self.data["Hurst"].iloc[lo:hi].dropna()
            if not h_seg.empty:
                hurst_mean = float(h_seg.mean())

        # Confirmação dupla: retorno + Hurst (se disponível)
        up_conf = cum_ret >= ret_min and (hurst_mean is None or hurst_mean >= h_min)
        dn_conf = cum_ret <= -ret_min and (hurst_mean is None or hurst_mean >= h_min)

        tipo = signal.get("tipo", "")
        if up_conf and tipo == "Venda":
            return False
        if dn_conf and tipo == "Compra":
            return False
        return True

    def _in_trending_regime(self, ts, signal: dict | None = None) -> bool:
        """Retorna True se o regime no instante ``ts`` é de tendência.

        Exige que AMBAS as condições sejam atendidas:
            ADX[ts]   >= adx_threshold   (força da tendência)
            Hurst[ts] >= hurst_threshold (persistência)

        Sprint-9 — bypass para Fibonacci:
            Quando ``signal["estrategia"] == "Fibonacci"`` e o parâmetro
            ``fib_regime_bypass`` está ativo, o ADX/Hurst point-in-time é
            ignorado. Justificativa: o gerador Fibonacci só emite quando
            ``fib_trend != 0``, o que por construção exige um swing de
            amplitude >= ``fib_min_swing_atr × ATR`` — proxy estrutural
            do regime de tendência. Como pullbacks reduzem ADX/Hurst
            transitoriamente, exigir o threshold no momento do pullback
            elimina exatamente os setups que queremos capturar.

        Se os indicadores não estiverem disponíveis no índice (cold-start
        ou dados sem colunas ADX/Hurst), retorna True como fallback
        conservador (não bloqueia por ausência de dados).

        Args:
            ts: Timestamp do sinal (deve existir no índice de self.data).
            signal: dict completo do sinal (opcional). Usado para detectar
                estratégia "Fibonacci" e aplicar o bypass.

        Returns:
            True se regime é trending (sinal permitido).
            False se regime é range/mean-reverting (sinal bloqueado).
        """
        p = self.params
        # Se filtro desativado, sempre permite (retrocompatibilidade)
        if not p.get("use_regime_filter", False):
            return True

        is_fib = (signal is not None
                  and signal.get("estrategia") == "Fibonacci")

        # Bypass Fibonacci: confia em fib_trend como proxy de trending
        if is_fib and p.get("fib_regime_bypass", False):
            return True

        if self.data is None:
            return True

        try:
            loc = self.data.index.get_loc(ts)
        except KeyError:
            return True  # timestamp não encontrado — fallback permissivo

        # Sprint-10: modo macro p/ Fibonacci — média sobre janela retrospectiva
        macro_w = int(p.get("fib_regime_macro_window", 0) or 0)
        if is_fib and macro_w > 0:
            lo = max(0, loc - macro_w + 1)
            hi = loc + 1  # inclui ts
            adx_ok_m = True
            if "ADX" in self.data.columns:
                seg = self.data["ADX"].iloc[lo:hi].dropna()
                if not seg.empty:
                    adx_ok_m = float(seg.mean()) >= float(
                        p.get("fib_macro_adx_min", 20.0))
            hurst_ok_m = True
            if "Hurst" in self.data.columns:
                seg = self.data["Hurst"].iloc[lo:hi].dropna()
                if not seg.empty:
                    hurst_ok_m = float(seg.mean()) >= float(
                        p.get("fib_macro_hurst_min", 0.50))
            return adx_ok_m and hurst_ok_m

        # Lê ADX
        adx_ok = True
        if "ADX" in self.data.columns:
            adx_val = self.data["ADX"].iloc[loc]
            if not pd.isna(adx_val):
                adx_ok = float(adx_val) >= float(p.get("adx_threshold", 25.0))

        # Lê Hurst
        hurst_ok = True
        if "Hurst" in self.data.columns:
            h_val = self.data["Hurst"].iloc[loc]
            if not pd.isna(h_val):
                hurst_ok = float(h_val) >= float(p.get("hurst_threshold", 0.50))

        return adx_ok and hurst_ok

    def _in_trading_window(self, ts) -> bool:
        """Retorna True se ``ts`` cai dentro da janela permitida.

        Bloqueia: antes de start, depois de end, e opcionalmente dentro do
        horário de almoço. Usa apenas o componente hora:minuto do timestamp
        (independente de timezone, pois o index já vem na tz do mercado).
        """
        p = self.params
        try:
            hour   = int(ts.hour)
            minute = int(ts.minute)
        except AttributeError:
            return True   # timestamp sem hora (improvável aqui) → não filtra

        t_min = hour * 60 + minute
        start_min = p["time_filter_start_hour"] * 60 + p["time_filter_start_minute"]
        end_min   = p["time_filter_end_hour"]   * 60 + p["time_filter_end_minute"]

        if t_min < start_min or t_min > end_min:
            return False

        if p.get("time_filter_skip_lunch", False):
            lunch_start = p["time_filter_lunch_start_hour"] * 60
            lunch_end   = p["time_filter_lunch_end_hour"]   * 60
            if lunch_start <= t_min < lunch_end:
                return False

        return True

    def _determine_trend(self) -> str:
        """Determina a tendência atual com base em indicadores."""
        if self.data is None or self.data.empty:
            return "Indeterminada"

        # Última linha com SMA_20 e MACD válidos
        valid_idx: int | None = None
        for k in range(-1, -min(len(self.data), 30) - 1, -1):
            sma = self.data["SMA_20"].iloc[k] if "SMA_20" in self.data.columns else np.nan
            mac = self.data["MACD"].iloc[k]   if "MACD"  in self.data.columns else np.nan
            if not (pd.isna(sma) or pd.isna(mac)):
                valid_idx = k
                break

        if valid_idx is None:
            return "Indeterminada"

        score = 0
        close = float(self.data["Close"].iloc[valid_idx])

        # Preço vs SMA_20
        sma20 = self.data["SMA_20"].iloc[valid_idx] if "SMA_20" in self.data.columns else np.nan
        if not pd.isna(sma20):
            score += 1 if close > float(sma20) else -1

        # MACD vs Signal
        macd    = self.data["MACD"].iloc[valid_idx]        if "MACD"        in self.data.columns else np.nan
        macd_sig= self.data["MACD_Signal"].iloc[valid_idx] if "MACD_Signal" in self.data.columns else np.nan
        if not (pd.isna(macd) or pd.isna(macd_sig)):
            score += 2 if float(macd) > float(macd_sig) else -2

        # RSI
        rsi = self.data["RSI"].iloc[valid_idx] if "RSI" in self.data.columns else np.nan
        if not pd.isna(rsi):
            score += 1 if float(rsi) > 50 else -1

        # EMA alignment (parametrizável)
        ep = self.params
        cols = [f'EMA_{ep["ema_short"]}', f'EMA_{ep["ema_medium"]}', f'EMA_{ep["ema_long"]}']
        if all(c in self.data.columns for c in cols):
            e_s = self.data[cols[0]].iloc[valid_idx]
            e_m = self.data[cols[1]].iloc[valid_idx]
            e_l = self.data[cols[2]].iloc[valid_idx]
            if not any(pd.isna(x) for x in [e_s, e_m, e_l]):
                es, em, el = float(e_s), float(e_m), float(e_l)
                if es > em > el:
                    score += 2
                elif es < em < el:
                    score -= 2

        if score >= 3:
            return "Alta"
        if score <= -3:
            return "Baixa"
        return "Lateral"
