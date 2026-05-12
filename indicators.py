# indicators.py — Módulo consolidado de indicadores técnicos
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Utilitários internos
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_series(data: pd.DataFrame, col: str) -> pd.Series:
    """Extrai uma Series de um DataFrame, mesmo que a coluna seja DataFrame."""
    s = data[col]
    if isinstance(s, pd.DataFrame):
        return s.iloc[:, 0]
    return s


def _safe_series(s: pd.Series, fill: float = np.nan) -> pd.Series:
    """Retorna série zerada com mesmo índice se a entrada for inválida."""
    if s is None or s.empty:
        return pd.Series(dtype=float)
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Classe principal
# ──────────────────────────────────────────────────────────────────────────────

class TechnicalIndicators:
    """
    Calcula indicadores técnicos sobre um DataFrame OHLCV.

    Todos os métodos estáticos aceitam pd.Series e retornam pd.Series,
    permitindo testes unitários isolados de cada indicador.

    compute_all() orquestra o cálculo completo e retorna uma *cópia*
    do DataFrame de entrada com as colunas de indicadores adicionadas.
    """

    # ── Padrões ────────────────────────────────────────────────────────────────

    DEFAULT_PARAMS: dict = {
        "sma_periods": [20, 50],
        "ema_short":   8,
        "ema_medium":  21,
        "ema_long":    55,
        "rsi_period":  14,
        "atr_period":  14,
        "bb_period":   20,
        "bb_std":      2,
        "stoch_k":     14,
        "stoch_d":     3,
        # ── Sprint-2: Regime detection ────────────────────────────────
        "adx_period":   14,   # período do ADX (Wilder)
        "hurst_window": 100,  # barras para estimativa de Hurst (R/S)
    }

    # ── Orquestrador ──────────────────────────────────────────────────────────

    @staticmethod
    def compute_all(data: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
        """Calcula todos os indicadores técnicos sobre uma *cópia* do DataFrame.

        Args:
            data:   DataFrame com colunas OHLCV.
            params: Parâmetros opcionais — sobrescrevem DEFAULT_PARAMS.

        Returns:
            Nova cópia do DataFrame com colunas de indicadores adicionadas.
            O DataFrame original não é modificado.
        """
        if data is None or data.empty:
            logger.warning("compute_all: DataFrame vazio ou None")
            return data

        p = dict(TechnicalIndicators.DEFAULT_PARAMS)
        if params:
            p.update(params)

        df = data.copy()

        close      = _ensure_series(df, "Close")
        high       = _ensure_series(df, "High")
        low        = _ensure_series(df, "Low")

        # ── Médias Móveis Simples ─────────────────────────────────────────────
        for period in p["sma_periods"]:
            df[f"SMA_{period}"] = TechnicalIndicators.sma(close, period)

        # ── Médias Móveis Exponenciais ────────────────────────────────────────
        for label, span in [
            ("short",  p["ema_short"]),
            ("medium", p["ema_medium"]),
            ("long",   p["ema_long"]),
        ]:
            df[f"EMA_{span}"] = TechnicalIndicators.ema(close, span)

        # Aliases usados por outros módulos
        df["MME9"]  = TechnicalIndicators.ema(close, 9)
        df["MME21"] = TechnicalIndicators.ema(close, 21)

        # ── RSI (Wilder SMMA) ─────────────────────────────────────────────────
        df["RSI"] = TechnicalIndicators.rsi(close, p["rsi_period"])

        # ── MACD ──────────────────────────────────────────────────────────────
        macd_line, signal, hist = TechnicalIndicators.macd(close)
        df["MACD"]        = macd_line
        df["MACD_Signal"] = signal
        df["MACD_Hist"]   = hist

        # ── Bandas de Bollinger ───────────────────────────────────────────────
        bb_mid, bb_up, bb_dn = TechnicalIndicators.bollinger_bands(
            close, p["bb_period"], p["bb_std"]
        )
        df["BB_Meio"]     = bb_mid
        df["BB_Superior"] = bb_up
        df["BB_Inferior"] = bb_dn

        # ── ATR (Wilder SMMA) ─────────────────────────────────────────────────
        df["ATR"] = TechnicalIndicators.atr(high, low, close, p["atr_period"])

        # ── Estocástico ───────────────────────────────────────────────────────
        stoch_k, stoch_d = TechnicalIndicators.stochastic(
            high, low, close, p["stoch_k"], p["stoch_d"]
        )
        df["Stoch_K"] = stoch_k
        df["Stoch_D"] = stoch_d

        # ── Volume ────────────────────────────────────────────────────────────
        if "Volume" in df.columns:
            vol = _ensure_series(df, "Volume")
            vol_sma = vol.rolling(window=20, min_periods=1).mean()
            df["Volume_SMA20"] = vol_sma
            df["Volume_Ratio"] = vol / vol_sma.replace(0, np.nan)

        # ── Suporte / Resistência (swing simples) ─────────────────────────────
        df["Suporte"]    = low.rolling(window=10, min_periods=1).min()
        df["Resistencia"] = high.rolling(window=10, min_periods=1).max()

        # ── Volatilidade Realizada (Sprint-2: vol targeting) ─────────────────
        # Anualiza pela periodicidade inferida do índice (igual ao Backtester).
        ann_factor = TechnicalIndicators._infer_ann_factor(df)
        vol_window = p.get("vol_window", 20)
        df["Realized_Vol"] = TechnicalIndicators.realized_vol(
            close, window=vol_window, ann_factor=ann_factor
        )

        # ── ADX + DI+/DI- (Sprint-2: regime detection) ───────────────────────
        adx, di_plus, di_minus = TechnicalIndicators.adx(
            high, low, close, p["adx_period"]
        )
        df["ADX"]      = adx
        df["DI_Plus"]  = di_plus
        df["DI_Minus"] = di_minus

        # ── Hurst Exponent rolling (Sprint-2: regime detection) ───────────────
        df["Hurst"] = TechnicalIndicators.hurst_rolling(
            close, window=p["hurst_window"]
        )

        # ── Niveis de Fibonacci (Sprint-8) ────────────────────────────────────
        # Calcula retracoes e extensoes do ultimo swing relevante.
        # Usa apenas barras i-1 e anteriores para evitar look-ahead.
        fib_window        = p.get("fib_swing_window", 20)
        fib_min_swing_atr = p.get("fib_min_swing_atr", 3.0)
        fib = TechnicalIndicators.fibonacci_levels(
            high, low, close,
            atr=df["ATR"],
            swing_window=fib_window,
            min_swing_atr=fib_min_swing_atr,
        )
        for col in fib.columns:
            df[col] = fib[col]

        logger.debug("Indicadores calculados: %d periodos, %d colunas",
                     len(df), len(df.columns))
        return df

    # ── Indicadores individuais ───────────────────────────────────────────────

    @staticmethod
    def sma(close: pd.Series, period: int) -> pd.Series:
        """Média Móvel Simples.

        Args:
            close:  Série de fechamentos.
            period: Número de períodos.

        Returns:
            Series com SMA; NaN nos primeiros (period-1) elementos.
        """
        return close.rolling(window=period, min_periods=period).mean()

    @staticmethod
    def ema(close: pd.Series, span: int) -> pd.Series:
        """Média Móvel Exponencial (EMA / MME).

        Usa ``adjust=False`` (recursivo), que é o padrão de plataformas
        como MetaTrader / TradingView.

        Args:
            close: Série de fechamentos.
            span:  Número de períodos (alpha = 2 / (span + 1)).

        Returns:
            Series com EMA a partir do primeiro elemento.
        """
        return close.ewm(span=span, adjust=False).mean()

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """RSI usando SMMA de Wilder (comportamento idêntico ao MetaTrader).

        Args:
            close:  Série de fechamentos.
            period: Número de períodos (padrão: 14).

        Returns:
            Series RSI no intervalo [0, 100]; NaN substituído por 50.
        """
        delta    = close.diff()
        gain     = delta.clip(lower=0)
        loss     = (-delta).clip(lower=0)

        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        rs  = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # Casos especiais:
        #   avg_loss == 0, avg_gain > 0  → RSI = 100 (sem perdas)
        #   avg_loss == 0, avg_gain == 0 → RSI = 50  (sem movimento)
        #   avg_gain == 0, avg_loss > 0  → RSI = 0   (sem ganhos)
        no_loss    = avg_loss == 0
        has_gain   = avg_gain > 0
        rsi = rsi.where(~no_loss, np.where(has_gain, 100.0, 50.0))
        rsi = rsi.where(~(avg_gain == 0) | no_loss, 0.0)
        return rsi.fillna(50.0)   # warm-up NaN (min_periods não atingido)

    @staticmethod
    def macd(
        close: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """MACD — Moving Average Convergence Divergence.

        Args:
            close:  Série de fechamentos.
            fast:   Períodos da EMA rápida (padrão: 12).
            slow:   Períodos da EMA lenta (padrão: 26).
            signal: Períodos da linha de sinal (padrão: 9).

        Returns:
            Tupla (macd_line, signal_line, histogram).
        """
        ema_fast   = close.ewm(span=fast,   adjust=False).mean()
        ema_slow   = close.ewm(span=slow,   adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram  = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(
        close: pd.Series,
        period: int = 20,
        num_std: float = 2.0,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Bandas de Bollinger.

        Args:
            close:   Série de fechamentos.
            period:  Períodos da média móvel central (padrão: 20).
            num_std: Múltiplo do desvio padrão (padrão: 2.0).

        Returns:
            Tupla (middle, upper, lower).
        """
        middle = close.rolling(window=period, min_periods=period).mean()
        std    = close.rolling(window=period, min_periods=period).std(ddof=1)
        upper  = middle + std * num_std
        lower  = middle - std * num_std
        return middle, upper, lower

    @staticmethod
    def atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
    ) -> pd.Series:
        """ATR — Average True Range usando SMMA de Wilder.

        CORREÇÃO v2: substituída SMA (rolling.mean) por SMMA de Wilder
        (ewm alpha=1/period), alinhando com MetaTrader / TradingView.

        Args:
            high:   Série de máximas.
            low:    Série de mínimas.
            close:  Série de fechamentos.
            period: Períodos (padrão: 14).

        Returns:
            Series com ATR; NaN nos primeiros períodos.
        """
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low  - close.shift(1)).abs()
        tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    @staticmethod
    def stochastic(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        k_period: int = 14,
        d_period: int = 3,
    ) -> tuple[pd.Series, pd.Series]:
        """Oscilador Estocástico %K e %D.

        Trata o caso de range zero (max == min) com fillna(50) após divisão
        segura, evitando RuntimeWarning de divisão por zero.

        Args:
            high:     Série de máximas.
            low:      Série de mínimas.
            close:    Série de fechamentos.
            k_period: Lookback para %K (padrão: 14).
            d_period: Suavização para %D (padrão: 3).

        Returns:
            Tupla (stoch_k, stoch_d) no intervalo [0, 100].
        """
        min_k  = low.rolling(window=k_period,  min_periods=k_period).min()
        max_k  = high.rolling(window=k_period, min_periods=k_period).max()
        rng    = (max_k - min_k).replace(0, np.nan)          # evita divisão por zero
        stoch_k = ((close - min_k) / rng * 100.0).fillna(50.0)
        stoch_d = stoch_k.rolling(window=d_period, min_periods=d_period).mean().fillna(50.0)
        return stoch_k, stoch_d

    @staticmethod
    def adx(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """ADX — Average Directional Index (Wilder, 1978).

        Mede a *força* da tendência independente de direção.
        Referências de interpretação:
            ADX < 20  → mercado sem tendência (range)
            ADX 20-25 → tendência emergindo
            ADX > 25  → tendência confirmada
            ADX > 40  → tendência forte

        DI+ > DI-   → tendência altista.
        DI- > DI+   → tendência baixista.

        Args:
            high:   Série de máximas.
            low:    Série de mínimas.
            close:  Série de fechamentos.
            period: Períodos do SMMA de Wilder (padrão: 14).

        Returns:
            Tupla (adx, di_plus, di_minus) — todas no intervalo [0, 100].
        """
        # True Range
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)

        # Directional Movement
        up_move   = high - high.shift(1)
        down_move = low.shift(1) - low

        dm_plus  = np.where((up_move > down_move) & (up_move > 0), up_move,  0.0)
        dm_minus = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        dm_plus  = pd.Series(dm_plus,  index=high.index)
        dm_minus = pd.Series(dm_minus, index=high.index)

        # Wilder SMMA (alpha = 1/period)
        alpha = 1.0 / period
        atr_w   = tr.ewm(alpha=alpha,    min_periods=period, adjust=False).mean()
        dmp_sm  = dm_plus.ewm(alpha=alpha,  min_periods=period, adjust=False).mean()
        dmm_sm  = dm_minus.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

        # DI+/DI-
        safe_atr = atr_w.replace(0, np.nan)
        di_plus  = (100.0 * dmp_sm / safe_atr).fillna(0.0)
        di_minus = (100.0 * dmm_sm / safe_atr).fillna(0.0)

        # DX e ADX
        di_sum  = (di_plus + di_minus).replace(0, np.nan)
        dx      = (100.0 * (di_plus - di_minus).abs() / di_sum).fillna(0.0)
        adx_val = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

        return adx_val, di_plus, di_minus

    @staticmethod
    def hurst_rolling(
        close: pd.Series,
        window: int = 100,
        min_periods: int = 40,
    ) -> pd.Series:
        """Expoente de Hurst rolling via análise R/S (Rescaled Range).

        H > 0.55 → mercado trending (persistência) — bom para operar tendência.
        H ≈ 0.50 → random walk — estratégias trend tendem a falhar.
        H < 0.45 → mean-reverting — melhor para estratégias de reversão.

        A estimativa R/S divide a janela em sub-períodos de tamanhos
        [4, 8, 16, ...] e regride log(R/S) sobre log(tamanho).
        O slope da regressão é H. Implementação pura numpy — sem scipy.

        Args:
            close:       Série de fechamentos.
            window:      Tamanho da janela rolling (padrão: 100).
            min_periods: Mínimo de barras para calcular (padrão: 40).

        Returns:
            Series com H no intervalo (0, 1]; NaN onde não há dados suficientes.
        """
        def _rs_hurst(arr: np.ndarray) -> float:
            """R/S para um array 1-D. Retorna H ou NaN se não convergir."""
            n = len(arr)
            if n < 20:
                return np.nan
            # log-retornos
            lret = np.log(arr[1:] / arr[:-1])
            lret = lret[np.isfinite(lret)]
            if len(lret) < 8:
                return np.nan

            # Tamanhos de sub-período: potências de 2 entre 4 e n/4
            lags, rs_vals = [], []
            s = 4
            while s <= len(lret) // 2:
                blocks = len(lret) // s
                rs_block = []
                for b in range(blocks):
                    chunk = lret[b * s:(b + 1) * s]
                    mean_c = chunk.mean()
                    devs   = np.cumsum(chunk - mean_c)
                    std_c  = chunk.std(ddof=1)
                    if std_c < 1e-14:
                        continue
                    rs_block.append((devs.max() - devs.min()) / std_c)
                if rs_block:
                    lags.append(np.log(s))
                    rs_vals.append(np.log(np.mean(rs_block)))
                s *= 2

            if len(lags) < 2:
                return np.nan
            # Regressão OLS simples: y = H * x + c
            x = np.array(lags);  y = np.array(rs_vals)
            xm = x.mean();       ym = y.mean()
            h = float(np.sum((x - xm) * (y - ym)) /
                      max(np.sum((x - xm) ** 2), 1e-14))
            return float(np.clip(h, 0.01, 0.99))

        values = close.values.astype(float)
        result = np.full(len(close), np.nan)
        for i in range(len(close)):
            if i < min_periods - 1:
                continue
            start = max(0, i - window + 1)
            result[i] = _rs_hurst(values[start:i + 1])
        return pd.Series(result, index=close.index)

    @staticmethod
    def realized_vol(
        close: pd.Series,
        window: int = 20,
        ann_factor: float | None = None,
    ) -> pd.Series:
        """Volatilidade realizada anualizada (desvio padrão de log-retornos).

        Usada pelo Volatility Targeting (Sprint-2 passo 2) para escalar o
        tamanho de posição e manter exposição ao risco constante ao longo
        do tempo.

        Fórmula:
            rv[t] = std(log(close[t-w:t] / close[t-w-1:t-1])) * sqrt(A)

        onde A = períodos por ano (252 para diário, 252*8 para 1h, etc.).

        Args:
            close:      Série de fechamentos.
            window:     Tamanho da janela rolling (padrão: 20).
            ann_factor: sqrt(períodos_por_ano). Se None, usa sqrt(252) = diário.

        Returns:
            Series com vol anualizada no intervalo [0, ∞); NaN nos primeiros
            (window-1) períodos.
        """
        if ann_factor is None:
            ann_factor = float(np.sqrt(252))
        log_ret = np.log(close / close.shift(1))
        rv = log_ret.rolling(window=window, min_periods=max(window // 2, 4)).std()
        return rv * ann_factor

    @staticmethod
    def fibonacci_levels(
        high:          pd.Series,
        low:           pd.Series,
        close:         pd.Series,
        atr:           pd.Series | None = None,
        swing_window:  int = 20,
        min_swing_atr: float = 3.0,
    ) -> pd.DataFrame:
        """Niveis de Fibonacci do ultimo swing relevante (Sprint-8).

        Para cada barra i, identifica o ultimo swing (high/low) nas barras
        [i-swing_window, i-1] (janela exclusiva do bar corrente, evita
        look-ahead) e calcula retracoes + extensoes.

        Um swing e considerado valido apenas se a amplitude
        |swing_high - swing_low| for maior que `min_swing_atr * ATR[i-1]`.
        Isso filtra swings triviais em mercados laterais.

        Direcao:
          - "up"   : swing_low veio ANTES do swing_high (tendencia de alta)
          - "down" : swing_high veio ANTES do swing_low (tendencia de baixa)

        Niveis retornados:
          fib_swing_high : ultimo topo do swing
          fib_swing_low  : ultimo fundo do swing
          fib_trend      : +1 (up), -1 (down), 0 (invalido)
          fib_23,38,50,61,78 : retracoes (para entrada em pullback)
          fib_127, fib_161   : extensoes (para targets)

        Args:
            high, low, close : series OHLC.
            atr              : series ATR (opcional; se None, calcula internamente
                              usando wilder 14).
            swing_window     : barras para detectar o swing.
            min_swing_atr    : impulso minimo (em ATRs) para swing ser valido.

        Returns:
            DataFrame com 10 colunas, mesmo indice dos inputs.
        """
        n = len(close)
        if atr is None:
            atr = TechnicalIndicators.atr(high, low, close, 14)

        h_vals   = high.values.astype(float)
        l_vals   = low.values.astype(float)
        atr_vals = atr.values.astype(float)

        cols = ["fib_swing_high", "fib_swing_low", "fib_trend",
                "fib_23", "fib_38", "fib_50", "fib_61", "fib_78",
                "fib_127", "fib_161"]
        out = {c: np.full(n, np.nan) for c in cols}
        out["fib_trend"] = np.zeros(n)   # 0 = indefinido

        for i in range(n):
            if i < swing_window:
                continue
            # Janela exclusiva do bar atual: [i - swing_window, i - 1]
            lo = i - swing_window
            hi = i   # python slice exclusivo → usa barras [lo, i-1]
            window_h = h_vals[lo:hi]
            window_l = l_vals[lo:hi]
            if len(window_h) == 0:
                continue

            idx_h = int(np.argmax(window_h))
            idx_l = int(np.argmin(window_l))
            sw_hi = window_h[idx_h]
            sw_lo = window_l[idx_l]
            amp   = sw_hi - sw_lo

            # Filtro de impulso minimo
            atr_ref = atr_vals[i - 1] if i - 1 < n else np.nan
            if not np.isfinite(atr_ref) or atr_ref <= 0:
                continue
            if amp < min_swing_atr * atr_ref:
                continue
            if amp <= 0:
                continue

            # Direcao: qual extremo veio primeiro
            if idx_l < idx_h:
                trend = 1.0    # up: lo antes do hi
            elif idx_h < idx_l:
                trend = -1.0   # down: hi antes do lo
            else:
                trend = 0.0    # mesmo bar = indeterminado

            out["fib_swing_high"][i] = sw_hi
            out["fib_swing_low"][i]  = sw_lo
            out["fib_trend"][i]      = trend

            # Retracoes medidas do extremo final em direcao ao extremo inicial:
            #   Trend up  : retracao desce de sw_hi em direcao a sw_lo
            #   Trend down: retracao sobe de sw_lo em direcao a sw_hi
            if trend > 0:
                out["fib_23"][i]  = sw_hi - 0.236 * amp
                out["fib_38"][i]  = sw_hi - 0.382 * amp
                out["fib_50"][i]  = sw_hi - 0.500 * amp
                out["fib_61"][i]  = sw_hi - 0.618 * amp
                out["fib_78"][i]  = sw_hi - 0.786 * amp
                out["fib_127"][i] = sw_hi + 0.272 * amp   # ext 127.2
                out["fib_161"][i] = sw_hi + 0.618 * amp   # ext 161.8
            elif trend < 0:
                out["fib_23"][i]  = sw_lo + 0.236 * amp
                out["fib_38"][i]  = sw_lo + 0.382 * amp
                out["fib_50"][i]  = sw_lo + 0.500 * amp
                out["fib_61"][i]  = sw_lo + 0.618 * amp
                out["fib_78"][i]  = sw_lo + 0.786 * amp
                out["fib_127"][i] = sw_lo - 0.272 * amp
                out["fib_161"][i] = sw_lo - 0.618 * amp

        return pd.DataFrame(out, index=close.index)

    @staticmethod
    def _infer_ann_factor(data: pd.DataFrame) -> float:
        """Infere o fator de anualização a partir da mediana dos deltas de índice.

        Mapeamento:
            <= 90s  → 1m  → 252 * 480
            <= 360s → 5m  → 252 * 96
            <= 1080 → 15m → 252 * 32
            <= 2100 → 30m → 252 * 16
            <= 5400 → 1h  → 252 * 8
            <= 21600 → 4h → 252 * 2
            <= 129600 → 1d → 252
            else → 52 (semanal) ou 12 (mensal)

        Retorna sqrt(períodos_por_ano).
        """
        if data is None or len(data) < 2:
            return float(np.sqrt(252))
        try:
            deltas = pd.Series(data.index).diff().dropna()
            if deltas.empty:
                return float(np.sqrt(252))
            med = deltas.median().total_seconds()
        except (TypeError, AttributeError):
            return float(np.sqrt(252))
        if   med <= 90:      ppy = 252 * 480
        elif med <= 360:     ppy = 252 * 96
        elif med <= 1080:    ppy = 252 * 32
        elif med <= 2100:    ppy = 252 * 16
        elif med <= 5400:    ppy = 252 * 8
        elif med <= 21600:   ppy = 252 * 2
        elif med <= 129600:  ppy = 252
        elif med <= 777600:  ppy = 52
        else:                ppy = 12
        return float(np.sqrt(ppy))
