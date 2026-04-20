# alert_manager.py — Sprint-6 passo 2: Sistema de Alertas
"""
AlertManager: monitora sinais novos e emite alertas via múltiplos canais.

Canais suportados:
  - Log JSON-lines  : cada alerta é uma linha JSON em alerts.jsonl
  - Console         : print formatado no terminal (sempre ativo)
  - Webhook HTTP    : POST JSON para URL configurável (Slack, Discord, n8n…)
  - Email SMTP      : opcional; requer configuração de servidor

Deduplicação:
  Sinais já alertados são rastreados por chave (ticker, data, tipo).
  O estado é persistido em .alerts_sent.json para sobreviver a reinicios.

Uso típico:
    am = AlertManager(ticker="^BVSP", log_path="alerts.jsonl")
    am.check(strategy)        # verifica sinais novos e alerta

Uso em loop:
    while True:
        df, _ = download("^BVSP", ...)
        s = CombinedStrategy("^BVSP"); s.set_data(df); s.prepare()
        am.check(s)
        time.sleep(300)
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import time
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# AlertManager
# ─────────────────────────────────────────────────────────────────────────────

class AlertManager:
    """
    Monitora sinais gerados pela strategy e emite alertas para novos sinais.

    Parameters
    ----------
    ticker      : ticker monitorado (para contexto nos alertas).
    log_path    : caminho do arquivo JSON-lines (default "alerts.jsonl").
    sent_path   : caminho para persistir sinais já alertados (default ".alerts_sent.json").
    min_forca   : ignora sinais com forca < min_forca (default 0 = todos).
    min_meta_prob : ignora sinais com meta_prob < min_meta_prob (default 0 = todos).
    webhook_url : URL para webhook HTTP (opcional).
    email_cfg   : dict com keys: host, port, user, password, to (opcional).
    console     : se True, imprime alertas no terminal (default True).
    """

    def __init__(
        self,
        ticker: str = "^BVSP",
        log_path: str = "alerts.jsonl",
        sent_path: str = ".alerts_sent.json",
        min_forca: int = 0,
        min_meta_prob: float = 0.0,
        webhook_url: str | None = None,
        email_cfg: dict | None = None,
        console: bool = True,
    ) -> None:
        self.ticker        = ticker
        self.log_path      = log_path
        self.sent_path     = sent_path
        self.min_forca     = min_forca
        self.min_meta_prob = min_meta_prob
        self.webhook_url   = webhook_url
        self.email_cfg     = email_cfg
        self.console       = console

        self._sent: set[str] = self._load_sent()

    # ──────────────────────────────────────────────────────────────────────────
    # Chave de deduplicação
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _key(sig: dict) -> str:
        ts   = str(sig.get("data", ""))[:10]
        tipo = sig.get("tipo", "")
        estr = sig.get("estrategia", "")
        return f"{ts}|{tipo}|{estr}"

    # ──────────────────────────────────────────────────────────────────────────
    # Persistência do estado
    # ──────────────────────────────────────────────────────────────────────────

    def _load_sent(self) -> set[str]:
        if os.path.exists(self.sent_path):
            try:
                with open(self.sent_path, encoding="utf-8") as f:
                    return set(json.load(f))
            except Exception:
                pass
        return set()

    def _save_sent(self) -> None:
        try:
            with open(self.sent_path, "w", encoding="utf-8") as f:
                json.dump(list(self._sent), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("AlertManager._save_sent falhou: %s", exc)

    # ──────────────────────────────────────────────────────────────────────────
    # Filtragem
    # ──────────────────────────────────────────────────────────────────────────

    def _should_alert(self, sig: dict) -> bool:
        key  = self._key(sig)
        if key in self._sent:
            return False
        if sig.get("forca", 0) < self.min_forca:
            return False
        mp = sig.get("meta_prob", None)
        if mp is not None and mp < self.min_meta_prob:
            return False
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # Canais de saída
    # ──────────────────────────────────────────────────────────────────────────

    def _format_alert(self, sig: dict, data_last: Any = None) -> str:
        ts    = str(sig.get("data", ""))[:10]
        tipo  = sig.get("tipo", "?")
        estr  = sig.get("estrategia", "")
        preco = sig.get("preco",       0) or 0
        sl    = sig.get("stop_loss",   0) or 0
        alvo  = sig.get("preco_alvo",  0) or 0
        forca = sig.get("forca",       0) or 0
        mp    = sig.get("meta_prob",   None)
        mp_s  = f"  meta_prob={mp:.2f}" if mp is not None else ""

        risco = abs(preco - sl) / preco * 100 if preco else 0
        ganho = abs(alvo  - preco) / preco * 100 if preco else 0

        return (
            f"[ALERTA] {self.ticker} | {tipo} | {ts}\n"
            f"  Estrategia : {estr}\n"
            f"  Entrada    : {preco:,.2f}   Forca: {forca}{mp_s}\n"
            f"  Stop Loss  : {sl:,.2f}  (-{risco:.2f}%)\n"
            f"  Alvo       : {alvo:,.2f}  (+{ganho:.2f}%)\n"
            f"  R:R        : 1:{ganho/risco:.1f}" if risco > 0 else
            f"[ALERTA] {self.ticker} | {tipo} | {ts} | Entrada: {preco:,.2f}"
        )

    def _emit_console(self, msg: str) -> None:
        if self.console:
            print(msg)

    def _emit_log(self, sig: dict) -> None:
        record = {
            "ts_alerta":   datetime.now().isoformat(),
            "ticker":      self.ticker,
            **{k: (str(v) if isinstance(v, pd.Timestamp) else v)
               for k, v in sig.items()},
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("AlertManager._emit_log falhou: %s", exc)

    def _emit_webhook(self, sig: dict, msg: str) -> None:
        if not self.webhook_url:
            return
        payload = json.dumps({
            "text":    msg,
            "ticker":  self.ticker,
            "signal":  {k: (str(v) if isinstance(v, pd.Timestamp) else v)
                        for k, v in sig.items()},
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
            logger.info("Webhook enviado: status=%d", status)
        except Exception as exc:
            logger.warning("AlertManager._emit_webhook falhou: %s", exc)

    def _emit_email(self, sig: dict, msg: str) -> None:
        cfg = self.email_cfg
        if not cfg:
            return
        try:
            body = MIMEText(msg, "plain", "utf-8")
            body["Subject"] = f"[Alerta] {self.ticker} {sig.get('tipo','')} {str(sig.get('data',''))[:10]}"
            body["From"]    = cfg.get("user", "")
            body["To"]      = cfg.get("to", "")
            with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587))) as smtp:
                smtp.starttls()
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(body)
            logger.info("Email enviado para %s", cfg["to"])
        except Exception as exc:
            logger.warning("AlertManager._emit_email falhou: %s", exc)

    # ──────────────────────────────────────────────────────────────────────────
    # Interface pública
    # ──────────────────────────────────────────────────────────────────────────

    def check(self, strategy) -> list[dict]:
        """
        Verifica sinais da strategy e emite alertas para os novos.

        Chama strategy.generate_signals() internamente.
        Atualiza o estado de sinais já enviados.

        Returns
        -------
        Lista de sinais novos que foram alertados nesta chamada.
        """
        if strategy.data is None:
            return []

        if not strategy._prepared:
            strategy.prepare()

        signals  = strategy.generate_signals()
        alerted  = []

        for sig in signals:
            if not self._should_alert(sig):
                continue
            msg = self._format_alert(sig)
            self._emit_console(msg)
            self._emit_log(sig)
            self._emit_webhook(sig, msg)
            self._emit_email(sig, msg)
            self._sent.add(self._key(sig))
            alerted.append(sig)

        if alerted:
            self._save_sent()

        logger.info("AlertManager.check: %d sinais, %d novos alertas",
                    len(signals), len(alerted))
        return alerted

    def reset(self) -> None:
        """Limpa o histórico de sinais já enviados (força re-envio na próxima chamada)."""
        self._sent.clear()
        if os.path.exists(self.sent_path):
            os.remove(self.sent_path)

    def load_log(self) -> list[dict]:
        """Lê e retorna todos os alertas do arquivo JSON-lines."""
        if not os.path.exists(self.log_path):
            return []
        records = []
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records

    @property
    def n_sent(self) -> int:
        """Número de sinais únicos já alertados nesta sessão + histórico."""
        return len(self._sent)
