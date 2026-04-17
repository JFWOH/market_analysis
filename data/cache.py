"""
data/cache.py — Cache pickle em disco para DataFrames OHLCV.

Estratégia:
  • Cada entrada é serializada como pickle em um subdiretório configurável.
  • A chave de cache é um hash SHA-256 dos parâmetros da requisição.
  • TTL configurável por entrada (default: 4 horas para intraday, 24h para daily+).
  • Thread-safe via lock em memória (suficiente para processo único).

Uso:
    from data.cache import DataCache
    import pandas as pd

    cache = DataCache(cache_dir="~/.market_analysis_cache")
    key = cache.make_key("^BVSP", "1d", "2023-01-01", "2023-12-31")

    df = cache.get(key)
    if df is None:
        df = fetch_from_yfinance(...)
        cache.set(key, df)
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
import threading
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# TTLs padrão em segundos por intervalo
_DEFAULT_TTL: dict[str, int] = {
    "1m":  60 * 30,       # 30 min
    "5m":  60 * 60,       # 1h
    "15m": 60 * 60 * 2,   # 2h
    "30m": 60 * 60 * 4,   # 4h
    "1h":  60 * 60 * 8,   # 8h
    "4h":  60 * 60 * 12,  # 12h
    "1d":  60 * 60 * 24,  # 24h
    "1wk": 60 * 60 * 48,  # 48h
    "1mo": 60 * 60 * 72,  # 72h
}
_DEFAULT_TTL_FALLBACK = 60 * 60 * 4  # 4h para qualquer outro intervalo


class DataCache:
    """Cache pickle com TTL para DataFrames OHLCV."""

    def __init__(
        self,
        cache_dir: str | Path = "~/.market_analysis_cache",
        default_ttl: int | None = None,
    ) -> None:
        """
        Args:
            cache_dir: Diretório raiz do cache (expandido automaticamente).
            default_ttl: TTL padrão em segundos. None = usa tabela por intervalo.
        """
        self._dir = Path(cache_dir).expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        logger.debug("DataCache inicializado em: %s", self._dir)

    # ------------------------------------------------------------------
    # Público
    # ------------------------------------------------------------------

    @staticmethod
    def make_key(ticker: str, interval: str, *extra: str) -> str:
        """Gera chave de cache determinística a partir dos parâmetros.

        Args:
            ticker:   Código do ativo (ex: "^BVSP").
            interval: Intervalo dos candles (ex: "1d").
            *extra:   Parâmetros adicionais (ex: start, end, period).

        Returns:
            String hexadecimal SHA-256 de 16 caracteres (64-bit prefix).
        """
        raw = "|".join([ticker.upper(), interval, *extra])
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, key: str, interval: str = "") -> pd.DataFrame | None:
        """Recupera DataFrame do cache se existir e não tiver expirado.

        Args:
            key:      Chave gerada por :meth:`make_key`.
            interval: Intervalo (para selecionar TTL adequado).

        Returns:
            DataFrame ou None se ausente / expirado.
        """
        path = self._path(key)
        with self._lock:
            if not path.exists():
                return None

            ttl = self._ttl(interval)
            age = time.time() - path.stat().st_mtime
            if age > ttl:
                logger.debug("Cache expirado para chave %s (age=%.0fs, ttl=%ds)", key, age, ttl)
                path.unlink(missing_ok=True)
                return None

            try:
                with path.open("rb") as fh:
                    df: pd.DataFrame = pickle.load(fh)
                logger.debug("Cache HIT: chave %s (%d linhas)", key, len(df))
                return df
            except Exception as exc:
                logger.warning("Erro ao ler cache %s: %s — descartando", path, exc)
                path.unlink(missing_ok=True)
                return None

    def set(self, key: str, df: pd.DataFrame) -> None:
        """Persiste DataFrame no cache.

        Args:
            key: Chave gerada por :meth:`make_key`.
            df:  DataFrame a ser armazenado.
        """
        if df is None or df.empty:
            logger.debug("Cache SET ignorado — DataFrame vazio para chave %s", key)
            return

        path = self._path(key)
        with self._lock:
            try:
                with path.open("wb") as fh:
                    pickle.dump(df, fh, protocol=pickle.HIGHEST_PROTOCOL)
                logger.debug("Cache SET: chave %s (%d linhas)", key, len(df))
            except Exception as exc:
                logger.warning("Erro ao salvar cache %s: %s", path, exc)

    def invalidate(self, key: str) -> bool:
        """Remove entrada específica do cache.

        Returns:
            True se a entrada existia e foi removida.
        """
        path = self._path(key)
        with self._lock:
            if path.exists():
                path.unlink()
                logger.debug("Cache invalidado: chave %s", key)
                return True
            return False

    def clear(self) -> int:
        """Remove todas as entradas do cache.

        Returns:
            Número de arquivos removidos.
        """
        removed = 0
        with self._lock:
            for entry in self._dir.glob("*.pkl"):
                entry.unlink(missing_ok=True)
                removed += 1
        logger.info("Cache limpo: %d entradas removidas", removed)
        return removed

    def stats(self) -> dict:
        """Retorna estatísticas do cache em disco."""
        files = list(self._dir.glob("*.pkl"))
        total_bytes = sum(f.stat().st_size for f in files)
        return {
            "entries": len(files),
            "total_mb": round(total_bytes / 1_048_576, 2),
            "cache_dir": str(self._dir),
        }

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.pkl"

    def _ttl(self, interval: str) -> int:
        if self._default_ttl is not None:
            return self._default_ttl
        return _DEFAULT_TTL.get(interval, _DEFAULT_TTL_FALLBACK)
