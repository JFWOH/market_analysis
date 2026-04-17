"""
data/schema.py — Validação de DataFrames OHLCV sem dependências externas.

Substitui pandera por verificações pandas puras, cobrindo os mesmos contratos:
  • colunas obrigatórias presentes
  • tipos numéricos
  • sem linhas todas-NaN
  • High >= Low em cada candle
  • Close/Open dentro do range [Low, High]
  • Volume >= 0
  • índice é DatetimeIndex ordenado

Uso:
    from data.schema import OHLCVSchema, OHLCVValidationError

    df = OHLCVSchema.validate(df)          # levanta OHLCVValidationError ou retorna df limpo
    ok, erros = OHLCVSchema.check(df)      # retorna (bool, lista[str]) sem levantar
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS: list[str] = ["Open", "High", "Low", "Close", "Volume"]


class OHLCVValidationError(ValueError):
    """Levantada quando um DataFrame falha na validação OHLCV."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Falha na validação OHLCV:\n" + "\n".join(f"  • {e}" for e in errors))


class OHLCVSchema:
    """Validador estático de DataFrames OHLCV."""

    # ------------------------------------------------------------------
    # Público
    # ------------------------------------------------------------------

    @staticmethod
    def validate(df: pd.DataFrame, *, drop_bad_rows: bool = True) -> pd.DataFrame:
        """Valida e opcionalmente limpa um DataFrame OHLCV.

        Args:
            df: DataFrame a ser validado.
            drop_bad_rows: Se True, remove linhas com inconsistências leves
                           (High < Low, NaN em OHLC) em vez de levantar erro.

        Returns:
            DataFrame validado (subset limpo quando drop_bad_rows=True).

        Raises:
            OHLCVValidationError: Para erros estruturais irrecuperáveis.
        """
        errors: list[str] = []

        # --- 1. Colunas obrigatórias -----------------------------------------
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            errors.append(f"Colunas ausentes: {missing}")

        if errors:
            raise OHLCVValidationError(errors)

        # --- 2. Índice DatetimeIndex -------------------------------------------
        if not isinstance(df.index, pd.DatetimeIndex):
            try:
                df = df.copy()
                df.index = pd.to_datetime(df.index)
                logger.debug("Índice convertido para DatetimeIndex")
            except Exception as exc:
                errors.append(f"Não foi possível converter índice para DatetimeIndex: {exc}")

        if errors:
            raise OHLCVValidationError(errors)

        df = df.copy()

        # --- 3. Tipos numéricos -----------------------------------------------
        for col in REQUIRED_COLUMNS:
            if not pd.api.types.is_numeric_dtype(df[col]):
                try:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                    logger.debug("Coluna '%s' coercida para numérico", col)
                except Exception:
                    errors.append(f"Coluna '{col}' não é numérica e não pode ser coercida")

        if errors:
            raise OHLCVValidationError(errors)

        # --- 4. Limpeza de linhas problemáticas --------------------------------
        ohlc_cols = ["Open", "High", "Low", "Close"]

        # Linhas totalmente NaN em OHLC
        all_nan_mask = df[ohlc_cols].isna().all(axis=1)
        n_all_nan = all_nan_mask.sum()
        if n_all_nan > 0:
            if drop_bad_rows:
                df = df[~all_nan_mask]
                logger.warning("Removidas %d linhas com OHLC totalmente NaN", n_all_nan)
            else:
                errors.append(f"{n_all_nan} linhas com todos os valores OHLC ausentes")

        # High < Low (inversão de candle)
        bad_hl = df["High"] < df["Low"]
        n_bad_hl = bad_hl.sum()
        if n_bad_hl > 0:
            if drop_bad_rows:
                df = df[~bad_hl]
                logger.warning("Removidas %d linhas com High < Low", n_bad_hl)
            else:
                errors.append(f"{n_bad_hl} candles com High < Low")

        # Volume negativo — zera em vez de remover linha
        neg_vol = df["Volume"] < 0
        n_neg_vol = neg_vol.sum()
        if n_neg_vol > 0:
            df.loc[neg_vol, "Volume"] = 0
            logger.warning("Volume negativo zerado em %d linhas", n_neg_vol)

        if errors:
            raise OHLCVValidationError(errors)

        # --- 5. Ordenar índice ------------------------------------------------
        if not df.index.is_monotonic_increasing:
            df = df.sort_index()
            logger.debug("Índice reordenado cronologicamente")

        n_rows = len(df)
        logger.info("Validação OHLCV OK — %d períodos", n_rows)
        return df

    @staticmethod
    def check(df: pd.DataFrame) -> tuple[bool, list[str]]:
        """Valida sem levantar exceção.

        Returns:
            (True, []) se válido, (False, lista_de_erros) se inválido.
        """
        try:
            OHLCVSchema.validate(df, drop_bad_rows=False)
            return True, []
        except OHLCVValidationError as exc:
            return False, exc.errors
