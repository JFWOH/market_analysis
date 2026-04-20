# paper_trader.py — Sprint-7 passo 3: Paper Trading Engine
"""
PaperTrader: executa estratégias em modo paper-trading.

Características:
  - Recebe sinais da strategy em tempo real e registra execuções simuladas.
  - Persiste posições abertas e histórico de trades em JSON.
  - Calcula PnL e métricas básicas (win rate, equity, MDD).
  - Suporte a múltiplas posições simultâneas por ticker.
  - Stop-loss e alvo automáticos a partir do sinal.

Uso:
    pt = PaperTrader(initial_capital=100_000, log_path="paper_trades.json")

    # Ciclo de atualização
    while True:
        df, _ = download("^BVSP", period="1y")
        s = CombinedStrategy("^BVSP"); s.set_data(df); s.prepare()
        pt.update(s)
        pt.print_summary()
        time.sleep(300)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().isoformat()


def _load_json(path: str, default) -> Any:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("PaperTrader: falha ao carregar %s: %s", path, exc)
    return default


def _save_json(path: str, obj: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        logger.warning("PaperTrader: falha ao salvar %s: %s", path, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Position
# ─────────────────────────────────────────────────────────────────────────────

class Position:
    """Representa uma posição aberta de paper trading."""

    def __init__(
        self,
        ticker: str,
        side: str,           # "long" | "short"
        entry_price: float,
        size: float,         # unidades (contratos / ações)
        stop_loss: float,
        target: float,
        signal_date: str,
        strategy_name: str,
        position_id: str,
    ) -> None:
        self.ticker        = ticker
        self.side          = side
        self.entry_price   = entry_price
        self.size          = size
        self.stop_loss     = stop_loss
        self.target        = target
        self.signal_date   = signal_date
        self.strategy_name = strategy_name
        self.position_id   = position_id
        self.open_ts       = _now_iso()

    def current_pnl(self, current_price: float) -> float:
        """PnL não-realizado."""
        diff = current_price - self.entry_price
        if self.side == "short":
            diff = -diff
        return diff * self.size

    def to_dict(self) -> dict:
        return {
            "position_id":   self.position_id,
            "ticker":        self.ticker,
            "side":          self.side,
            "entry_price":   self.entry_price,
            "size":          self.size,
            "stop_loss":     self.stop_loss,
            "target":        self.target,
            "signal_date":   self.signal_date,
            "strategy_name": self.strategy_name,
            "open_ts":       self.open_ts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        obj = cls.__new__(cls)
        for k, v in d.items():
            setattr(obj, k, v)
        return obj


# ─────────────────────────────────────────────────────────────────────────────
# PaperTrader
# ─────────────────────────────────────────────────────────────────────────────

class PaperTrader:
    """
    Motor de paper trading persistente.

    Parameters
    ----------
    initial_capital : capital inicial simulado.
    log_path        : arquivo JSON para histórico de trades.
    positions_path  : arquivo JSON para posições abertas (persistência).
    size_pct        : fração do capital alocada por trade (default 10%).
    max_positions   : máximo de posições abertas simultaneamente (default 5).
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        log_path: str = "paper_trades.json",
        positions_path: str = ".paper_positions.json",
        size_pct: float = 0.10,
        max_positions: int = 5,
    ) -> None:
        self.initial_capital = initial_capital
        self.log_path        = log_path
        self.positions_path  = positions_path
        self.size_pct        = size_pct
        self.max_positions   = max_positions

        self._trades: list[dict]    = _load_json(log_path, [])
        raw_pos = _load_json(positions_path, [])
        self._positions: list[Position] = [Position.from_dict(p) for p in raw_pos]
        self._next_id   = len(self._trades) + 1

    # ──────────────────────────────────────────────────────────────────────────
    # Estado financeiro
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def equity(self) -> float:
        """Capital atual = inicial + PnL realizado."""
        realized = sum(t.get("pnl", 0) for t in self._trades)
        return self.initial_capital + realized

    @property
    def open_pnl(self) -> float:
        """PnL não-realizado de todas as posições abertas."""
        return sum(
            p.current_pnl(p.entry_price)   # fallback: preço de entrada
            for p in self._positions
        )

    def equity_with_open(self, price_map: dict[str, float] | None = None) -> float:
        """Capital incluindo PnL não-realizado."""
        price_map = price_map or {}
        unrealized = sum(
            p.current_pnl(price_map.get(p.ticker, p.entry_price))
            for p in self._positions
        )
        return self.equity + unrealized

    # ──────────────────────────────────────────────────────────────────────────
    # Métricas
    # ──────────────────────────────────────────────────────────────────────────

    def metrics(self) -> dict:
        """Calcula métricas básicas de performance."""
        trades = self._trades
        if not trades:
            return {
                "n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "total_pnl": 0.0, "equity": self.equity,
                "max_drawdown": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            }

        pnls   = [t.get("pnl", 0) for t in trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_rate = len(wins) / len(trades) if trades else 0.0
        gross_profit = sum(wins)
        gross_loss   = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss else (
            float("inf") if gross_profit > 0 else 0.0
        )

        # MDD via equity curve
        cap = self.initial_capital
        eq  = [cap]
        for p in pnls:
            cap += p
            eq.append(cap)
        eq_arr = [e for e in eq]
        peak = eq_arr[0]
        mdd  = 0.0
        for e in eq_arr:
            if e > peak:
                peak = e
            dd = (peak - e) / peak if peak > 0 else 0.0
            mdd = max(mdd, dd)

        return {
            "n_trades":     len(trades),
            "win_rate":     round(win_rate, 4),
            "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else float("inf"),
            "total_pnl":    round(sum(pnls), 2),
            "equity":       round(self.equity, 2),
            "max_drawdown": round(mdd, 4),
            "avg_win":      round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss":     round(sum(losses) / len(losses), 2) if losses else 0.0,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Abertura / fechamento de posições
    # ──────────────────────────────────────────────────────────────────────────

    def _position_key(self, ticker: str, side: str) -> str:
        return f"{ticker}|{side}"

    def _has_open(self, ticker: str, side: str) -> bool:
        for p in self._positions:
            if p.ticker == ticker and p.side == side:
                return True
        return False

    def open_position(self, sig: dict, ticker: str) -> Position | None:
        """
        Abre uma nova posição paper a partir de um sinal.

        Retorna a Position criada ou None se descartada.
        """
        if len(self._positions) >= self.max_positions:
            logger.info("PaperTrader: max_positions atingido (%d)", self.max_positions)
            return None

        tipo  = sig.get("tipo", "").upper()
        side  = "long" if "COMPRA" in tipo or "LONG" in tipo else "short"
        price = float(sig.get("preco", 0) or 0)
        if price <= 0:
            return None

        if self._has_open(ticker, side):
            return None   # já tem posição neste lado

        sl     = float(sig.get("stop_loss",  price * (0.97 if side == "long" else 1.03)))
        target = float(sig.get("preco_alvo", price * (1.05 if side == "long" else 0.95)))
        alloc  = self.equity * self.size_pct
        size   = alloc / price if price > 0 else 0.0

        pos = Position(
            ticker        = ticker,
            side          = side,
            entry_price   = price,
            size          = round(size, 4),
            stop_loss     = sl,
            target        = target,
            signal_date   = str(sig.get("data", ""))[:10],
            strategy_name = str(sig.get("estrategia", "")),
            position_id   = f"PT-{self._next_id:05d}",
        )
        self._next_id += 1
        self._positions.append(pos)
        self._save_positions()
        logger.info("PaperTrader: aberta %s %s @ %.2f", side, ticker, price)
        return pos

    def close_position(self, pos: Position, exit_price: float, reason: str) -> dict:
        """Fecha uma posição e registra o trade."""
        pnl = pos.current_pnl(exit_price)
        trade = {
            "trade_id":    pos.position_id,
            "ticker":      pos.ticker,
            "side":        pos.side,
            "entry_price": pos.entry_price,
            "exit_price":  exit_price,
            "size":        pos.size,
            "pnl":         round(pnl, 2),
            "reason":      reason,
            "open_ts":     pos.open_ts,
            "close_ts":    _now_iso(),
            "strategy":    pos.strategy_name,
        }
        self._trades.append(trade)
        self._positions = [p for p in self._positions if p.position_id != pos.position_id]
        self._save_trades()
        self._save_positions()
        logger.info("PaperTrader: fechada %s %s PnL=%.2f (%s)",
                    pos.side, pos.ticker, pnl, reason)
        return trade

    # ──────────────────────────────────────────────────────────────────────────
    # Check de stop/alvo em posições abertas
    # ──────────────────────────────────────────────────────────────────────────

    def check_exits(self, current_prices: dict[str, float]) -> list[dict]:
        """
        Verifica se alguma posição aberta atingiu stop-loss ou alvo.

        Parameters
        ----------
        current_prices : dict ticker → preço atual.

        Returns
        -------
        Lista de trades fechados nesta chamada.
        """
        closed = []
        for pos in list(self._positions):
            price = current_prices.get(pos.ticker)
            if price is None:
                continue
            if pos.side == "long":
                if price <= pos.stop_loss:
                    closed.append(self.close_position(pos, pos.stop_loss, "stop_loss"))
                elif price >= pos.target:
                    closed.append(self.close_position(pos, pos.target, "target"))
            else:   # short
                if price >= pos.stop_loss:
                    closed.append(self.close_position(pos, pos.stop_loss, "stop_loss"))
                elif price <= pos.target:
                    closed.append(self.close_position(pos, pos.target, "target"))
        return closed

    # ──────────────────────────────────────────────────────────────────────────
    # Interface principal
    # ──────────────────────────────────────────────────────────────────────────

    def update(self, strategy, current_price: float | None = None) -> dict:
        """
        Ciclo de atualização: abre novas posições + verifica exits.

        Parameters
        ----------
        strategy      : instância de strategy com dados atualizados.
        current_price : preço atual (opcional; usa último close se None).

        Returns
        -------
        dict com "opened" e "closed" desta atualização.
        """
        # Preço atual
        if current_price is None and strategy.data is not None:
            current_price = float(strategy.data["Close"].iloc[-1])

        # Verifica stops/alvos com o preço atual
        closed: list[dict] = []
        if current_price is not None:
            closed = self.check_exits({strategy.ticker: current_price})

        # Gera sinais e abre novas posições
        if not strategy._prepared:
            strategy.prepare()
        signals = strategy.generate_signals()

        opened: list[Position] = []
        for sig in signals:
            pos = self.open_position(sig, strategy.ticker)
            if pos:
                opened.append(pos)

        return {
            "opened": [p.to_dict() for p in opened],
            "closed": closed,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Persistência
    # ──────────────────────────────────────────────────────────────────────────

    def _save_trades(self) -> None:
        _save_json(self.log_path, self._trades)

    def _save_positions(self) -> None:
        _save_json(self.positions_path, [p.to_dict() for p in self._positions])

    def reset(self) -> None:
        """Limpa todo o histórico e posições abertas."""
        self._trades     = []
        self._positions  = []
        self._next_id    = 1
        for path in (self.log_path, self.positions_path):
            if os.path.exists(path):
                os.remove(path)

    # ──────────────────────────────────────────────────────────────────────────
    # Display
    # ──────────────────────────────────────────────────────────────────────────

    def print_summary(self, price_map: dict[str, float] | None = None) -> None:
        """Imprime resumo do estado atual."""
        W   = 60
        sep = "+" + "-" * W + "+"
        m   = self.metrics()

        print(sep)
        print(f"| {'PAPER TRADER SUMMARY':<{W-1}}|")
        print(sep)
        print(f"|  Equity        : R$ {m['equity']:>12,.2f}                  |")
        print(f"|  N trades      : {m['n_trades']:>5}                               |")
        print(f"|  Win rate      : {m['win_rate']*100:>6.1f}%                            |")
        pf = m['profit_factor']
        pf_s = f"{pf:.3f}" if pf != float("inf") else "inf"
        print(f"|  Profit Factor : {pf_s:>8}                           |")
        print(f"|  Total PnL     : R$ {m['total_pnl']:>+12,.2f}                 |")
        print(f"|  Max Drawdown  : {m['max_drawdown']*100:>6.2f}%                            |")
        print(sep)

        if self._positions:
            print(f"| {'Posicoes abertas':<{W-1}}|")
            for p in self._positions:
                eq_now = self.equity_with_open(price_map)
                print(f"|  {p.position_id} {p.side:5} {p.ticker} "
                      f"@ {p.entry_price:,.2f} SL={p.stop_loss:,.2f} "
                      f"TGT={p.target:,.2f}  |")
            print(sep)

    # ──────────────────────────────────────────────────────────────────────────
    # Acesso ao histórico
    # ──────────────────────────────────────────────────────────────────────────

    def get_trades(self) -> list[dict]:
        """Retorna cópia do histórico de trades."""
        return list(self._trades)

    def get_positions(self) -> list[dict]:
        """Retorna posições abertas como lista de dicts."""
        return [p.to_dict() for p in self._positions]

    @property
    def n_trades(self) -> int:
        return len(self._trades)

    @property
    def n_positions(self) -> int:
        return len(self._positions)
