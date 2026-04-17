"""
tests/unit/test_data.py — Testes determinísticos para o pacote data/.

Não requer pytest instalado: pode ser executado diretamente com
    python tests/unit/test_data.py

Quando pytest estiver disponível, também funciona como suíte normal.
"""

from __future__ import annotations

import sys
import os
import tempfile
import traceback
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# Garante que a raiz do projeto está no path
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.schema import OHLCVSchema, OHLCVValidationError
from data.cache import DataCache

_TZ_B3 = ZoneInfo("America/Sao_Paulo")

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 10, tz_aware: bool = False) -> pd.DataFrame:
    """Gera DataFrame OHLCV sintético e determinístico."""
    rng = np.random.default_rng(42)
    base = 100_000.0
    closes = base + np.cumsum(rng.normal(0, 500, n))
    highs  = closes + rng.uniform(100, 800, n)
    lows   = closes - rng.uniform(100, 800, n)
    opens  = lows + rng.uniform(0, highs - lows)

    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    if tz_aware:
        idx = idx.tz_localize("UTC").tz_convert(_TZ_B3)

    return pd.DataFrame(
        {
            "Open":   opens,
            "High":   highs,
            "Low":    lows,
            "Close":  closes,
            "Volume": rng.integers(1_000, 50_000, n).astype(float),
        },
        index=idx,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Testes de Schema
# ──────────────────────────────────────────────────────────────────────────────

def test_schema_valid_df():
    """DataFrame bem-formado deve passar sem erros."""
    df = _make_ohlcv(20)
    result = OHLCVSchema.validate(df)
    assert isinstance(result, pd.DataFrame), "validate() deve retornar DataFrame"
    assert len(result) == 20
    assert list(result.columns[:5]) == ["Open", "High", "Low", "Close", "Volume"] or \
           all(c in result.columns for c in ["Open", "High", "Low", "Close", "Volume"])
    print("  [OK] test_schema_valid_df")


def test_schema_missing_column():
    """DataFrame sem coluna obrigatória deve levantar OHLCVValidationError."""
    df = _make_ohlcv(5).drop(columns=["Volume"])
    ok, errors = OHLCVSchema.check(df)
    assert not ok, "check() deve retornar False para coluna ausente"
    assert any("Volume" in e for e in errors), f"Esperado 'Volume' nos erros: {errors}"
    print("  [OK] test_schema_missing_column")


def test_schema_high_less_than_low():
    """Linhas com High < Low devem ser removidas com drop_bad_rows=True."""
    df = _make_ohlcv(10)
    # Corrompe 2 linhas
    df.iloc[2, df.columns.get_loc("High")] = df.iloc[2]["Low"] - 100
    df.iloc[7, df.columns.get_loc("High")] = df.iloc[7]["Low"] - 50
    result = OHLCVSchema.validate(df, drop_bad_rows=True)
    assert len(result) == 8, f"Esperadas 8 linhas, obteve {len(result)}"
    assert (result["High"] >= result["Low"]).all(), "Ainda há High < Low após limpeza"
    print("  [OK] test_schema_high_less_than_low")


def test_schema_negative_volume_zeroed():
    """Volume negativo deve ser zerado sem remover a linha."""
    df = _make_ohlcv(5)
    df.iloc[1, df.columns.get_loc("Volume")] = -500.0
    result = OHLCVSchema.validate(df, drop_bad_rows=True)
    assert len(result) == 5, "Nenhuma linha deve ser removida por volume negativo"
    assert result.iloc[1]["Volume"] == 0.0, "Volume negativo deve ser zerado"
    print("  [OK] test_schema_negative_volume_zeroed")


def test_schema_unordered_index():
    """Índice desordenado deve ser reordenado automaticamente."""
    df = _make_ohlcv(10)
    df = df.iloc[::-1]  # Inverte
    assert not df.index.is_monotonic_increasing
    result = OHLCVSchema.validate(df)
    assert result.index.is_monotonic_increasing, "Índice deve estar ordenado após validate()"
    print("  [OK] test_schema_unordered_index")


def test_schema_check_returns_tuple():
    """check() deve retornar (bool, list) sem levantar exceção."""
    df = _make_ohlcv(5)
    ok, errors = OHLCVSchema.check(df)
    assert isinstance(ok, bool)
    assert isinstance(errors, list)
    assert ok is True
    assert errors == []
    print("  [OK] test_schema_check_returns_tuple")


# ──────────────────────────────────────────────────────────────────────────────
# Testes de Cache
# ──────────────────────────────────────────────────────────────────────────────

def test_cache_set_get():
    """Set seguido de Get deve retornar DataFrame idêntico."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DataCache(cache_dir=tmpdir)
        df = _make_ohlcv(15)
        key = DataCache.make_key("^BVSP", "1d", "2023-01-01", "2023-12-31")

        cache.set(key, df)
        result = cache.get(key, interval="1d")

        assert result is not None, "cache.get() não deve retornar None após set()"
        assert len(result) == 15
        pd.testing.assert_frame_equal(df, result)
    print("  [OK] test_cache_set_get")


def test_cache_miss():
    """Get para chave inexistente deve retornar None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DataCache(cache_dir=tmpdir)
        result = cache.get("nonexistent_key", interval="1d")
        assert result is None, "cache.get() deve retornar None para chave inexistente"
    print("  [OK] test_cache_miss")


def test_cache_invalidate():
    """Invalidate deve remover entrada e get deve retornar None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DataCache(cache_dir=tmpdir)
        df = _make_ohlcv(5)
        key = DataCache.make_key("USDBRL=X", "1h")

        cache.set(key, df)
        removed = cache.invalidate(key)
        assert removed is True

        result = cache.get(key, interval="1h")
        assert result is None
    print("  [OK] test_cache_invalidate")


def test_cache_clear():
    """Clear deve remover todas as entradas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DataCache(cache_dir=tmpdir)
        df = _make_ohlcv(5)

        for i in range(3):
            cache.set(DataCache.make_key(f"TICKER{i}", "1d"), df)

        removed = cache.clear()
        assert removed == 3, f"Esperados 3 removidos, obteve {removed}"

        stats = cache.stats()
        assert stats["entries"] == 0
    print("  [OK] test_cache_clear")


def test_cache_make_key_deterministic():
    """make_key deve ser determinístico e sensível à ordem dos args."""
    k1 = DataCache.make_key("^BVSP", "1d", "2023-01-01", "2023-12-31")
    k2 = DataCache.make_key("^BVSP", "1d", "2023-01-01", "2023-12-31")
    k3 = DataCache.make_key("^BVSP", "1d", "2023-12-31", "2023-01-01")

    assert k1 == k2, "Mesmos args devem gerar mesma chave"
    assert k1 != k3, "Ordem diferente de args deve gerar chave diferente"
    assert len(k1) == 16, f"Chave deve ter 16 chars, obteve {len(k1)}"
    print("  [OK] test_cache_make_key_deterministic")


def test_cache_empty_df_not_stored():
    """set() com DataFrame vazio não deve criar arquivo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DataCache(cache_dir=tmpdir)
        key = DataCache.make_key("EMPTY", "1d")
        cache.set(key, pd.DataFrame())
        result = cache.get(key, interval="1d")
        assert result is None
        stats = cache.stats()
        assert stats["entries"] == 0
    print("  [OK] test_cache_empty_df_not_stored")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

_TESTS = [
    test_schema_valid_df,
    test_schema_missing_column,
    test_schema_high_less_than_low,
    test_schema_negative_volume_zeroed,
    test_schema_unordered_index,
    test_schema_check_returns_tuple,
    test_cache_set_get,
    test_cache_miss,
    test_cache_invalidate,
    test_cache_clear,
    test_cache_make_key_deterministic,
    test_cache_empty_df_not_stored,
]


def run_all() -> bool:
    """Executa todos os testes e retorna True se todos passaram."""
    passed = 0
    failed = 0

    print(f"\n{'='*60}")
    print("  Suite: data/ — schema + cache")
    print(f"{'='*60}")

    for test_fn in _TESTS:
        try:
            test_fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"  [FAIL] {test_fn.__name__}")
            traceback.print_exc()

    print(f"{'='*60}")
    print(f"  Resultado: {passed} passou(aram) / {failed} falhou(aram)")
    print(f"{'='*60}\n")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
