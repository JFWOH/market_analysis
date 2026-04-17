"""
data — Camada de dados confiável do market_analysis.

Exports públicos:
    OHLCVSchema      — validação de DataFrames OHLCV
    DataProvider     — interface abstrata
    YFinanceProvider — implementação Yahoo Finance com cache e timezone
    DataCache        — cache pickle em disco
"""

from .schema import OHLCVSchema, OHLCVValidationError
from .providers import DataProvider, YFinanceProvider
from .cache import DataCache

__all__ = [
    "OHLCVSchema",
    "OHLCVValidationError",
    "DataProvider",
    "YFinanceProvider",
    "DataCache",
]
