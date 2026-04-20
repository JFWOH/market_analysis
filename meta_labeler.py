# meta_labeler.py — Sprint-3 passo 3: Meta-Labeling
"""
Meta-labeling (Lopez de Prado, cap. 5):

  Modelo primário  → gera sinais (direção + lado)
  Modelo secundário → aprende QUANDO o modelo primário está certo

O meta-labeler é um classificador binário que recebe como entrada as
features do mercado no momento do sinal e produz P(acerto) ∈ [0, 1].

Sinais com probabilidade abaixo de `min_prob` são descartados.
Isso reduz falsos positivos sem alterar a direção — o modelo primário
mantém controle sobre buy/sell, o meta-labeler controla o sizing.

Arquitetura:
  - Feature engineering via _build_features() — indicadores técnicos
    e regime já calculados em CombinedStrategy.prepare()
  - Modelo: RandomForestClassifier (sklearn) com class_weight='balanced'
    para lidar com desequilíbrio de classes
  - CV: PurgedKFold para evitar leakage temporal
  - Integração: filter_signals() recebe lista de sinais + DataFrame com
    indicadores e descarta os de baixa probabilidade

Uso básico:
    ml = MetaLabeler()
    ml.fit(features_df, labels_series, t1_series)
    filtered = ml.filter_signals(signals, data_df)
    proba = ml.predict_proba(features_df)
"""
from __future__ import annotations

import logging
import warnings
from typing import Any

import numpy as np
import pandas as pd

from labels import PurgedKFold, TripleBarrierLabeler, compute_label_stats

logger = logging.getLogger(__name__)

# ─── Importação condicional do sklearn ───────────────────────────────────────
try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import cross_val_score
    from sklearn.metrics import roc_auc_score, precision_score, recall_score
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False
    logger.warning("scikit-learn nao disponivel — MetaLabeler desabilitado")


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering
# ─────────────────────────────────────────────────────────────────────────────

def _compute_microstructure(data: pd.DataFrame, vol_window: int = 20) -> pd.DataFrame:
    """
    Pré-computa features de microestrutura sobre o DataFrame completo.

    Retorna DataFrame com as mesmas linhas que `data` e colunas extras:
      micro_amihud      : Amihud illiquidity ratio (|ret| / value_traded), rolling mean
      micro_vol_ratio   : Volume atual / rolling mean (volume surge)
      micro_vol_trend   : Rolling 5 / rolling 20 de volume (curto vs longo)
      micro_vwap_dist   : (Close - VWAP_rolling) / Close
      micro_range       : (High - Low) / Close  (intrabar range normalizado)
      micro_gap         : (Open - prev_Close) / prev_Close  (overnight gap)
      micro_rel_range   : (High - Low) / ATR  (range relativo à volatilidade média)
    """
    df = pd.DataFrame(index=data.index)

    close  = data["Close"]
    high   = data["High"]   if "High"   in data.columns else close
    low    = data["Low"]    if "Low"    in data.columns else close
    opn    = data["Open"]   if "Open"   in data.columns else close
    volume = data["Volume"] if "Volume" in data.columns else pd.Series(1.0, index=data.index)
    atr    = data["ATR"]    if "ATR"    in data.columns else pd.Series(np.nan, index=data.index)

    log_ret = np.log(close / close.shift(1)).abs()

    # ── Amihud illiquidity: |ret| / (vol × close) ────────────────────────
    value_traded = (volume * close).replace(0, np.nan)
    amihud_raw   = log_ret / value_traded
    df["micro_amihud"] = amihud_raw.rolling(vol_window, min_periods=5).mean().fillna(0)

    # ── Volume ratio: vol_atual / vol_média ───────────────────────────────
    vol_mean = volume.rolling(vol_window, min_periods=5).mean().replace(0, np.nan)
    df["micro_vol_ratio"]  = (volume / vol_mean).fillna(1.0).clip(0, 10)

    # ── Volume trend: média curta / média longa ───────────────────────────
    vol_short = volume.rolling(5,          min_periods=3).mean().replace(0, np.nan)
    vol_long  = volume.rolling(vol_window, min_periods=5).mean().replace(0, np.nan)
    df["micro_vol_trend"] = (vol_short / vol_long).fillna(1.0).clip(0, 5)

    # ── VWAP rolling: sum(close×vol) / sum(vol) ──────────────────────────
    cv = (close * volume).rolling(vol_window, min_periods=5).sum()
    v  = volume.rolling(vol_window, min_periods=5).sum().replace(0, np.nan)
    vwap = cv / v
    df["micro_vwap_dist"] = ((close - vwap) / close.replace(0, np.nan)).fillna(0)

    # ── Intrabar range normalizado ────────────────────────────────────────
    df["micro_range"] = ((high - low) / close.replace(0, np.nan)).fillna(0)

    # ── Gap overnight: (Open - prev_Close) / prev_Close ──────────────────
    prev_close = close.shift(1)
    df["micro_gap"] = ((opn - prev_close) / prev_close.replace(0, np.nan)).fillna(0)

    # ── Range relativo ao ATR ─────────────────────────────────────────────
    atr_safe = atr.replace(0, np.nan)
    df["micro_rel_range"] = ((high - low) / atr_safe).fillna(1.0).clip(0, 5)

    return df


def build_features(
    data: pd.DataFrame,
    timestamps: pd.DatetimeIndex | None = None,
    vol_window: int = 20,
) -> pd.DataFrame:
    """
    Extrai features de `data` para as timestamps indicadas.

    Inclui indicadores técnicos (ADX, EMA, RSI, MACD, etc.) e features de
    microestrutura (Amihud, volume ratio, VWAP dist, intrabar range, gap).
    Todas as features de preço são normalizadas pelo Close (scale-invariant).

    Parameters
    ----------
    data       : DataFrame com indicadores (output de strategy.prepare()).
    timestamps : datas para as quais extrair features. Se None, usa todas.
    vol_window : janela rolling para features de microestrutura (default 20).

    Returns
    -------
    pd.DataFrame com uma linha por timestamp e colunas de features.
    """
    if data.empty:
        return pd.DataFrame()

    if timestamps is None:
        timestamps = data.index

    # Pré-computa microestrutura em batch (eficiente — operações vetorizadas)
    micro = _compute_microstructure(data, vol_window=vol_window)

    rows = []
    for ts in timestamps:
        if ts not in data.index:
            continue
        row   = data.loc[ts]
        m_row = micro.loc[ts] if ts in micro.index else pd.Series(dtype=float)
        feat: dict[str, float] = {}

        close = float(row.get("Close", np.nan))
        if close <= 0 or np.isnan(close):
            continue

        # ── Tendência / Momentum ──────────────────────────────────────────
        adx    = row.get("ADX",      np.nan)
        di_p   = row.get("DI_Plus",  np.nan)
        di_m   = row.get("DI_Minus", np.nan)
        feat["adx"]        = _safe(adx)
        feat["di_ratio"]   = _safe(di_p - di_m)
        feat["di_sum"]     = _safe(di_p + di_m)

        # ── EMA alignment (normalizado pelo close) ────────────────────────
        for ep in [8, 21, 55]:
            ema = row.get(f"EMA_{ep}", np.nan)
            feat[f"ema{ep}_dist"] = _safe((close - ema) / close)

        feat["ema_align"] = _safe(
            (row.get("EMA_8", np.nan) - row.get("EMA_21", np.nan)) / close
        )
        feat["ema_slope"] = _safe(
            (row.get("EMA_8", np.nan) - row.get("EMA_55", np.nan)) / close
        )

        # ── Regime / Vol ──────────────────────────────────────────────────
        feat["hurst"]    = _safe(row.get("Hurst",        np.nan))
        feat["rv"]       = _safe(row.get("Realized_Vol", np.nan))
        atr = row.get("ATR", np.nan)
        feat["atr_pct"]  = _safe(atr / close)
        bb_w = row.get("BB_Width", np.nan)
        feat["bb_width"] = _safe(bb_w / close if not np.isnan(bb_w) else np.nan)

        # ── Osciladores ───────────────────────────────────────────────────
        feat["rsi"]         = _safe(row.get("RSI",         np.nan))
        feat["macd"]        = _safe(row.get("MACD",        np.nan))
        feat["macd_signal"] = _safe(row.get("MACD_Signal", np.nan))
        feat["macd_hist"]   = _safe(
            row.get("MACD", np.nan) - row.get("MACD_Signal", np.nan)
        )

        # ── Microestrutura (Sprint-5 passo 1) ────────────────────────────
        for col in ["micro_amihud", "micro_vol_ratio", "micro_vol_trend",
                    "micro_vwap_dist", "micro_range", "micro_gap",
                    "micro_rel_range"]:
            feat[col] = _safe(m_row.get(col, 0.0) if hasattr(m_row, "get") else 0.0)

        rows.append({"_ts": ts, **feat})

    if not rows:
        return pd.DataFrame()

    df_feat = pd.DataFrame(rows).set_index("_ts")
    df_feat.index.name = None
    return df_feat.astype(float)


def _safe(v: Any) -> float:
    """Converte para float, retorna 0.0 se NaN/None."""
    try:
        f = float(v)
        return 0.0 if np.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# MetaLabeler
# ─────────────────────────────────────────────────────────────────────────────

class MetaLabeler:
    """
    Meta-labeler: classifica se o sinal primário será lucrativo.

    Parameters
    ----------
    n_estimators : int      Número de árvores no RandomForest (default 200).
    max_depth    : int|None Profundidade máxima das árvores (default None).
    min_prob     : float    Limiar de probabilidade para aceitar sinal (0.5).
    n_splits     : int      Folds para PurgedKFold (default 5).
    embargo_pct  : float    % de embargo pós-teste (default 0.01).
    pt_sl        : tuple    Barreiras para labelar trades (default (2.0, 1.0)).
    max_holding  : int      Barras máximas para barreira vertical (default 20).
    random_state : int      Seed de reprodutibilidade (default 42).
    """

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int | None = None,
        min_prob: float = 0.5,
        n_splits: int = 5,
        embargo_pct: float = 0.01,
        pt_sl: tuple[float, float] = (2.0, 1.0),
        max_holding: int = 20,
        random_state: int = 42,
    ) -> None:
        if not _HAS_SKLEARN:
            raise ImportError("scikit-learn é necessário para usar MetaLabeler")

        self.min_prob     = min_prob
        self.n_splits     = n_splits
        self.embargo_pct  = embargo_pct
        self.pt_sl        = pt_sl
        self.max_holding  = max_holding
        self._fitted      = False
        self._cv_scores: list[float] = []

        self._pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf",    RandomForestClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                class_weight="balanced",
                random_state=random_state,
                n_jobs=-1,
            )),
        ])

    # ──────────────────────────────────────────────────────────────────────────
    # Treinamento
    # ──────────────────────────────────────────────────────────────────────────

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        t1: pd.Series | None = None,
        eval_cv: bool = True,
    ) -> "MetaLabeler":
        """
        Treina o meta-labeler.

        Parameters
        ----------
        X  : features (pd.DataFrame, índice = t0).
        y  : labels binários — 1 = sinal lucrativo, 0 = não lucrativo.
             Labels com NaN são descartados.
        t1 : Series com data de saída de cada amostra (para purge).
             Se None, usa o índice de X (sem label-span purge).
        eval_cv : se True, calcula ROC-AUC via PurgedKFold (mais lento).
        """
        # Remove NaN
        mask = y.notna()
        X, y = X[mask], y[mask]
        if t1 is not None:
            t1 = t1[mask]

        if len(X) < 10:
            logger.warning("MetaLabeler.fit: poucos exemplos (%d) — treinamento pulado", len(X))
            return self

        # Garante labels binários: +1 → 1, outros → 0
        y_bin = (y == 1).astype(int)

        # ── CV com purge ──────────────────────────────────────────────────
        if eval_cv and len(X) >= self.n_splits * 5:
            pkf = PurgedKFold(n_splits=self.n_splits, embargo_pct=self.embargo_pct)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    scores = cross_val_score(
                        self._pipeline, X.values, y_bin.values,
                        cv=pkf.split(X, pred_times=X.index,
                                     eval_times=t1 if t1 is not None else X.index),
                        scoring="roc_auc",
                    )
                    self._cv_scores = list(scores)
                    logger.info("MetaLabeler CV ROC-AUC: %.3f ± %.3f",
                                np.mean(scores), np.std(scores))
                except Exception as exc:
                    logger.warning("CV falhou: %s", exc)

        # ── Treino final em todos os dados ────────────────────────────────
        self._pipeline.fit(X.values, y_bin.values)
        self._feature_names = list(X.columns)
        self._fitted = True
        return self

    def fit_from_strategy(
        self,
        strategy,
        eval_cv: bool = True,
    ) -> "MetaLabeler":
        """
        Atalho: extrai features e labels diretamente de uma CombinedStrategy
        já preparada, usando TripleBarrierLabeler para rotular os sinais.

        Parameters
        ----------
        strategy : CombinedStrategy após prepare() e generate_signals().
        eval_cv  : passar para fit().
        """
        if strategy.data is None:
            raise ValueError("strategy.data é None — chame prepare() primeiro")

        data    = strategy.data
        signals = strategy.generate_signals()
        if not signals:
            logger.warning("fit_from_strategy: nenhum sinal gerado")
            return self

        # Rotula via triple-barrier
        lbl = TripleBarrierLabeler(pt_sl=self.pt_sl, max_holding=self.max_holding)
        labeled = lbl.label_signals(data["Close"], signals)
        if labeled.empty:
            return self

        # Extrai features nas datas dos sinais
        feat_ts = labeled.index[labeled.index.isin(data.index)]
        X = build_features(data, timestamps=feat_ts)
        if X.empty:
            return self

        # Alinha labels e t1 com features
        aligned = labeled.loc[labeled.index.isin(X.index)]
        y_raw   = aligned["label"]
        t1      = aligned["t1"] if "t1" in aligned.columns else None

        # Binariza: +1 → 1 (lucrativo), resto → 0
        y_bin = pd.Series(
            np.where(y_raw == 1, 1, 0),
            index=y_raw.index,
        )

        stats = compute_label_stats(labeled)
        logger.info("Label stats: %s", stats)

        return self.fit(X, y_bin, t1=t1, eval_cv=eval_cv)

    # ──────────────────────────────────────────────────────────────────────────
    # Inferência
    # ──────────────────────────────────────────────────────────────────────────

    def predict_proba(self, X: pd.DataFrame) -> pd.Series:
        """
        Retorna P(sinal lucrativo) para cada linha de X.

        Returns pd.Series com mesmo índice que X, valores em [0, 1].
        """
        if not self._fitted:
            raise RuntimeError("MetaLabeler não treinado — chame fit() primeiro")
        proba = self._pipeline.predict_proba(X.values)[:, 1]
        return pd.Series(proba, index=X.index, name="meta_prob")

    def filter_signals(
        self,
        signals: list[dict],
        data: pd.DataFrame,
    ) -> list[dict]:
        """
        Filtra sinais com P(lucrativo) < min_prob.

        Parameters
        ----------
        signals : lista de sinais de CombinedStrategy.generate_signals().
        data    : DataFrame com indicadores (strategy.data após prepare()).

        Returns
        -------
        Lista filtrada de sinais, cada um com campo extra 'meta_prob'.
        """
        if not self._fitted or not signals:
            return signals

        dates = []
        for sig in signals:
            ts = pd.Timestamp(sig["data"]) if sig.get("data") else None
            if ts is not None and ts in data.index:
                dates.append(ts)
            else:
                dates.append(None)

        valid_ts = pd.DatetimeIndex([d for d in dates if d is not None])
        X_all    = build_features(data, timestamps=valid_ts)
        if X_all.empty:
            return signals

        proba_map = self.predict_proba(X_all).to_dict()

        kept = []
        for sig, ts in zip(signals, dates):
            if ts is None:
                kept.append(sig)
                continue
            prob = proba_map.get(ts, np.nan)
            if np.isnan(prob) or prob >= self.min_prob:
                sig = {**sig, "meta_prob": float(prob) if not np.isnan(prob) else None}
                kept.append(sig)

        return kept

    # ──────────────────────────────────────────────────────────────────────────
    # Diagnóstico
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def cv_roc_auc(self) -> float | None:
        """ROC-AUC médio da CV (disponível após fit com eval_cv=True)."""
        return float(np.mean(self._cv_scores)) if self._cv_scores else None

    def feature_importance(self) -> pd.Series | None:
        """Retorna importância de features do RandomForest (se treinado)."""
        if not self._fitted:
            return None
        clf = self._pipeline.named_steps["clf"]
        return pd.Series(
            clf.feature_importances_,
            index=self._feature_names,
            name="importance",
        ).sort_values(ascending=False)

    def report(self) -> dict:
        """Retorna dict com métricas de diagnóstico do modelo."""
        return {
            "fitted":      self._fitted,
            "cv_roc_auc":  self.cv_roc_auc,
            "cv_scores":   self._cv_scores,
            "min_prob":    self.min_prob,
            "n_features":  len(self._feature_names) if self._fitted else 0,
        }
