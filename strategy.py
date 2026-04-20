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
        self._prepared: bool = False

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
                           if self._in_trending_regime(s["data"])]
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

    def _in_trending_regime(self, ts) -> bool:
        """Retorna True se o regime no instante ``ts`` é de tendência.

        Exige que AMBAS as condições sejam atendidas:
            ADX[ts]   >= adx_threshold   (força da tendência)
            Hurst[ts] >= hurst_threshold (persistência)

        Se os indicadores não estiverem disponíveis no índice (cold-start
        ou dados sem colunas ADX/Hurst), retorna True como fallback
        conservador (não bloqueia por ausência de dados).

        Args:
            ts: Timestamp do sinal (deve existir no índice de self.data).

        Returns:
            True se regime é trending (sinal permitido).
            False se regime é range/mean-reverting (sinal bloqueado).
        """
        p = self.params
        # Se filtro desativado, sempre permite (retrocompatibilidade)
        if not p.get("use_regime_filter", False):
            return True

        if self.data is None:
            return True

        try:
            loc = self.data.index.get_loc(ts)
        except KeyError:
            return True  # timestamp não encontrado — fallback permissivo

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
