# labels.py — Sprint-3 passo 1+2: Triple-Barrier Labeling + Purged CV
"""
Duas responsabilidades:

1. Triple-Barrier Labeling (Lopez de Prado, "Advances in Financial ML", cap. 3)
   ─────────────────────────────────────────────────────────────────────────────
   Para cada evento (entrada em t0):
   - Barreira superior: preço de take-profit = entry × (1 + pt × vol)
   - Barreira inferior: preço de stop-loss   = entry × (1 − sl × vol)
   - Barreira vertical: t_final = t0 + max_holding barras
   Label: +1 se superior toca primeiro, −1 se inferior, 0 se vertical.

   Vol usada: desvio-padrão dos log-retornos numa janela rolling (vol_window).

2. Purged & Embargoing K-Fold Cross-Validation (Lopez de Prado, cap. 7)
   ─────────────────────────────────────────────────────────────────────
   Evita leakage temporal:
   - Purge: remove do fold de treino qualquer amostra cujo label-span se
     sobreponha ao período de teste.
   - Embargo: adiciona um buffer de h barras após a janela de teste antes
     de permitir amostras de treino (evita leakage via features lagged).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Generator, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# 1. Triple-Barrier Labeling
# ─────────────────────────────────────────────────────────────────────────────

class TripleBarrierLabeler:
    """
    Rotula eventos de trading via método das três barreiras.

    Parameters
    ----------
    pt_sl : tuple[float, float]
        Multiplicadores da vol diária para barreira de take-profit e stop-loss.
        Ex: (2.0, 1.0) => TP = entry × (1 + 2σ), SL = entry × (1 − 1σ).
        Use pt_sl[0]=0 para desabilitar TP, pt_sl[1]=0 para desabilitar SL.
    max_holding : int
        Número máximo de barras até a barreira vertical (default 20).
    vol_window : int
        Janela para calcular vol diária via std(log-retornos) (default 20).
    min_ret : float | None
        Se definido, descarta labels onde |retorno| < min_ret (ruído).
        Retorna NaN nesses casos — útil para meta-labeling.
    """

    def __init__(
        self,
        pt_sl: tuple[float, float] = (2.0, 1.0),
        max_holding: int = 20,
        vol_window: int = 20,
        min_ret: float | None = None,
    ) -> None:
        self.pt_sl       = pt_sl
        self.max_holding = max_holding
        self.vol_window  = vol_window
        self.min_ret     = min_ret

    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _daily_vol(close: pd.Series, window: int = 20) -> pd.Series:
        """Std dos log-retornos com janela rolling (sem anualização)."""
        log_ret = np.log(close / close.shift(1))
        return log_ret.rolling(window, min_periods=max(window // 2, 4)).std()

    def label_events(
        self,
        close: pd.Series,
        events: pd.DatetimeIndex | pd.Series | None = None,
    ) -> pd.DataFrame:
        """
        Rotula todos os eventos (ou todas as barras, se events=None).

        Parameters
        ----------
        close  : pd.Series com índice DatetimeIndex — preço de fechamento.
        events : DatetimeIndex/Series com as datas dos eventos a rotular.
                 Se None, usa todas as barras de close.

        Returns
        -------
        pd.DataFrame com colunas:
          - t0        : data de entrada
          - t1        : data de saída (quando barreira foi tocada)
          - label     : +1, −1 ou 0
          - ret       : retorno realizado (log-return da entrada à saída)
          - barrier   : qual barreira tocou ('tp', 'sl', 'vertical')
          - entry_px  : preço na entrada (close[t0])
          - exit_px   : preço na saída (close[t1])
          - duration  : barras entre t0 e t1 (inclusive)
        """
        if events is None:
            events = close.index
        elif isinstance(events, pd.Series):
            events = pd.DatetimeIndex(events)

        vol = self._daily_vol(close, self.vol_window)
        idx = close.index.tolist()
        n   = len(idx)

        rows = []
        for t0 in events:
            if t0 not in close.index:
                continue
            pos0   = close.index.get_loc(t0)
            px0    = close.iloc[pos0]
            vol0   = vol.iloc[pos0]

            if pd.isna(vol0) or vol0 <= 0:
                continue  # sem vol calculada — pula

            pt = self.pt_sl[0]
            sl = self.pt_sl[1]
            ub = px0 * (1.0 + pt * vol0) if pt > 0 else np.inf
            lb = px0 * (1.0 - sl * vol0) if sl > 0 else -np.inf

            t1        = idx[min(pos0 + self.max_holding, n - 1)]
            barrier   = "vertical"
            label     = 0

            for j in range(pos0 + 1, min(pos0 + self.max_holding + 1, n)):
                px_j = close.iloc[j]
                if px_j >= ub:
                    t1      = idx[j]
                    barrier = "tp"
                    label   = +1
                    break
                if px_j <= lb:
                    t1      = idx[j]
                    barrier = "sl"
                    label   = -1
                    break

            px1  = close.loc[t1]
            ret  = np.log(px1 / px0)
            dur  = close.index.get_loc(t1) - pos0

            # Descarta se retorno muito pequeno (ruído)
            if self.min_ret is not None and abs(ret) < self.min_ret:
                label = np.nan

            rows.append({
                "t0":       t0,
                "t1":       t1,
                "label":    label,
                "ret":      ret,
                "barrier":  barrier,
                "entry_px": px0,
                "exit_px":  px1,
                "duration": dur,
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.set_index("t0")
        return df

    def label_signals(
        self,
        close: pd.Series,
        signals: list[dict],
    ) -> pd.DataFrame:
        """
        Rotula uma lista de sinais gerados por CombinedStrategy.generate_signals().

        Sinais de Compra → label via close (busca tp/sl no sentido longo).
        Sinais de Venda  → label invertido (sinal de venda bem-sucedido = queda).

        Returns
        -------
        DataFrame com colunas de label_events() + 'tipo', 'estrategia', 'forca'.
        """
        if not signals:
            return pd.DataFrame()

        # Extrai datas únicas dos sinais
        dates_map: dict = {}
        for sig in signals:
            raw = sig.get("data")
            if raw is None:
                continue
            ts = pd.Timestamp(raw)
            if ts not in dates_map:
                dates_map[ts] = sig

        event_idx = pd.DatetimeIndex(sorted(dates_map.keys()))
        # Alinha com o índice de close (usa a barra mais próxima)
        valid_idx = event_idx[event_idx.isin(close.index)]

        labels_df = self.label_events(close, events=valid_idx)
        if labels_df.empty:
            return pd.DataFrame()

        # Anota tipo/estrategia/forca do sinal original
        sig_meta = []
        for ts in labels_df.index:
            sig = dates_map.get(ts, {})
            sig_meta.append({
                "tipo":      sig.get("tipo", ""),
                "estrategia": sig.get("estrategia", ""),
                "forca":     sig.get("forca", np.nan),
            })
        meta_df = pd.DataFrame(sig_meta, index=labels_df.index)

        # Inverte label para sinais de Venda
        # (venda bem-sucedida = preço caiu → label original -1 → flip para +1)
        result = pd.concat([labels_df, meta_df], axis=1)
        sell_mask = result["tipo"] == "Venda"
        result.loc[sell_mask, "label"] = result.loc[sell_mask, "label"] * -1

        return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. Purged & Embargoing K-Fold Cross-Validation
# ─────────────────────────────────────────────────────────────────────────────

class PurgedKFold:
    """
    K-Fold com purge e embargo para séries temporais financeiras.

    Referência: Lopez de Prado (2018), cap. 7.

    A diferença em relação ao TimeSeriesSplit padrão:
    - Purge: remove do conjunto de treino qualquer amostra cujo label-span
      [t0, t1] se sobreponha ao período de teste [test_start, test_end].
    - Embargo: após o teste, proíbe h barras de treino para evitar que
      features calculadas com lags coincidam com o período de teste.

    Parameters
    ----------
    n_splits : int   Número de folds (default 5).
    embargo_pct : float
        Proporção do total de amostras usada como embargo (default 0.01 = 1%).
        Será arredondado para max(1, int(n × embargo_pct)) barras.
    """

    def __init__(self, n_splits: int = 5, embargo_pct: float = 0.01) -> None:
        self.n_splits    = n_splits
        self.embargo_pct = embargo_pct

    def split(
        self,
        X: pd.DataFrame,
        y: pd.Series | None = None,
        pred_times: pd.Series | None = None,
        eval_times: pd.Series | None = None,
    ) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        """
        Gera pares (train_idx, test_idx) com purge e embargo.

        Parameters
        ----------
        X          : DataFrame de features (índice = t0).
        y          : Series de labels (índice = t0). Opcional.
        pred_times : Series com t0 de cada amostra (default: X.index).
        eval_times : Series com t1 de cada amostra (data de saída do label).
                     Se None, assume t1 = t0 (sem label-span overlap).
        """
        n         = len(X)
        indices   = np.arange(n)
        embargo_h = max(1, int(n * self.embargo_pct))

        # Tempos de início e fim de cada amostra
        t0_arr = pd.DatetimeIndex(pred_times) if pred_times is not None else X.index
        t1_arr = pd.DatetimeIndex(eval_times) if eval_times is not None else X.index

        fold_size = n // self.n_splits

        for fold in range(self.n_splits):
            test_start_i = fold * fold_size
            test_end_i   = (fold + 1) * fold_size if fold < self.n_splits - 1 else n
            test_idx     = indices[test_start_i:test_end_i]

            test_t_start = t0_arr[test_start_i]
            test_t_end   = t0_arr[test_end_i - 1]

            # ── Purge ──────────────────────────────────────────────────────
            # Remove amostras de treino cujo label-span (t0..t1) toca o teste
            train_mask = np.ones(n, dtype=bool)
            train_mask[test_start_i:test_end_i] = False  # remove o próprio teste

            for i in indices:
                if train_mask[i]:
                    # t1 desta amostra cai dentro do período de teste → purge
                    if t0_arr[i] <= test_t_end and t1_arr[i] >= test_t_start:
                        train_mask[i] = False

            # ── Embargo ────────────────────────────────────────────────────
            # Proíbe h barras logo APÓS o teste
            embargo_end = min(test_end_i + embargo_h, n)
            train_mask[test_end_i:embargo_end] = False

            train_idx = indices[train_mask]

            if len(train_idx) == 0 or len(test_idx) == 0:
                continue

            yield train_idx, test_idx

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits


# ─────────────────────────────────────────────────────────────────────────────
# Utilitários públicos
# ─────────────────────────────────────────────────────────────────────────────

def compute_label_stats(labels_df: pd.DataFrame) -> dict:
    """
    Retorna estatísticas de distribuição dos labels.

    Returns
    -------
    dict com keys: n_total, n_long, n_short, n_neutral, n_nan,
                   pct_long, pct_short, pct_neutral, avg_ret, avg_duration.
    """
    if labels_df.empty or "label" not in labels_df.columns:
        return {}

    lb = labels_df["label"].dropna()
    n  = len(labels_df)

    n_long    = int((lb == +1).sum())
    n_short   = int((lb == -1).sum())
    n_neutral = int((lb ==  0).sum())
    n_nan     = int(labels_df["label"].isna().sum())

    avg_ret = float(labels_df["ret"].dropna().mean()) if "ret" in labels_df.columns else float("nan")
    avg_dur = float(labels_df["duration"].dropna().mean()) if "duration" in labels_df.columns else float("nan")

    return {
        "n_total":    n,
        "n_long":     n_long,
        "n_short":    n_short,
        "n_neutral":  n_neutral,
        "n_nan":      n_nan,
        "pct_long":   n_long    / n if n > 0 else 0.0,
        "pct_short":  n_short   / n if n > 0 else 0.0,
        "pct_neutral": n_neutral / n if n > 0 else 0.0,
        "avg_ret":    avg_ret,
        "avg_duration": avg_dur,
    }
