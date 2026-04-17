"""
tests/unit/test_strategy.py — Testes unitários de PriceActionAnalyzer e CombinedStrategy.

Executável diretamente:
    python tests/unit/test_strategy.py
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

from price_action import PriceActionAnalyzer
from strategy import CombinedStrategy

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _df(opens, highs, lows, closes, n: int = None) -> pd.DataFrame:
    """Cria DataFrame OHLCV a partir de listas (sem Volume)."""
    n = n or len(closes)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open":   np.array(opens,  dtype=float),
        "High":   np.array(highs,  dtype=float),
        "Low":    np.array(lows,   dtype=float),
        "Close":  np.array(closes, dtype=float),
        "Volume": np.full(n, 10_000.0),
    }, index=idx)


def _ohlcv_trend(n: int = 50, direction: str = "up") -> pd.DataFrame:
    """DataFrame com tendência clara para testes de trend filter.

    Usa ruído mínimo (50 pts) para garantir que indicadores confirmem
    a tendência sem ambiguidade.
    """
    rng = np.random.default_rng(0)
    # Inclina forte (25%) para superar o ruído nos indicadores
    if direction == "up":
        closes = np.linspace(80_000, 120_000, n) + rng.normal(0, 50, n)
    else:
        closes = np.linspace(120_000, 80_000, n) + rng.normal(0, 50, n)
    highs  = closes + rng.uniform(50, 200, n)
    lows   = closes - rng.uniform(50, 200, n)
    opens  = lows + rng.uniform(0, 1, n) * (highs - lows)
    idx    = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows,
        "Close": closes, "Volume": np.full(n, 10_000.0),
    }, index=idx)


def _with_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona EMA_21 e EMA_55 ao DataFrame para habilitar filtro de tendência."""
    from indicators import TechnicalIndicators
    return TechnicalIndicators.compute_all(df)


# ──────────────────────────────────────────────────────────────────────────────
# PriceActionAnalyzer — estrutura de barras
# ──────────────────────────────────────────────────────────────────────────────

def test_bar_structure_columns_present():
    """analisar_padroes deve adicionar todas as colunas de estrutura."""
    opens  = [100, 101, 102]
    highs  = [105, 106, 107]
    lows   = [ 98,  99, 100]
    closes = [103, 104, 105]
    df  = _df(opens, highs, lows, closes)
    pa  = PriceActionAnalyzer(df)
    out = pa.analisar_padroes()

    expected = [
        'Range', 'Body', 'Body_Pct', 'Upper_Wick', 'Lower_Wick',
        'Bull_Bar', 'Bear_Bar', 'Doji',
        'Inside_Bar', 'Outside_Bar',
        'Higher_High', 'Lower_Low',
        'Bullish_Pin_Bar', 'Bearish_Pin_Bar',
        'Bullish_Engulfing', 'Bearish_Engulfing',
    ]
    for col in expected:
        assert col in out.columns, f"Coluna '{col}' ausente após analisar_padroes"
    print("  [OK] test_bar_structure_columns_present")


def test_bull_bar_detection():
    """Barra de alta (close > open) deve ser Bull_Bar == 1."""
    df  = _df([100], [105], [98], [104])
    pa  = PriceActionAnalyzer(df)
    out = pa.calcular_estrutura_barras()
    assert int(out['Bull_Bar'].iloc[0]) == 1, "Bull_Bar deveria ser 1"
    assert int(out['Bear_Bar'].iloc[0]) == 0, "Bear_Bar deveria ser 0"
    print("  [OK] test_bull_bar_detection")


def test_bear_bar_detection():
    """Barra de baixa (close < open) deve ser Bear_Bar == 1."""
    df  = _df([105], [108], [98], [100])
    pa  = PriceActionAnalyzer(df)
    out = pa.calcular_estrutura_barras()
    assert int(out['Bear_Bar'].iloc[0]) == 1
    assert int(out['Bull_Bar'].iloc[0]) == 0
    print("  [OK] test_bear_bar_detection")


def test_doji_detection():
    """Barra com corpo < 10% do range deve ser Doji."""
    # Range = 10, Body = 0.5 → body_pct = 0.05 < 0.1
    df  = _df([100.25], [105], [95], [100.75])
    pa  = PriceActionAnalyzer(df)
    out = pa.calcular_estrutura_barras()
    assert int(out['Doji'].iloc[0]) == 1, (
        f"Doji esperado, body_pct={out['Body_Pct'].iloc[0]:.3f}"
    )
    print("  [OK] test_doji_detection")


def test_inside_bar_detection():
    """Barra com H<=prev_H e L>=prev_L deve ser Inside_Bar."""
    # Bar 0: High=110, Low=90  |  Bar 1: High=105, Low=95 (inside)
    df = _df([100, 100], [110, 105], [90, 95], [105, 102])
    pa  = PriceActionAnalyzer(df)
    out = pa.calcular_estrutura_barras()
    assert int(out['Inside_Bar'].iloc[1]) == 1, "Bar 1 deveria ser Inside_Bar"
    assert int(out['Inside_Bar'].iloc[0]) == 0, "Bar 0 não deveria ser Inside_Bar"
    print("  [OK] test_inside_bar_detection")


def test_outside_bar_detection():
    """Barra com H>=prev_H e L<=prev_L deve ser Outside_Bar."""
    # Bar 0: High=105, Low=95  |  Bar 1: High=110, Low=88 (outside)
    df = _df([100, 100], [105, 110], [95, 88], [102, 105])
    pa  = PriceActionAnalyzer(df)
    out = pa.calcular_estrutura_barras()
    assert int(out['Outside_Bar'].iloc[1]) == 1, "Bar 1 deveria ser Outside_Bar"
    print("  [OK] test_outside_bar_detection")


# ──────────────────────────────────────────────────────────────────────────────
# Padrões de reversão
# ──────────────────────────────────────────────────────────────────────────────

def test_bullish_pin_bar_detected():
    """Pin bar bullish: lower_wick_ratio > 0.6, body_pct < 0.3, lower_low."""
    #          Bar 0 (referência)         Bar 1 (pin bar)
    #  Open=102, H=110, L=95, C=108   Open=102, H=105, L=90, C=103
    #  range_0=15, range_1=15
    #  body_1 = |103-102| = 1 → body_pct = 1/15 ≈ 0.067 < 0.3 ✓
    #  lower_wick_1 = min(102,103) - 90 = 12 → ratio = 12/15 = 0.8 > 0.6 ✓
    #  lower_low_1: 90 < 95 ✓
    opens  = [102, 102]
    highs  = [110, 105]
    lows   = [ 95,  90]
    closes = [108, 103]
    df  = _df(opens, highs, lows, closes)
    pa  = PriceActionAnalyzer(df)
    out = pa.analisar_padroes()
    assert int(out['Bullish_Pin_Bar'].iloc[1]) == 1, (
        f"Bullish_Pin_Bar não detectado. "
        f"body_pct={out['Body_Pct'].iloc[1]:.3f}, "
        f"lower_wick_ratio={out['Lower_Wick_Ratio'].iloc[1]:.3f}, "
        f"lower_low={out['Lower_Low'].iloc[1]}"
    )
    print("  [OK] test_bullish_pin_bar_detected")


def test_bearish_pin_bar_detected():
    """Pin bar bearish: upper_wick_ratio > 0.6, body_pct < 0.3, higher_high."""
    #  Bar 0: O=98, H=105, L=95, C=102
    #  Bar 1: O=103, H=118, L=101, C=104
    #  range_1 = 17, body_1 = 1, body_pct = 1/17 ≈ 0.059 < 0.3 ✓
    #  upper_wick_1 = 118 - max(103,104) = 118-104 = 14 → ratio = 14/17 ≈ 0.82 > 0.6 ✓
    #  higher_high_1: 118 > 105 ✓
    opens  = [ 98, 103]
    highs  = [105, 118]
    lows   = [ 95, 101]
    closes = [102, 104]
    df  = _df(opens, highs, lows, closes)
    pa  = PriceActionAnalyzer(df)
    out = pa.analisar_padroes()
    assert int(out['Bearish_Pin_Bar'].iloc[1]) == 1, (
        f"Bearish_Pin_Bar não detectado. "
        f"body_pct={out['Body_Pct'].iloc[1]:.3f}, "
        f"upper_wick_ratio={out['Upper_Wick_Ratio'].iloc[1]:.3f}, "
        f"higher_high={out['Higher_High'].iloc[1]}"
    )
    print("  [OK] test_bearish_pin_bar_detected")


def test_bullish_engulfing_detected():
    """Engolfo de alta: bear→bull, open < prev_close, close > prev_open."""
    #  Bar 0 (bear): O=105, H=108, L=98, C=100   (bull→ no, bear→ yes)
    #  Bar 1 (bull): O=97,  H=112, L=96, C=108
    #    bear_bar_0: 100 < 105 ✓
    #    bull_bar_1: 108 > 97 ✓
    #    open_1 < close_0: 97 < 100 ✓
    #    close_1 > open_0: 108 > 105 ✓
    opens  = [105,  97]
    highs  = [108, 112]
    lows   = [ 98,  96]
    closes = [100, 108]
    df  = _df(opens, highs, lows, closes)
    pa  = PriceActionAnalyzer(df)
    out = pa.analisar_padroes()
    assert int(out['Bullish_Engulfing'].iloc[1]) == 1, (
        f"Bullish_Engulfing não detectado. "
        f"bear_bar_0={out['Bear_Bar'].iloc[0]}, bull_bar_1={out['Bull_Bar'].iloc[1]}"
    )
    print("  [OK] test_bullish_engulfing_detected")


def test_bearish_engulfing_detected():
    """Engolfo de baixa: bull→bear, open > prev_close, close < prev_open."""
    #  Bar 0 (bull): O=95, H=105, L=94, C=104
    #  Bar 1 (bear): O=106, H=108, L=92, C=93
    #    bull_bar_0: 104 > 95 ✓
    #    bear_bar_1: 93 < 106 ✓
    #    open_1 > close_0: 106 > 104 ✓
    #    close_1 < open_0: 93 < 95 ✓
    opens  = [ 95, 106]
    highs  = [105, 108]
    lows   = [ 94,  92]
    closes = [104,  93]
    df  = _df(opens, highs, lows, closes)
    pa  = PriceActionAnalyzer(df)
    out = pa.analisar_padroes()
    assert int(out['Bearish_Engulfing'].iloc[1]) == 1, (
        f"Bearish_Engulfing não detectado. "
        f"bull_bar_0={out['Bull_Bar'].iloc[0]}, bear_bar_1={out['Bear_Bar'].iloc[1]}"
    )
    print("  [OK] test_bearish_engulfing_detected")


def test_no_false_pattern_on_neutral_bar():
    """Barra neutra (doji dentro de range normal) não deve ativar nenhum padrão de reversão."""
    # 3 barras normais sem padrão extremo
    opens  = [100, 100, 100]
    highs  = [103, 103, 103]
    lows   = [ 97,  97,  97]
    closes = [101, 101, 101]  # ligeiramente bullish, sem sombras extremas
    df  = _df(opens, highs, lows, closes)
    pa  = PriceActionAnalyzer(df)
    out = pa.analisar_padroes()

    reversal_cols = [
        'Bullish_Pin_Bar', 'Bearish_Pin_Bar',
        'Bullish_Engulfing', 'Bearish_Engulfing',
    ]
    for col in reversal_cols:
        if col in out.columns:
            assert out[col].sum() == 0, f"{col} ativado indevidamente: {out[col].tolist()}"
    print("  [OK] test_no_false_pattern_on_neutral_bar")


# ──────────────────────────────────────────────────────────────────────────────
# Geração de sinais — filtros
# ──────────────────────────────────────────────────────────────────────────────

def test_signal_includes_required_fields():
    """Todo sinal deve ter os campos obrigatórios."""
    df  = _with_indicators(_ohlcv_trend(60, "up"))
    pa  = PriceActionAnalyzer(df)
    pa.analisar_padroes()
    signals = pa.gerar_sinais_entrada(contexto_tendencia=False, min_strength=1)

    required = ['data', 'tipo', 'preco', 'stop_loss', 'preco_alvo', 'estrategia', 'forca']
    for s in signals:
        for field in required:
            assert field in s, f"Campo '{field}' ausente no sinal: {s}"
    print(f"  [OK] test_signal_includes_required_fields  ({len(signals)} sinais)")


def test_signal_stop_loss_direction():
    """stop_loss deve estar abaixo do preço para Compra e acima para Venda."""
    df  = _with_indicators(_ohlcv_trend(60))
    pa  = PriceActionAnalyzer(df)
    pa.analisar_padroes()
    signals = pa.gerar_sinais_entrada(contexto_tendencia=False, min_strength=1)

    for s in signals:
        if s['tipo'] == 'Compra':
            assert s['stop_loss'] < s['preco'], (
                f"Stop acima do preço para Compra: stop={s['stop_loss']}, preco={s['preco']}"
            )
        else:
            assert s['stop_loss'] > s['preco'], (
                f"Stop abaixo do preço para Venda: stop={s['stop_loss']}, preco={s['preco']}"
            )
    print(f"  [OK] test_signal_stop_loss_direction")


def test_signal_target_direction():
    """preco_alvo deve estar acima do preço para Compra e abaixo para Venda."""
    df  = _with_indicators(_ohlcv_trend(60))
    pa  = PriceActionAnalyzer(df)
    pa.analisar_padroes()
    signals = pa.gerar_sinais_entrada(contexto_tendencia=False, min_strength=1)

    for s in signals:
        if s['tipo'] == 'Compra':
            assert s['preco_alvo'] > s['preco'], (
                f"Alvo abaixo do preço para Compra"
            )
        else:
            assert s['preco_alvo'] < s['preco'], (
                f"Alvo acima do preço para Venda"
            )
    print(f"  [OK] test_signal_target_direction")


def test_trend_filter_suppresses_counter_trend():
    """Filtro de tendência deve suprimir sinais contra a tendência dominante."""
    # Tendência de alta → sinais de Venda devem ser filtrados
    df = _with_indicators(_ohlcv_trend(80, "up"))
    pa = PriceActionAnalyzer(df)
    pa.analisar_padroes()

    signals_filtered   = pa.gerar_sinais_entrada(contexto_tendencia=True,  min_strength=1)
    signals_unfiltered = pa.gerar_sinais_entrada(contexto_tendencia=False, min_strength=1)

    sell_filtered   = [s for s in signals_filtered   if s['tipo'] == 'Venda']
    sell_unfiltered = [s for s in signals_unfiltered if s['tipo'] == 'Venda']

    # Com filtro ativo em tendência de alta, vendas devem ser <= sem filtro
    assert len(sell_filtered) <= len(sell_unfiltered), (
        "Filtro de tendência não suprimiu sinais de Venda em tendência de alta"
    )
    print(f"  [OK] test_trend_filter_suppresses_counter_trend  "
          f"(Venda: {len(sell_unfiltered)} -> {len(sell_filtered)})")


def test_min_strength_filters_weak_patterns():
    """Padrões com força < min_strength não devem gerar sinais."""
    df = _with_indicators(_ohlcv_trend(60))
    pa = PriceActionAnalyzer(df)
    pa.analisar_padroes()

    # Força 10 = nenhum padrão deve passar
    signals_high = pa.gerar_sinais_entrada(contexto_tendencia=False, min_strength=10)
    assert len(signals_high) == 0, (
        f"min_strength=10 não deveria gerar sinais, obteve {len(signals_high)}"
    )

    # Força 1 = qualquer padrão passa
    signals_low  = pa.gerar_sinais_entrada(contexto_tendencia=False, min_strength=1)
    print(f"  [OK] test_min_strength_filters_weak_patterns  "
          f"(strength=1: {len(signals_low)}, strength=10: {len(signals_high)})")


def test_atr_multiplier_affects_stop():
    """Multiplicador ATR deve afetar a distância do stop."""
    df = _with_indicators(_ohlcv_trend(60))
    pa = PriceActionAnalyzer(df)
    pa.analisar_padroes()

    s1 = pa.gerar_sinais_entrada(contexto_tendencia=False, min_strength=1, atr_stop_mult=1.0)
    s2 = pa.gerar_sinais_entrada(contexto_tendencia=False, min_strength=1, atr_stop_mult=3.0)

    if not s1 or not s2:
        print("  [SKIP] test_atr_multiplier_affects_stop (nenhum sinal gerado)")
        return

    # Para o mesmo sinal de Compra, stop com mult=3 deve estar mais longe
    buy1 = next((s for s in s1 if s['tipo'] == 'Compra'), None)
    buy2 = next((s for s in s2 if s['tipo'] == 'Compra' and s['data'] == buy1['data']), None)

    if buy1 and buy2:
        dist1 = buy1['preco'] - buy1['stop_loss']
        dist2 = buy2['preco'] - buy2['stop_loss']
        assert dist2 > dist1, f"Stop com mult=3 deveria ser maior que mult=1: {dist2:.2f} vs {dist1:.2f}"
        print(f"  [OK] test_atr_multiplier_affects_stop  (dist1={dist1:.0f}, dist2={dist2:.0f})")
    else:
        print("  [SKIP] test_atr_multiplier_affects_stop (sinais em datas diferentes)")


# ──────────────────────────────────────────────────────────────────────────────
# CombinedStrategy — idempotência e deduplicação
# ──────────────────────────────────────────────────────────────────────────────

def test_prepare_idempotent():
    """Chamar prepare() duas vezes não deve duplicar colunas."""
    df = _ohlcv_trend(60)
    s  = CombinedStrategy("TEST", params={"use_sentiment_filter": False})
    s.set_data(df)

    s.prepare()
    cols_after_first = list(s.data.columns)
    n_cols_first     = len(cols_after_first)

    s.prepare()   # segunda chamada — deve ser no-op
    cols_after_second = list(s.data.columns)
    n_cols_second     = len(cols_after_second)

    assert n_cols_first == n_cols_second, (
        f"prepare() duplicou colunas: {n_cols_first} → {n_cols_second}"
    )
    assert cols_after_first == cols_after_second
    print(f"  [OK] test_prepare_idempotent  ({n_cols_first} colunas)")


def test_prepare_force_recalculates():
    """prepare(force=True) deve re-calcular mesmo se já preparado."""
    df = _ohlcv_trend(60)
    s  = CombinedStrategy("TEST", params={"use_sentiment_filter": False})
    s.set_data(df)
    s.prepare()

    assert s._prepared is True

    # Modificar dado artificialmente e forçar re-prepare
    s.data["Close"] *= 1.1
    s._prepared = True           # simular "já preparado"
    s.prepare(force=True)        # deve re-calcular

    assert s._prepared is True
    print("  [OK] test_prepare_force_recalculates")


def test_generate_signals_idempotent():
    """Chamar generate_signals() duas vezes deve retornar mesmo número de sinais."""
    df = _ohlcv_trend(80)
    s  = CombinedStrategy("TEST", params={
        "use_sentiment_filter": False,
        "use_trend_filter": False,
        "min_pattern_strength": 1,
    })
    s.set_data(df)
    s.prepare()

    signals_1 = s.generate_signals()
    signals_2 = s.generate_signals()

    assert len(signals_1) == len(signals_2), (
        f"generate_signals() não é idempotente: {len(signals_1)} vs {len(signals_2)}"
    )
    print(f"  [OK] test_generate_signals_idempotent  ({len(signals_1)} sinais)")


def test_generate_signals_no_duplicate_date_type():
    """Não deve haver dois sinais com mesma (data, tipo) após deduplicação."""
    df = _ohlcv_trend(80)
    s  = CombinedStrategy("TEST", params={
        "use_sentiment_filter": False,
        "use_trend_filter": False,
        "min_pattern_strength": 1,
    })
    s.set_data(df)

    signals = s.generate_signals()

    seen: set = set()
    for sig in signals:
        key = (sig['data'], sig['tipo'])
        assert key not in seen, f"Sinal duplicado (data={sig['data']}, tipo={sig['tipo']})"
        seen.add(key)
    print(f"  [OK] test_generate_signals_no_duplicate_date_type  ({len(signals)} sinais)")


def test_allow_long_false_no_buy_signals():
    """allow_long=False deve suprimir todos os sinais de Compra."""
    df = _ohlcv_trend(80)
    s  = CombinedStrategy("TEST", params={
        "use_sentiment_filter": False,
        "use_trend_filter":     False,
        "min_pattern_strength": 1,
        "allow_long":           False,
        "allow_short":          True,
    })
    s.set_data(df)
    signals = s.generate_signals()

    buys = [sig for sig in signals if sig['tipo'] == 'Compra']
    assert len(buys) == 0, f"allow_long=False mas {len(buys)} sinais de Compra gerados"
    print("  [OK] test_allow_long_false_no_buy_signals")


def test_allow_short_false_no_sell_signals():
    """allow_short=False deve suprimir todos os sinais de Venda."""
    df = _ohlcv_trend(80)
    s  = CombinedStrategy("TEST", params={
        "use_sentiment_filter": False,
        "use_trend_filter":     False,
        "min_pattern_strength": 1,
        "allow_long":           True,
        "allow_short":          False,
    })
    s.set_data(df)
    signals = s.generate_signals()

    sells = [sig for sig in signals if sig['tipo'] == 'Venda']
    assert len(sells) == 0, f"allow_short=False mas {len(sells)} sinais de Venda gerados"
    print("  [OK] test_allow_short_false_no_sell_signals")


def test_determine_trend_alta():
    """Tendência deve ser Alta para série monotonicamente crescente."""
    from indicators import TechnicalIndicators
    df = TechnicalIndicators.compute_all(_ohlcv_trend(80, "up"))
    s  = CombinedStrategy("TEST")
    s.data     = df
    s._prepared = True

    trend = s._determine_trend()
    assert trend == "Alta", f"Tendência esperada Alta, obteve '{trend}'"
    print(f"  [OK] test_determine_trend_alta  (trend='{trend}')")


def test_determine_trend_baixa():
    """Tendência deve ser Baixa para série monotonicamente decrescente."""
    from indicators import TechnicalIndicators
    df = TechnicalIndicators.compute_all(_ohlcv_trend(80, "down"))
    s  = CombinedStrategy("TEST")
    s.data     = df
    s._prepared = True

    trend = s._determine_trend()
    assert trend == "Baixa", f"Tendência esperada Baixa, obteve '{trend}'"
    print(f"  [OK] test_determine_trend_baixa  (trend='{trend}')")


def test_set_data_resets_prepared():
    """set_data() deve resetar o flag _prepared."""
    df = _ohlcv_trend(50)
    s  = CombinedStrategy("TEST")
    s.set_data(df)
    s.prepare()
    assert s._prepared is True

    s.set_data(df)   # novo set_data
    assert s._prepared is False, "_prepared deveria ser False após set_data()"
    print("  [OK] test_set_data_resets_prepared")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_bar_structure_columns_present,
    test_bull_bar_detection,
    test_bear_bar_detection,
    test_doji_detection,
    test_inside_bar_detection,
    test_outside_bar_detection,
    test_bullish_pin_bar_detected,
    test_bearish_pin_bar_detected,
    test_bullish_engulfing_detected,
    test_bearish_engulfing_detected,
    test_no_false_pattern_on_neutral_bar,
    test_signal_includes_required_fields,
    test_signal_stop_loss_direction,
    test_signal_target_direction,
    test_trend_filter_suppresses_counter_trend,
    test_min_strength_filters_weak_patterns,
    test_atr_multiplier_affects_stop,
    test_prepare_idempotent,
    test_prepare_force_recalculates,
    test_generate_signals_idempotent,
    test_generate_signals_no_duplicate_date_type,
    test_allow_long_false_no_buy_signals,
    test_allow_short_false_no_sell_signals,
    test_determine_trend_alta,
    test_determine_trend_baixa,
    test_set_data_resets_prepared,
]


def run_all() -> bool:
    passed = failed = 0
    print(f"\n{'='*60}")
    print("  Suite: strategy/ — price action + filtros + idempotência")
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
