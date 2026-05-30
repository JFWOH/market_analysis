# Sprint 28 — Integração com Motor Real (Modo Replay Histórico)

**Bloco**: III (Interface Gráfica)
**Duração estimada**: 5-7 dias úteis
**Pré-requisito**: Sprint 27 fechado (`v0.27.0`)
**Status**: pending
**Tag ao fechar**: `v0.28.0`

---

## 1. Contexto

O Sprint 27 estabeleceu a arquitetura com `MockRunner` gerando eventos aleatórios. Este sprint substitui o mock pelo **motor real** em modo Replay Histórico: o backtester roda barra-a-barra sobre uma janela do passado, publicando eventos a cada bar processada.

Por que Replay primeiro (e não Paper Live):
- Replay é **determinístico** — facilita debugging e testes.
- Replay tem **dados completos** — sem latência de fonte externa.
- Replay produz **valor imediato** para o usuário (validar configs antes de qualquer dinheiro real).
- Replay testa todo o pipeline UI ↔ adapter ↔ motor sem o ruído da rede.

---

## 2. Objetivo

Implementar `ReplayRunner` que envolve `backtester.py`, com controle de velocidade na UI e replay determinístico de cenários históricos. A métrica final deve ser **bit-a-bit idêntica** ao que o backtester produz via CLI.

---

## 3. Entregáveis

### E1 — `gui/adapter.py` expandido

```python
"""
Adapter — ÚNICA porta de entrada entre UI e motor.
gui/ nunca importa diretamente de market_analysis/.
"""
from typing import Any
from pathlib import Path
import pandas as pd


def load_data_cached(
    ticker: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval: str = "1d",
) -> pd.DataFrame:
    """Wrapper sobre data_provider + cache."""
    from data_provider import get_data
    from scripts.fetch_real_data import fetch_with_cache
    return fetch_with_cache(ticker, start, end, interval)


def build_strategy(config: dict) -> Any:
    """Constrói CombinedStrategy a partir de config dict."""
    from strategy import CombinedStrategy
    params = config.get("strategy_params", {})
    return CombinedStrategy(**params)


def build_risk_guard(config: dict) -> Any:
    """Constrói RiskGuard se habilitado em config."""
    from risk_guard import RiskGuard, RiskLimits
    if not config.get("use_risk_guard", True):
        return None
    limits_dict = config.get("risk_limits", {})
    return RiskGuard(RiskLimits(**limits_dict))


def list_available_presets() -> list[dict]:
    """Lista presets do banco."""
    from db.repository import Repository
    repo = Repository()
    return repo.list_presets()


def get_preset_params(name: str) -> dict:
    """Carrega parâmetros de um preset."""
    from db.repository import Repository
    repo = Repository()
    preset = repo.get_preset(name)
    if not preset:
        raise ValueError(f"Preset não encontrado: {name}")
    return preset["config_json"]


def validate_ticker(ticker: str) -> tuple[bool, str]:
    """Valida ticker via yfinance pré-disparo. Retorna (válido, mensagem)."""
    import yfinance as yf
    try:
        info = yf.Ticker(ticker).info
        if "symbol" in info or "shortName" in info:
            return True, "OK"
        return False, f"Ticker '{ticker}' não retornou dados válidos"
    except Exception as e:
        return False, f"Erro ao validar: {e}"
```

### E2 — `gui/runners/replay.py`

```python
import time
import pandas as pd
from gui.runners.base import BaseRunner
from gui.adapter import (
    load_data_cached,
    build_strategy,
    build_risk_guard,
)


class ReplayRunner(BaseRunner):
    """
    Runner para Replay Histórico.
    
    Consome backtester barra-a-barra, emitindo eventos a cada uma.
    Controla velocidade via sleep_ms entre barras.
    """
    
    SPEED_MULTIPLIERS = {
        "1x": 1.0,
        "10x": 0.1,
        "100x": 0.01,
        "1000x": 0.001,
        "instant": 0.0,
    }
    
    def run(self) -> None:
        # ============ Setup ============
        ticker = self.config["ticker"]
        start = pd.Timestamp(self.config["start_date"])
        end = pd.Timestamp(self.config["end_date"])
        interval = self.config.get("interval", "1d")
        speed = self.config.get("speed", "1x")
        sleep_per_bar = self.SPEED_MULTIPLIERS.get(speed, 1.0)
        initial_capital = self.config.get("initial_capital", 100_000.0)
        
        self.emit("SESSION_STARTED", {
            "ticker": ticker,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "interval": interval,
            "speed": speed,
            "initial_capital": initial_capital,
        })
        
        # ============ Load data ============
        try:
            data = load_data_cached(ticker, start, end, interval)
        except Exception as e:
            self.emit("SESSION_ENDED", {
                "status": "error",
                "summary": {"error": f"Falha ao carregar dados: {e}"},
            })
            return
        
        if len(data) < 100:
            self.emit("SESSION_ENDED", {
                "status": "error",
                "summary": {"error": f"Dados insuficientes: {len(data)} barras"},
            })
            return
        
        # Pre-computar indicadores
        from indicators import compute_all
        data = compute_all(data)
        
        # ============ Build engine ============
        strategy = build_strategy(self.config)
        risk_guard = build_risk_guard(self.config)
        
        # Estado de simulação (mantido localmente; backtester é refatorado para suportar step)
        from backtester import Backtester
        bt = Backtester(
            initial_capital=initial_capital,
            commission=self.config.get("commission", 0.001),
            slippage=self.config.get("slippage", 0.001),
            risk_guard=risk_guard,
        )
        
        n_bars = len(data)
        emit_every_n_bars = max(1, n_bars // 200)  # ~200 atualizações para a UI
        
        # ============ Loop barra-a-barra ============
        for i in range(50, n_bars):  # warm-up de 50 barras para indicadores
            self.check_commands()
            
            if self._aborted:
                self._finalize(bt, status="aborted", bars_processed=i)
                return
            
            while self._paused:
                time.sleep(0.1)
                self.check_commands()
                if self._aborted:
                    self._finalize(bt, status="aborted", bars_processed=i)
                    return
            
            current_bar = data.iloc[:i+1]
            current_ts = data.index[i]
            
            # 1. Estratégia gera sinais
            signals = strategy.gerar_sinais(current_bar, current_ts)
            for sig in signals:
                self.emit("SIGNAL_GENERATED", {
                    "ticker": ticker,
                    "tipo": sig["tipo"],
                    "preco": float(sig["preco"]),
                    "stop_loss": float(sig.get("stop_loss", 0)),
                    "estrategia": sig.get("estrategia", "unknown"),
                    "context": {
                        "ADX": float(current_bar["ADX"].iloc[-1]) if "ADX" in current_bar else None,
                        "Hurst": float(current_bar["Hurst"].iloc[-1]) if "Hurst" in current_bar else None,
                    },
                })
            
            # 2. Backtester processa
            bar_result = bt.step(current_bar, signals, current_ts)
            
            # 3. Emitir eventos de trade
            for trade_evt in bar_result.get("trade_events", []):
                self.emit(trade_evt["type"], trade_evt["payload"])
            
            # 4. Periodic metrics update
            if i % emit_every_n_bars == 0:
                self._emit_metrics(bt, i, n_bars)
            
            # 5. Speed control
            if sleep_per_bar > 0:
                time.sleep(sleep_per_bar)
        
        # ============ Finalização ============
        self._finalize(bt, status="completed", bars_processed=n_bars)
    
    def _emit_metrics(self, bt, bar_index, n_bars):
        metrics = bt.compute_running_metrics()
        self.emit("METRICS_UPDATE", {
            "bar_index": bar_index,
            "progress_pct": round(100 * bar_index / n_bars, 2),
            "equity": float(metrics["equity"]),
            "pnl": float(metrics["realized_pnl"]),
            "drawdown_total_pct": float(metrics["drawdown_total_pct"]),
            "drawdown_capital_at_risk_pct": float(metrics["drawdown_capital_at_risk_pct"]),
            "n_trades": metrics["n_trades"],
            "win_rate": float(metrics["win_rate"]) if metrics["n_trades"] > 0 else None,
            "sharpe": float(metrics["sharpe"]) if metrics["n_trades"] > 5 else None,
        })
    
    def _finalize(self, bt, status, bars_processed):
        summary = bt.compute_final_metrics()
        self.emit("SESSION_ENDED", {
            "status": status,
            "summary": summary,
            "bars_processed": bars_processed,
        })
```

### E3 — Refatoração do `backtester.py` para suportar step-by-step

Backtester atual provavelmente processa série inteira em uma chamada. Precisa expor:

```python
class Backtester:
    def step(
        self,
        current_data: pd.DataFrame,
        signals: list[dict],
        current_ts: pd.Timestamp,
    ) -> dict:
        """
        Processa uma barra: aplica exits, abre novas posições baseado em signals.
        
        Returns
        -------
        dict com:
            - trade_events: lista de eventos (TRADE_OPENED, TRADE_CLOSED, etc.)
            - equity: float atual
        """
    
    def compute_running_metrics(self) -> dict:
        """Métricas parciais baseadas em estado atual."""
    
    def compute_final_metrics(self) -> dict:
        """Métricas finais (mesma estrutura do run() atual)."""
```

**Importante**: o método `run(data)` existente deve ser preservado para retrocompatibilidade. Internamente, pode chamar `step` em loop.

### E4 — Atualização de `gui/routes/config.py`

Formulário expandido para configurar replay real:

```python
@bp.route("/sessions", methods=["POST"])
def start_session():
    data = request.form.to_dict()
    
    mode = data.get("mode", "replay")
    
    if mode == "replay":
        # Validação de ticker
        from gui.adapter import validate_ticker
        valid, msg = validate_ticker(data["ticker"])
        if not valid:
            return render_template(
                "config.html.j2",
                error=msg,
                form_data=data,
            ), 400
        
        config = {
            "ticker": data["ticker"],
            "start_date": data["start_date"],
            "end_date": data["end_date"],
            "interval": data.get("interval", "1d"),
            "speed": data.get("speed", "1x"),
            "initial_capital": float(data.get("initial_capital", 100_000)),
            "commission": float(data.get("commission", 0.001)),
            "slippage": float(data.get("slippage", 0.001)),
            "preset_name": data.get("preset_name", "sprint_13_reference"),
            # carrega params do preset
        }
        
        from gui.adapter import get_preset_params
        if config["preset_name"]:
            config["strategy_params"] = get_preset_params(config["preset_name"])
        
        from gui.runners.replay import ReplayRunner
        runner_cls = ReplayRunner
    
    elif mode == "mock":
        # mantém MockRunner para tests/dev
        from gui.runners.mock import MockRunner
        config = {...}
        runner_cls = MockRunner
    
    mgr = current_app.config["SESSION_MANAGER"]
    session_id = mgr.start_session(mode="replay", config=config, runner_cls=runner_cls)
    
    return redirect(url_for("live.live_page", session_id=session_id))
```

### E5 — Atualização do template `config.html.j2`

Formulário completo:
- Modo (Mock / Replay / Live disabled até Sprint 32)
- Ticker (com validação inline via fetch ao endpoint /api/validate_ticker)
- Datas (DatePicker simples)
- Intervalo (1d, 1h, etc.)
- Velocidade (1x, 10x, 100x, 1000x, instant)
- Capital inicial, slippage, comissão
- Preset (dropdown carregado do banco)
- Botão "Salvar como preset" (envia para `/api/presets` POST)

Validação inline com HTMX:
```html
<input name="ticker" 
       hx-post="/api/validate_ticker"
       hx-trigger="blur"
       hx-target="#ticker_status">
<span id="ticker_status"></span>
```

### E6 — Endpoint `/api/validate_ticker`

```python
@bp.route("/api/validate_ticker", methods=["POST"])
def validate_ticker_endpoint():
    ticker = request.form.get("ticker", "")
    from gui.adapter import validate_ticker
    valid, msg = validate_ticker(ticker)
    color = "green" if valid else "red"
    return f'<span style="color: {color};">{msg}</span>'
```

### E7 — Testes

**`tests/integration/test_replay_e2e.py`** (mínimo 6 casos):

1. **Replay determinístico**: rodar mesmo cenário 2x produz métricas finais idênticas.
2. **Equivalência com CLI**: replay via UI produz métricas idênticas a `backtester.run(data)` direto.
3. **GFC 2008**: replay de 2008-06 a 2009-06 produz MDD esperado.
4. **Speed control**: `speed=1000x` completa em ≤ 30s; `speed=1x` demora proporcionalmente mais (sanity).
5. **Abort no meio**: aborto na barra 100 de 200 produz `bars_processed=100` no summary.
6. **Pause-resume**: durante pause, nenhum BAR_PROCESSED é emitido.

**`tests/unit/test_backtester_step.py`** (mínimo 5 casos):

1. **Equivalência step-vs-run**: `step` chamado em loop produz mesmo resultado que `run`.
2. **Métricas parciais corretas**: `compute_running_metrics` em meio do loop.
3. **Métricas finais idênticas** ao método antigo.
4. **Compute_all** chamado uma vez (não recalcula a cada step).
5. **Edge case**: step sem signals e sem positions abertas é no-op.

### E8 — Sanity check de equivalência

Script `scripts/validate_replay_equivalence.py`:

```python
"""
Roda backtester via CLI e via UI replay, compara métricas.
"""
def main():
    # CLI
    cli_result = backtester.run(data, params)
    
    # UI replay (simulado, não real UI)
    ui_result = run_replay_simulation(data, params)
    
    assert cli_result["total_pnl"] == pytest.approx(ui_result["total_pnl"])
    assert cli_result["sharpe"] == pytest.approx(ui_result["sharpe"])
    assert cli_result["max_drawdown"] == pytest.approx(ui_result["max_drawdown"])
    print("✓ Equivalência confirmada")
```

---

## 4. Critério de Aceitação

- [ ] Suite completa passa (incluindo 11 novos testes)
- [ ] Replay de janela conhecida produz métricas **bit-a-bit idênticas** ao backtester via CLI
- [ ] Speed control 1x, 10x, 100x, 1000x, instant funcionam
- [ ] Validação de ticker funciona inline na UI
- [ ] Presets carregados do banco aparecem no dropdown
- [ ] GFC 2008 sobre ^BVSP produz MDD-capital-at-risk consistente com o documentado no Sprint 18
- [ ] Aborto graceful em qualquer ponto da simulação
- [ ] Sanity script `validate_replay_equivalence.py` passa

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Refatoração step-by-step do backtester quebra testes | Alta | Preservar `run()` chamando `step` em loop; testes existentes não mudam |
| Diferença sutil entre CLI e UI (floating point, ordem) | Média | Sanity script obrigatório; `pytest.approx` com tolerância apertada |
| yfinance lento para download de janela longa | Média | Cache agressivo já existe; tratar timeout |
| Speed instant produz queue overflow | Média | Throttling de emit_metrics (a cada N barras) |
| Memory leak em sessões longas | Baixa-Média | Profilar com sessão de 10 anos diários |

---

## 6. Notas para o Claude Code

- **Não recomputar indicadores a cada step**: chamar `compute_all` uma vez antes do loop.
- **Slicing de DataFrame** dentro do loop é O(n) — para sessões muito longas, considerar passar `data` completo e `current_index` em vez de `data.iloc[:i+1]`.
- **`backtester.step` precisa ser idempotente**: chamar `step` duas vezes na mesma barra sem signals novos não deve duplicar trades.
- **Equivalência floating point**: backtester e replay devem usar **exatamente** os mesmos cálculos. Diferenças surgem se ordem de operações muda.
- **Warm-up de 50 barras**: necessário para indicadores. Documentar e tornar configurável (`warm_up_bars`).
- **Emit metrics a cada N barras**: não a cada barra (queue overflow + UI travada). N = max(1, n_bars // 200).

---

## 7. Comandos de validação

```bash
pytest tests/integration/test_replay_e2e.py -v
pytest tests/unit/test_backtester_step.py -v

# Sanity script
python scripts/validate_replay_equivalence.py

# Replay manual via UI
python -m gui.server
# Browser: configurar replay 2008-06 a 2009-06 sobre ^BVSP, velocidade instant
# Verificar métricas finais no relatório
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — adapter.py expandido | 0.5 dia |
| E2 — ReplayRunner | 1-1.5 dias |
| E3 — backtester step refactor | 1-1.5 dias |
| E4 — routes update | 0.5 dia |
| E5 — template config completo | 0.5 dia |
| E6 — endpoint validate_ticker | 0.25 dia |
| E7 — testes (11 casos) | 1.5-2 dias |
| E8 — sanity script | 0.25 dia |
| Buffer | 0.5 dia |
| **Total** | **5-7 dias** |
