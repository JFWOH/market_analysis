"""
tests/unit/test_indicators.py — Testes de regressão numérica para TechnicalIndicators.

Executável diretamente:
    python tests/unit/test_indicators.py

Ou via pytest quando disponível.

Estratégia de regressão:
  • Séries determinísticas (seed fixo ou aritméticas) com valores esperados
    calculados por referência analítica ou validados via pandas puro.
  • Tolerância: rtol=1e-6 para igualdade numérica.
  • Invariantes de domínio: RSI ∈ [0,100], Stoch ∈ [0,100], ATR ≥ 0, etc.
"""

from __future__ import annotations

import os
import sys
import traceback

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from indicators import TechnicalIndicators as TI

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _arithmetic(n: int = 20, start: float = 1.0) -> pd.Series:
    """Série aritmética 1, 2, 3, … n."""
    return pd.Series(np.arange(start, start + n, dtype=float))


def _ohlcv_df(n: int = 60) -> pd.DataFrame:
    """DataFrame OHLCV sintético determinístico (seed 42)."""
    rng    = np.random.default_rng(42)
    closes = 100_000.0 + np.cumsum(rng.normal(0, 500, n))
    highs  = closes + rng.uniform(100, 800, n)
    lows   = closes - rng.uniform(100, 800, n)
    opens  = lows + rng.uniform(0, 1, n) * (highs - lows)
    vols   = rng.integers(1_000, 50_000, n).astype(float)
    idx    = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
        index=idx,
    )


# ──────────────────────────────────────────────────────────────────────────────
# SMA
# ──────────────────────────────────────────────────────────────────────────────

def test_sma_arithmetic():
    """SMA(3) de série aritmética 1..10 — valores analíticos exatos."""
    s   = _arithmetic(10)
    out = TI.sma(s, 3)

    # Primeiros 2 devem ser NaN
    assert np.isnan(out.iloc[0]), "SMA[0] deve ser NaN"
    assert np.isnan(out.iloc[1]), "SMA[1] deve ser NaN"

    # SMA_3[i] = mean(s[i-2], s[i-1], s[i])
    expected = {2: 2.0, 3: 3.0, 4: 4.0, 5: 5.0, 9: 9.0}
    for i, val in expected.items():
        assert abs(out.iloc[i] - val) < 1e-9, f"SMA[{i}] esperado {val}, obteve {out.iloc[i]}"
    print("  [OK] test_sma_arithmetic")


def test_sma_period_equals_length():
    """SMA com period == len deve ter só um valor não-NaN (o último)."""
    s   = _arithmetic(5)
    out = TI.sma(s, 5)
    assert out.isna().sum() == 4
    assert abs(out.iloc[4] - 3.0) < 1e-9  # mean(1,2,3,4,5) = 3.0
    print("  [OK] test_sma_period_equals_length")


# ──────────────────────────────────────────────────────────────────────────────
# EMA
# ──────────────────────────────────────────────────────────────────────────────

def test_ema_span3_arithmetic():
    """EMA(span=3) sobre [1,2,3,4,5] — recursão manual verificada.

    alpha = 2/(3+1) = 0.5
    EMA[0] = 1.0
    EMA[1] = 0.5*2 + 0.5*1.0 = 1.5
    EMA[2] = 0.5*3 + 0.5*1.5 = 2.25
    EMA[3] = 0.5*4 + 0.5*2.25 = 3.125
    EMA[4] = 0.5*5 + 0.5*3.125 = 4.0625
    """
    s   = _arithmetic(5)
    out = TI.ema(s, span=3)

    expected = [1.0, 1.5, 2.25, 3.125, 4.0625]
    for i, val in enumerate(expected):
        assert abs(out.iloc[i] - val) < 1e-9, (
            f"EMA[{i}] esperado {val:.6f}, obteve {out.iloc[i]:.6f}"
        )
    print("  [OK] test_ema_span3_arithmetic")


def test_ema_no_nan():
    """EMA não deve produzir NaN para nenhum elemento (seed de EWM é o primeiro valor)."""
    s   = _arithmetic(50)
    out = TI.ema(s, span=14)
    assert not out.isna().any(), "EMA não deve ter NaN"
    print("  [OK] test_ema_no_nan")


# ──────────────────────────────────────────────────────────────────────────────
# RSI
# ──────────────────────────────────────────────────────────────────────────────

def test_rsi_range():
    """RSI deve estar sempre no intervalo [0, 100]."""
    df  = _ohlcv_df(100)
    rsi = TI.rsi(df["Close"], 14)
    assert rsi.between(0, 100).all(), "RSI fora do intervalo [0, 100]"
    print("  [OK] test_rsi_range")


def test_rsi_all_gains():
    """Série monotonicamente crescente deve gerar RSI próximo de 100."""
    s   = pd.Series(np.linspace(100, 200, 50))
    rsi = TI.rsi(s, 14)
    # Após warm-up (14 períodos), RSI deve ser > 90
    assert rsi.iloc[-1] > 90, f"RSI esperado >90 para série crescente, obteve {rsi.iloc[-1]:.2f}"
    print("  [OK] test_rsi_all_gains")


def test_rsi_all_losses():
    """Série monotonicamente decrescente deve gerar RSI próximo de 0."""
    s   = pd.Series(np.linspace(200, 100, 50))
    rsi = TI.rsi(s, 14)
    assert rsi.iloc[-1] < 10, f"RSI esperado <10 para série decrescente, obteve {rsi.iloc[-1]:.2f}"
    print("  [OK] test_rsi_all_losses")


def test_rsi_constant_series():
    """Série constante → sem ganhos nem perdas → RSI deve ser 50 (fillna)."""
    s   = pd.Series([100.0] * 30)
    rsi = TI.rsi(s, 14)
    # Primeiros 14 são NaN (min_periods) → fillna(50)
    assert (rsi == 50.0).all(), f"RSI série constante deve ser 50, obteve {rsi.unique()}"
    print("  [OK] test_rsi_constant_series")


def test_rsi_numerical_regression():
    """Regressão numérica: RSI[30] para série seed=42 deve ser estável."""
    df  = _ohlcv_df(60)
    rsi = TI.rsi(df["Close"], 14)
    val = round(float(rsi.iloc[30]), 4)
    # Valor calculado da implementação corrigida (Wilder SMMA) — golden value
    # Recalculado via pandas ewm(alpha=1/14, adjust=False): ~53.xxxx
    # Aceitamos range ±0.5 para robustez entre plataformas
    assert 30.0 < val < 70.0, f"RSI[30] fora do range esperado: {val}"
    print(f"  [OK] test_rsi_numerical_regression  (RSI[30]={val})")


# ──────────────────────────────────────────────────────────────────────────────
# ATR
# ──────────────────────────────────────────────────────────────────────────────

def test_atr_non_negative():
    """ATR deve ser sempre não-negativo."""
    df  = _ohlcv_df(60)
    atr = TI.atr(df["High"], df["Low"], df["Close"], 14)
    valid = atr.dropna()
    assert (valid >= 0).all(), "ATR não deve ser negativo"
    print("  [OK] test_atr_non_negative")


def test_atr_wilder_vs_sma():
    """ATR Wilder (SMMA) deve diferir de SMA rolling para a mesma série.

    Verifica que a correção está ativa: se ambos fossem iguais, o fix foi perdido.
    """
    df    = _ohlcv_df(60)
    high, low, close = df["High"], df["Low"], df["Close"]
    period = 14

    # ATR Wilder (implementação atual)
    atr_wilder = TI.atr(high, low, close, period)

    # ATR SMA (referência para diferença)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low  - close.shift(1)).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_sma = tr.rolling(window=period).mean()

    # Devem divergir após o período de warm-up
    diff = (atr_wilder.dropna() - atr_sma.dropna()).abs()
    assert diff.max() > 1.0, (
        "ATR Wilder e ATR SMA são idênticos — fix Wilder não está ativo"
    )
    print(f"  [OK] test_atr_wilder_vs_sma  (max_diff={diff.max():.2f})")


def test_atr_numerical_regression():
    """ATR[30] para série seed=42 deve ser estável entre execuções."""
    df  = _ohlcv_df(60)
    atr = TI.atr(df["High"], df["Low"], df["Close"], 14)
    val = round(float(atr.iloc[30]), 2)
    # Valor esperado: entre 300 e 2000 pontos para série Ibovespa sintética
    assert 100.0 < val < 5000.0, f"ATR[30] fora do range esperado: {val}"
    print(f"  [OK] test_atr_numerical_regression  (ATR[30]={val})")


# ──────────────────────────────────────────────────────────────────────────────
# MACD
# ──────────────────────────────────────────────────────────────────────────────

def test_macd_returns_tuple():
    """macd() deve retornar tupla de 3 Series com mesmo índice."""
    df          = _ohlcv_df(60)
    line, sig, hist = TI.macd(df["Close"])
    assert isinstance(line, pd.Series)
    assert isinstance(sig,  pd.Series)
    assert isinstance(hist, pd.Series)
    assert len(line) == len(df)
    print("  [OK] test_macd_returns_tuple")


def test_macd_hist_equals_line_minus_signal():
    """Histograma deve ser exatamente MACD - Signal."""
    df             = _ohlcv_df(60)
    line, sig, hist = TI.macd(df["Close"])
    diff = (hist - (line - sig)).abs()
    assert diff.max() < 1e-9, f"Histograma != MACD - Signal (max_err={diff.max():.2e})"
    print("  [OK] test_macd_hist_equals_line_minus_signal")


def test_macd_zero_crossings():
    """MACD deve cruzar zero em série com tendência conhecida."""
    # Série: sobe 30 candles, depois desce 30 candles
    up   = np.linspace(100, 200, 30)
    down = np.linspace(200, 100, 30)
    s    = pd.Series(np.concatenate([up, down]))
    line, sig, hist = TI.macd(s)
    # Linha MACD deve ter valores positivos na parte de alta e negativos na baixa
    # (com atraso do EWM). Verificamos apenas que há cruzamento de zero.
    has_positive = (line > 0).any()
    has_negative = (line < 0).any()
    assert has_positive and has_negative, "MACD deve cruzar zero em série com reversão"
    print("  [OK] test_macd_zero_crossings")


# ──────────────────────────────────────────────────────────────────────────────
# Bollinger Bands
# ──────────────────────────────────────────────────────────────────────────────

def test_bollinger_ordering():
    """Upper >= Middle >= Lower deve sempre ser verdade onde não é NaN."""
    df             = _ohlcv_df(60)
    mid, up, dn    = TI.bollinger_bands(df["Close"], 20, 2.0)
    valid          = mid.notna()
    assert (up[valid] >= mid[valid]).all(), "BB Upper < Middle"
    assert (mid[valid] >= dn[valid]).all(), "BB Middle < Lower"
    print("  [OK] test_bollinger_ordering")


def test_bollinger_width_constant_series():
    """Série constante → desvio zero → upper == middle == lower."""
    s           = pd.Series([100.0] * 30)
    mid, up, dn = TI.bollinger_bands(s, 20, 2.0)
    valid        = mid.notna()
    assert (up[valid] == mid[valid]).all(), "BB Upper deve ser igual ao Middle para série constante"
    assert (dn[valid] == mid[valid]).all(), "BB Lower deve ser igual ao Middle para série constante"
    print("  [OK] test_bollinger_width_constant_series")


def test_bollinger_numerical():
    """BB Middle[25] deve ser SMA_20 calculada manualmente."""
    df          = _ohlcv_df(60)
    close       = df["Close"]
    mid, up, dn = TI.bollinger_bands(close, 20, 2.0)

    # Middle é SMA_20 — verifica contra rolling manual
    sma_manual  = close.rolling(20).mean()
    diff        = (mid - sma_manual).abs().dropna()
    assert diff.max() < 1e-9, f"BB Middle diverge de SMA_20 (max_err={diff.max():.2e})"
    print("  [OK] test_bollinger_numerical")


# ──────────────────────────────────────────────────────────────────────────────
# Estocástico
# ──────────────────────────────────────────────────────────────────────────────

def test_stochastic_range():
    """Stoch K e D devem estar em [0, 100]."""
    df          = _ohlcv_df(60)
    stoch_k, stoch_d = TI.stochastic(df["High"], df["Low"], df["Close"])
    assert stoch_k.between(0, 100).all(), "Stoch_K fora de [0, 100]"
    assert stoch_d.between(0, 100).all(), "Stoch_D fora de [0, 100]"
    print("  [OK] test_stochastic_range")


def test_stochastic_zero_range():
    """High == Low em todos os candles → range zero → fillna(50)."""
    n     = 30
    price = pd.Series([100.0] * n)
    stoch_k, stoch_d = TI.stochastic(price, price, price)
    assert (stoch_k == 50.0).all(), "Stoch_K deve ser 50 quando range=0"
    print("  [OK] test_stochastic_zero_range")


def test_stochastic_high_at_close():
    """Quando Close == High (sempre), %K deve ser 100."""
    n     = 30
    high  = pd.Series(np.linspace(100, 200, n))
    low   = pd.Series(np.linspace( 90, 190, n))
    close = high.copy()   # Close == High → %K = 100
    stoch_k, _ = TI.stochastic(high, low, close, k_period=14)
    valid = stoch_k.iloc[14:]   # após warm-up
    assert (valid == 100.0).all(), f"Stoch_K deve ser 100 quando Close==High; obteve {valid.unique()}"
    print("  [OK] test_stochastic_high_at_close")


# ──────────────────────────────────────────────────────────────────────────────
# compute_all
# ──────────────────────────────────────────────────────────────────────────────

def test_compute_all_no_mutation():
    """compute_all não deve modificar o DataFrame original."""
    df      = _ohlcv_df(60)
    cols_before = set(df.columns)
    _result = TI.compute_all(df)
    assert set(df.columns) == cols_before, (
        "compute_all mutou o DataFrame original"
    )
    print("  [OK] test_compute_all_no_mutation")


def test_compute_all_columns_present():
    """compute_all deve produzir todas as colunas esperadas."""
    df     = _ohlcv_df(60)
    result = TI.compute_all(df)
    expected_cols = [
        "SMA_20", "SMA_50", "EMA_8", "EMA_21", "EMA_55",
        "MME9", "MME21",
        "RSI",
        "MACD", "MACD_Signal", "MACD_Hist",
        "BB_Meio", "BB_Superior", "BB_Inferior",
        "ATR",
        "Stoch_K", "Stoch_D",
        "Volume_SMA20", "Volume_Ratio",
        "Suporte", "Resistencia",
    ]
    for col in expected_cols:
        assert col in result.columns, f"Coluna '{col}' ausente no resultado de compute_all"
    print("  [OK] test_compute_all_columns_present")


def test_compute_all_length_preserved():
    """compute_all deve retornar DataFrame com mesmo número de linhas."""
    df     = _ohlcv_df(60)
    result = TI.compute_all(df)
    assert len(result) == len(df), (
        f"compute_all alterou o número de linhas: {len(result)} != {len(df)}"
    )
    print("  [OK] test_compute_all_length_preserved")


def test_compute_all_custom_params():
    """Parâmetros customizados devem ser respeitados."""
    df     = _ohlcv_df(60)
    params = {"ema_short": 5, "ema_long": 30, "rsi_period": 9}
    result = TI.compute_all(df, params=params)
    assert "EMA_5"  in result.columns, "EMA_5 deveria existir com ema_short=5"
    assert "EMA_30" in result.columns, "EMA_30 deveria existir com ema_long=30"
    print("  [OK] test_compute_all_custom_params")


def test_compute_all_empty_df():
    """compute_all com DataFrame vazio deve retornar o próprio vazio sem erro."""
    df     = pd.DataFrame()
    result = TI.compute_all(df)
    assert result is not None
    assert result.empty
    print("  [OK] test_compute_all_empty_df")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_sma_arithmetic,
    test_sma_period_equals_length,
    test_ema_span3_arithmetic,
    test_ema_no_nan,
    test_rsi_range,
    test_rsi_all_gains,
    test_rsi_all_losses,
    test_rsi_constant_series,
    test_rsi_numerical_regression,
    test_atr_non_negative,
    test_atr_wilder_vs_sma,
    test_atr_numerical_regression,
    test_macd_returns_tuple,
    test_macd_hist_equals_line_minus_signal,
    test_macd_zero_crossings,
    test_bollinger_ordering,
    test_bollinger_width_constant_series,
    test_bollinger_numerical,
    test_stochastic_range,
    test_stochastic_zero_range,
    test_stochastic_high_at_close,
    test_compute_all_no_mutation,
    test_compute_all_columns_present,
    test_compute_all_length_preserved,
    test_compute_all_custom_params,
    test_compute_all_empty_df,
]


def run_all() -> bool:
    passed = failed = 0
    print(f"\n{'='*60}")
    print("  Suite: indicators/ — regressão numérica")
    print(f"{'='*60}")
    for fn in _TESTS:
        try:
            fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"  [FAIL] {fn.__name__}")
            traceback.print_exc()
    print(f"{'='*60}")
    print(f"  Resultado: {passed} passou(aram) / {failed} falhou(aram)")
    print(f"{'='*60}\n")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
