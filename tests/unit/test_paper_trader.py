# tests/unit/test_paper_trader.py  — Sprint-7 passo 3
"""
Testes unitários para paper_trader.py.

Cobre:
  - Position (init, current_pnl, to_dict, from_dict)
  - PaperTrader.__init__ (capital, vazio, load de JSON)
  - equity / open_pnl / equity_with_open
  - metrics (zero trades, wins/losses, PF, MDD)
  - open_position (cria, max_positions, duplicata, sem preço)
  - close_position (pnl, remove da lista, salva trades)
  - check_exits (stop_loss long/short, target long/short, sem preço)
  - update (abre posições, verifica stops)
  - reset (limpa tudo)
  - get_trades / get_positions / n_trades / n_positions
  - print_summary (não levanta exceção)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from paper_trader import PaperTrader, Position


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _tmp_paths():
    """Retorna (log_path, positions_path) em diretório temporário."""
    d = tempfile.mkdtemp()
    return os.path.join(d, "trades.json"), os.path.join(d, ".positions.json")


def _make_pt(**kw) -> PaperTrader:
    log_path, pos_path = _tmp_paths()
    return PaperTrader(
        initial_capital=100_000.0,
        log_path=log_path,
        positions_path=pos_path,
        **kw,
    )


def _buy_signal(price=50_000.0, sl=48_000.0, target=55_000.0):
    return {
        "tipo": "COMPRA",
        "preco": price,
        "stop_loss": sl,
        "preco_alvo": target,
        "data": "2024-01-15",
        "estrategia": "TestStrat",
    }


def _sell_signal(price=50_000.0, sl=52_000.0, target=45_000.0):
    return {
        "tipo": "VENDA",
        "preco": price,
        "stop_loss": sl,
        "preco_alvo": target,
        "data": "2024-01-16",
        "estrategia": "TestStrat",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Position
# ─────────────────────────────────────────────────────────────────────────────

class TestPosition:
    def test_init_fields(self):
        pos = Position("^BVSP", "long", 50_000.0, 1.0,
                       48_000.0, 55_000.0, "2024-01-01", "S1", "PT-00001")
        assert pos.ticker == "^BVSP"
        assert pos.side   == "long"
        assert pos.entry_price == 50_000.0

    def test_current_pnl_long_profit(self):
        pos = Position("T", "long", 100.0, 10.0, 95.0, 110.0, "", "", "X")
        assert pos.current_pnl(110.0) == pytest.approx(100.0)

    def test_current_pnl_long_loss(self):
        pos = Position("T", "long", 100.0, 10.0, 95.0, 110.0, "", "", "X")
        assert pos.current_pnl(90.0) == pytest.approx(-100.0)

    def test_current_pnl_short_profit(self):
        pos = Position("T", "short", 100.0, 10.0, 105.0, 90.0, "", "", "X")
        assert pos.current_pnl(90.0) == pytest.approx(100.0)

    def test_current_pnl_short_loss(self):
        pos = Position("T", "short", 100.0, 10.0, 105.0, 90.0, "", "", "X")
        assert pos.current_pnl(110.0) == pytest.approx(-100.0)

    def test_to_dict_has_all_keys(self):
        pos = Position("^BVSP", "long", 50_000.0, 2.0,
                       48_000.0, 55_000.0, "2024-01-01", "S1", "PT-00001")
        d = pos.to_dict()
        for k in ("position_id", "ticker", "side", "entry_price", "size",
                  "stop_loss", "target", "signal_date", "strategy_name", "open_ts"):
            assert k in d

    def test_from_dict_round_trip(self):
        pos = Position("^BVSP", "short", 48_000.0, 3.0,
                       50_000.0, 42_000.0, "2024-02-01", "S2", "PT-00002")
        pos2 = Position.from_dict(pos.to_dict())
        assert pos2.position_id == pos.position_id
        assert pos2.entry_price == pos.entry_price
        assert pos2.side        == pos.side


# ─────────────────────────────────────────────────────────────────────────────
# PaperTrader.__init__
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperTraderInit:
    def test_initial_capital_set(self):
        pt = _make_pt()
        assert pt.initial_capital == 100_000.0

    def test_starts_with_zero_trades(self):
        pt = _make_pt()
        assert pt.n_trades == 0

    def test_starts_with_zero_positions(self):
        pt = _make_pt()
        assert pt.n_positions == 0

    def test_equity_equals_initial_capital_on_start(self):
        pt = _make_pt()
        assert pt.equity == 100_000.0

    def test_loads_existing_trades_from_json(self):
        log_path, pos_path = _tmp_paths()
        # Cria um histórico pré-existente
        with open(log_path, "w") as f:
            json.dump([{"trade_id": "PT-00001", "pnl": 500.0}], f)
        pt = PaperTrader(initial_capital=100_000.0, log_path=log_path,
                         positions_path=pos_path)
        assert pt.n_trades == 1
        assert pt.equity == 100_500.0

    def test_loads_existing_positions(self):
        log_path, pos_path = _tmp_paths()
        pos = Position("T", "long", 100.0, 5.0, 95.0, 110.0, "2024-01-01", "S", "PT-00001")
        with open(pos_path, "w") as f:
            json.dump([pos.to_dict()], f)
        pt = PaperTrader(initial_capital=100_000.0, log_path=log_path,
                         positions_path=pos_path)
        assert pt.n_positions == 1


# ─────────────────────────────────────────────────────────────────────────────
# Equity / PnL
# ─────────────────────────────────────────────────────────────────────────────

class TestEquity:
    def test_equity_increases_with_wins(self):
        pt = _make_pt()
        pt._trades = [{"pnl": 1000.0}, {"pnl": 500.0}]
        assert pt.equity == 101_500.0

    def test_equity_decreases_with_losses(self):
        pt = _make_pt()
        pt._trades = [{"pnl": -2000.0}]
        assert pt.equity == 98_000.0

    def test_equity_with_open_uses_price_map(self):
        pt = _make_pt()
        pos = Position("T", "long", 100.0, 10.0, 90.0, 120.0, "", "", "P1")
        pt._positions = [pos]
        # Preço atual = 110, ganho = 10 * 10 = 100
        eq = pt.equity_with_open({"T": 110.0})
        assert eq == pytest.approx(100_100.0)

    def test_equity_with_open_fallback_to_entry(self):
        pt = _make_pt()
        pos = Position("T", "long", 100.0, 10.0, 90.0, 120.0, "", "", "P1")
        pt._positions = [pos]
        # sem price_map → usa entry_price → pnl = 0
        eq = pt.equity_with_open({})
        assert eq == pytest.approx(100_000.0)


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestMetrics:
    def test_metrics_zero_trades(self):
        pt = _make_pt()
        m  = pt.metrics()
        assert m["n_trades"]     == 0
        assert m["win_rate"]     == 0.0
        assert m["profit_factor"] == 0.0
        assert m["equity"]       == 100_000.0

    def test_metrics_win_rate(self):
        pt = _make_pt()
        pt._trades = [{"pnl": 100}, {"pnl": 200}, {"pnl": -50}, {"pnl": 100}]
        m = pt.metrics()
        assert m["win_rate"] == pytest.approx(0.75)

    def test_metrics_profit_factor(self):
        pt = _make_pt()
        pt._trades = [{"pnl": 300}, {"pnl": -100}]
        m = pt.metrics()
        assert m["profit_factor"] == pytest.approx(3.0)

    def test_metrics_all_wins_pf_inf(self):
        pt = _make_pt()
        pt._trades = [{"pnl": 100}, {"pnl": 200}]
        m = pt.metrics()
        assert m["profit_factor"] == float("inf")

    def test_metrics_max_drawdown_positive(self):
        pt = _make_pt()
        # Sequência: +1000, -3000, +500 → MDD after -3000
        pt._trades = [{"pnl": 1000}, {"pnl": -3000}, {"pnl": 500}]
        m = pt.metrics()
        assert m["max_drawdown"] > 0.0

    def test_metrics_total_pnl(self):
        pt = _make_pt()
        pt._trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}]
        m = pt.metrics()
        assert m["total_pnl"] == pytest.approx(250.0)

    def test_metrics_avg_win_loss(self):
        pt = _make_pt()
        pt._trades = [{"pnl": 200}, {"pnl": 300}, {"pnl": -100}, {"pnl": -50}]
        m = pt.metrics()
        assert m["avg_win"]  == pytest.approx(250.0)
        assert m["avg_loss"] == pytest.approx(-75.0)


# ─────────────────────────────────────────────────────────────────────────────
# open_position
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenPosition:
    def test_opens_long_position(self):
        pt  = _make_pt()
        pos = pt.open_position(_buy_signal(), "^BVSP")
        assert pos is not None
        assert pos.side == "long"

    def test_opens_short_position(self):
        pt  = _make_pt()
        pos = pt.open_position(_sell_signal(), "^BVSP")
        assert pos is not None
        assert pos.side == "short"

    def test_position_stored(self):
        pt = _make_pt()
        pt.open_position(_buy_signal(), "^BVSP")
        assert pt.n_positions == 1

    def test_max_positions_respected(self):
        pt = _make_pt(max_positions=2)
        # Abre 2 posições em tickers diferentes (sem duplicata)
        pt.open_position(_buy_signal(price=100.0), "T1")
        pt.open_position(_buy_signal(price=200.0), "T2")
        # Tenta abrir terceira
        pos = pt.open_position(_buy_signal(price=300.0), "T3")
        assert pos is None
        assert pt.n_positions == 2

    def test_no_duplicate_side_same_ticker(self):
        pt = _make_pt()
        pt.open_position(_buy_signal(), "^BVSP")
        pos2 = pt.open_position(_buy_signal(), "^BVSP")
        assert pos2 is None
        assert pt.n_positions == 1

    def test_zero_price_returns_none(self):
        pt  = _make_pt()
        sig = _buy_signal(price=0)
        pos = pt.open_position(sig, "T")
        assert pos is None

    def test_position_id_increments(self):
        pt = _make_pt()
        p1 = pt.open_position(_buy_signal(price=100.0), "T1")
        p2 = pt.open_position(_buy_signal(price=200.0), "T2")
        assert p1.position_id != p2.position_id

    def test_size_from_capital_and_size_pct(self):
        pt  = _make_pt(size_pct=0.10)
        pos = pt.open_position(_buy_signal(price=50_000.0), "T")
        # Aloca 10% de 100_000 = 10_000 / 50_000 = 0.2 contratos
        assert pos.size == pytest.approx(0.2)

    def test_uses_default_sl_if_missing(self):
        pt  = _make_pt()
        sig = {"tipo": "COMPRA", "preco": 100.0, "data": "2024-01-01",
               "estrategia": "S"}   # sem stop_loss
        pos = pt.open_position(sig, "T")
        assert pos is not None
        assert pos.stop_loss < 100.0   # SL default abaixo da entrada


# ─────────────────────────────────────────────────────────────────────────────
# close_position
# ─────────────────────────────────────────────────────────────────────────────

class TestClosePosition:
    def test_close_removes_from_positions(self):
        pt  = _make_pt()
        pos = pt.open_position(_buy_signal(), "^BVSP")
        pt.close_position(pos, 52_000.0, "target")
        assert pt.n_positions == 0

    def test_close_adds_to_trades(self):
        pt  = _make_pt()
        pos = pt.open_position(_buy_signal(), "^BVSP")
        pt.close_position(pos, 52_000.0, "target")
        assert pt.n_trades == 1

    def test_close_pnl_long_win(self):
        pt  = _make_pt(size_pct=0.10)
        pos = pt.open_position(_buy_signal(price=50_000.0), "T")
        trade = pt.close_position(pos, 55_000.0, "target")
        assert trade["pnl"] > 0

    def test_close_pnl_long_loss(self):
        pt  = _make_pt(size_pct=0.10)
        pos = pt.open_position(_buy_signal(price=50_000.0), "T")
        trade = pt.close_position(pos, 48_000.0, "stop_loss")
        assert trade["pnl"] < 0

    def test_close_reason_stored(self):
        pt    = _make_pt()
        pos   = pt.open_position(_buy_signal(), "T")
        trade = pt.close_position(pos, 48_000.0, "stop_loss")
        assert trade["reason"] == "stop_loss"

    def test_close_saves_to_file(self):
        log_path, pos_path = _tmp_paths()
        pt  = PaperTrader(log_path=log_path, positions_path=pos_path)
        pos = pt.open_position(_buy_signal(), "T")
        pt.close_position(pos, 52_000.0, "target")
        with open(log_path) as f:
            saved = json.load(f)
        assert len(saved) == 1


# ─────────────────────────────────────────────────────────────────────────────
# check_exits
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckExits:
    def test_long_stop_loss_triggered(self):
        pt  = _make_pt()
        pt.open_position(_buy_signal(price=100.0, sl=95.0, target=110.0), "T")
        closed = pt.check_exits({"T": 94.0})   # abaixo do SL
        assert len(closed) == 1
        assert closed[0]["reason"] == "stop_loss"

    def test_long_target_triggered(self):
        pt  = _make_pt()
        pt.open_position(_buy_signal(price=100.0, sl=95.0, target=110.0), "T")
        closed = pt.check_exits({"T": 111.0})
        assert len(closed) == 1
        assert closed[0]["reason"] == "target"

    def test_short_stop_loss_triggered(self):
        pt  = _make_pt()
        pt.open_position(_sell_signal(price=100.0, sl=105.0, target=90.0), "T")
        closed = pt.check_exits({"T": 106.0})   # acima do SL para short
        assert len(closed) == 1
        assert closed[0]["reason"] == "stop_loss"

    def test_short_target_triggered(self):
        pt  = _make_pt()
        pt.open_position(_sell_signal(price=100.0, sl=105.0, target=90.0), "T")
        closed = pt.check_exits({"T": 89.0})
        assert len(closed) == 1
        assert closed[0]["reason"] == "target"

    def test_no_exit_within_range(self):
        pt  = _make_pt()
        pt.open_position(_buy_signal(price=100.0, sl=95.0, target=110.0), "T")
        closed = pt.check_exits({"T": 103.0})   # entre SL e alvo
        assert len(closed) == 0

    def test_missing_ticker_in_price_map_skipped(self):
        pt  = _make_pt()
        pt.open_position(_buy_signal(), "^BVSP")
        closed = pt.check_exits({"OTHER": 90_000.0})
        assert len(closed) == 0


# ─────────────────────────────────────────────────────────────────────────────
# update()
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdate:
    def _mock_strategy(self, signals, ticker="T", last_price=100.0):
        import pandas as pd
        import numpy as np
        s = type("S", (), {})()
        s.ticker    = ticker
        s._prepared = True
        s.generate_signals = lambda: signals
        df = pd.DataFrame({"Close": [last_price]})
        s.data = df
        return s

    def test_update_opens_new_positions(self):
        pt = _make_pt()
        s  = self._mock_strategy([_buy_signal(price=100.0)])
        result = pt.update(s, current_price=100.0)
        assert len(result["opened"]) == 1

    def test_update_closed_trades_on_stop(self):
        pt = _make_pt()
        # Abre posição manualmente primeiro
        pt.open_position(_buy_signal(price=100.0, sl=95.0, target=110.0), "T")
        # Agora atualiza com preço abaixo do SL
        s = self._mock_strategy([], last_price=94.0)
        result = pt.update(s, current_price=94.0)
        assert len(result["closed"]) == 1

    def test_update_returns_dict_structure(self):
        pt = _make_pt()
        s  = self._mock_strategy([])
        result = pt.update(s, current_price=100.0)
        assert "opened" in result
        assert "closed" in result

    def test_update_uses_last_close_if_no_price(self):
        pt = _make_pt()
        s  = self._mock_strategy([_buy_signal(price=50.0)], last_price=50.0)
        result = pt.update(s)   # sem current_price explícito
        # Deve abrir a posição sem erro
        assert isinstance(result, dict)


# ─────────────────────────────────────────────────────────────────────────────
# reset / get_trades / get_positions
# ─────────────────────────────────────────────────────────────────────────────

class TestPersistenceAndReset:
    def test_reset_clears_trades(self):
        pt = _make_pt()
        pt._trades = [{"pnl": 100}]
        pt.reset()
        assert pt.n_trades == 0

    def test_reset_clears_positions(self):
        pt = _make_pt()
        pt.open_position(_buy_signal(), "T")
        pt.reset()
        assert pt.n_positions == 0

    def test_reset_deletes_files(self):
        log_path, pos_path = _tmp_paths()
        pt = PaperTrader(log_path=log_path, positions_path=pos_path)
        pt.open_position(_buy_signal(), "T")
        pt._save_trades()
        pt.reset()
        assert not os.path.exists(log_path)

    def test_get_trades_returns_copy(self):
        pt = _make_pt()
        pt._trades = [{"pnl": 100}]
        trades = pt.get_trades()
        trades.append({"pnl": 999})
        assert pt.n_trades == 1   # original não modificado

    def test_get_positions_returns_list_of_dicts(self):
        pt = _make_pt()
        pt.open_position(_buy_signal(), "T")
        positions = pt.get_positions()
        assert isinstance(positions, list)
        assert isinstance(positions[0], dict)

    def test_n_trades_property(self):
        pt = _make_pt()
        assert pt.n_trades == 0
        pt._trades.append({"pnl": 0})
        assert pt.n_trades == 1

    def test_n_positions_property(self):
        pt = _make_pt()
        assert pt.n_positions == 0
        pt.open_position(_buy_signal(), "T")
        assert pt.n_positions == 1


# ─────────────────────────────────────────────────────────────────────────────
# print_summary
# ─────────────────────────────────────────────────────────────────────────────

class TestPrintSummary:
    def test_print_no_exception(self, capsys):
        pt = _make_pt()
        pt.print_summary()
        out = capsys.readouterr().out
        assert "PAPER TRADER" in out

    def test_print_shows_equity(self, capsys):
        pt = _make_pt()
        pt.print_summary()
        out = capsys.readouterr().out
        assert "100" in out    # parte do valor 100_000

    def test_print_with_positions(self, capsys):
        pt = _make_pt()
        pt.open_position(_buy_signal(), "^BVSP")
        pt.print_summary({"^BVSP": 51_000.0})
        out = capsys.readouterr().out
        assert "PT-" in out

    def test_print_with_all_wins(self, capsys):
        pt = _make_pt()
        pt._trades = [{"pnl": 1000}, {"pnl": 500}]
        pt.print_summary()
        out = capsys.readouterr().out
        assert "inf" in out or "Win" in out
