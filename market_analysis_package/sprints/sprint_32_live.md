# Sprint 32 — Paper Trading Live (Polling yfinance em Pregão)

**Bloco**: III (Interface Gráfica)
**Duração estimada**: 10-14 dias úteis
**Pré-requisito**: Sprint 31 fechado (`v0.31.0`)
**Status**: pending
**Tag ao fechar**: `v0.32.0`

---

## 1. Contexto

Os Sprints 27-31 entregam um sistema de replay histórico completo e auditável. Este sprint adiciona a capacidade de operar **com dados atualizados durante o pregão**, em modo paper (sem ordens reais).

Por que vem depois do Replay (e não antes):
- **Replay já validou** a arquitetura completa de eventos, persistência e UI.
- **Live adiciona apenas** a fonte de dados em tempo real — todo o resto é reutilizado.
- **Live tem armadilhas próprias** (latência, dados ausentes, agendamento de pregão) que se beneficiam de uma fundação estável.

Importante reconhecer o que **NÃO** este sprint entrega:
- ❌ Integração com corretora real (FIX, OMS) — fora de escopo
- ❌ Dados tick-a-tick — yfinance não oferece; intraday em 1m é o melhor disponível na fonte gratuita
- ❌ Garantia de execução em open/close — apenas simulação fair

O que entrega:
- ✅ Atualização periódica via yfinance durante horário de pregão
- ✅ Processamento de signals em tempo real
- ✅ Persistência idempotente (reconexão não duplica trades)
- ✅ Indicador visual de saúde da conexão e latência
- ✅ Suspensão fora de pregão

---

## 2. Objetivo

Implementar `LiveRunner` análogo ao `ReplayRunner` mas consumindo dados em tempo real, com tratamento adequado de horário de pregão, dados ausentes, e idempotência.

---

## 3. Entregáveis

### E1 — Scheduler de mercado `market_schedule.py`

```python
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from enum import Enum


class MarketStatus(str, Enum):
    OPEN = "open"
    PRE_OPEN = "pre_open"      # leilão de abertura
    AFTER_HOURS = "after_hours" # leilão de fechamento
    CLOSED = "closed"
    HOLIDAY = "holiday"
    WEEKEND = "weekend"


@dataclass(frozen=True)
class MarketSession:
    name: str
    timezone: str
    open_time: time
    close_time: time
    pre_open_minutes: int = 15
    after_hours_minutes: int = 30
    
    # Para overrides anuais simples (não cobre todos os feriados, mas é honesto)
    holidays_iso: tuple = ()  # ex: ("2026-01-01", "2026-12-25")


B3 = MarketSession(
    name="B3 (Brasil)",
    timezone="America/Sao_Paulo",
    open_time=time(10, 0),
    close_time=time(17, 25),  # call de fechamento até 17:55
    pre_open_minutes=15,
    after_hours_minutes=30,
    holidays_iso=(
        "2026-01-01", "2026-02-16", "2026-02-17",  # Carnaval
        "2026-04-03", "2026-04-21",
        "2026-05-01", "2026-06-04",
        "2026-09-07", "2026-10-12",
        "2026-11-02", "2026-11-15", "2026-11-20",
        "2026-12-24", "2026-12-25", "2026-12-31",
    ),
)

NYSE = MarketSession(
    name="NYSE / NASDAQ",
    timezone="America/New_York",
    open_time=time(9, 30),
    close_time=time(16, 0),
    pre_open_minutes=30,
    after_hours_minutes=60,
)


def get_market_status(
    session: MarketSession,
    now: datetime = None,
) -> MarketStatus:
    """Retorna status atual do mercado."""
    tz = ZoneInfo(session.timezone)
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    
    # Weekend
    if now.weekday() >= 5:
        return MarketStatus.WEEKEND
    
    # Holiday
    if now.strftime("%Y-%m-%d") in session.holidays_iso:
        return MarketStatus.HOLIDAY
    
    today_open = now.replace(
        hour=session.open_time.hour,
        minute=session.open_time.minute,
        second=0, microsecond=0,
    )
    today_close = now.replace(
        hour=session.close_time.hour,
        minute=session.close_time.minute,
        second=0, microsecond=0,
    )
    pre_open_start = today_open - timedelta(minutes=session.pre_open_minutes)
    after_hours_end = today_close + timedelta(minutes=session.after_hours_minutes)
    
    if now < pre_open_start or now > after_hours_end:
        return MarketStatus.CLOSED
    elif now < today_open:
        return MarketStatus.PRE_OPEN
    elif now <= today_close:
        return MarketStatus.OPEN
    else:
        return MarketStatus.AFTER_HOURS


def next_market_open(
    session: MarketSession,
    now: datetime = None,
) -> datetime:
    """Retorna timestamp da próxima abertura."""
    ...


def seconds_until_next_open(
    session: MarketSession,
    now: datetime = None,
) -> int:
    """Útil para sleep até abertura."""
    return int((next_market_open(session, now) - (now or datetime.now())).total_seconds())


def get_session_for_ticker(ticker: str) -> MarketSession:
    """Inferência por sufixo: .SA → B3, sem sufixo → NYSE."""
    if ticker.endswith(".SA") or ticker.startswith("^BVSP"):
        return B3
    if ticker.endswith("=X"):
        # Forex 24h — tratar como sempre aberto exceto fim de semana
        return _FOREX_24H
    return NYSE
```

### E2 — `LiveDataProvider`

`live_data_provider.py`:

```python
import time
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import yfinance as yf
from typing import Optional


class LiveDataProvider:
    """
    Provedor de dados via polling em yfinance.
    
    Mantém cache local em SQLite para evitar re-fetch de barras já recebidas.
    Detecta novas barras comparando timestamps.
    """
    
    POLL_INTERVALS = {
        "1m": 60,        # 1 minuto
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "60m": 3600,
        "1h": 3600,
        "1d": 60,        # daily: polling a cada 1min até nova barra aparecer
    }
    
    def __init__(
        self,
        ticker: str,
        interval: str = "1m",
        warmup_bars: int = 200,
        cache_dir: Path = Path("data/cache"),
    ):
        self.ticker = ticker
        self.interval = interval
        self.warmup_bars = warmup_bars
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_bar_time: Optional[pd.Timestamp] = None
        self._fetch_count = 0
        self._error_count = 0
    
    def fetch_warmup(self) -> pd.DataFrame:
        """
        Busca histórico inicial para warm-up dos indicadores.
        Período = self.warmup_bars + buffer.
        """
        period_str = self._compute_warmup_period()
        df = yf.Ticker(self.ticker).history(
            period=period_str,
            interval=self.interval,
            auto_adjust=True,
        )
        if df.empty:
            raise RuntimeError(f"Warmup vazio para {self.ticker}")
        df = df.tail(self.warmup_bars)
        self._last_bar_time = df.index[-1]
        return df
    
    def poll_new_bars(self) -> Optional[pd.DataFrame]:
        """
        Faz polling, retorna apenas novas barras (timestamp > _last_bar_time).
        Retorna None se nada novo.
        """
        try:
            self._fetch_count += 1
            # Janela curta: últimos N intervalos para pegar apenas atualizações
            df = yf.Ticker(self.ticker).history(
                period="5d",  # rede de segurança
                interval=self.interval,
                auto_adjust=True,
            )
            if df.empty:
                return None
            
            if self._last_bar_time:
                new_bars = df[df.index > self._last_bar_time]
            else:
                new_bars = df
            
            if new_bars.empty:
                return None
            
            self._last_bar_time = new_bars.index[-1]
            return new_bars
        
        except Exception as e:
            self._error_count += 1
            from logging import getLogger
            getLogger(__name__).warning(f"poll_new_bars erro: {e}")
            return None
    
    def get_health(self) -> dict:
        """Estatísticas de saúde para UI."""
        return {
            "ticker": self.ticker,
            "fetch_count": self._fetch_count,
            "error_count": self._error_count,
            "error_rate": self._error_count / max(1, self._fetch_count),
            "last_bar_time": self._last_bar_time.isoformat() if self._last_bar_time else None,
        }
    
    def _compute_warmup_period(self) -> str:
        """Calcula período yfinance para cobrir warmup_bars."""
        if self.interval == "1d":
            days = max(1, int(self.warmup_bars * 1.5))
            return f"{days}d"
        # intraday: estimar dias necessários (assumindo ~390 min/day para US, ~445 para B3)
        ...
```

### E3 — `LiveRunner`

`gui/runners/live.py`:

```python
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from gui.runners.base import BaseRunner
from market_schedule import (
    get_market_status,
    get_session_for_ticker,
    MarketStatus,
    seconds_until_next_open,
)
from live_data_provider import LiveDataProvider


class LiveRunner(BaseRunner):
    """
    Paper Trading com dados em tempo real via yfinance.
    
    Loop principal:
        1. Warmup: busca histórico inicial para indicadores
        2. Loop infinito (até abort ou perda de mercado):
           a. Verificar status do mercado
           b. Se fechado, dormir até próxima abertura
           c. Fetch new bars
           d. Para cada nova barra: gerar sinais, processar via backtester
           e. Emit eventos
           f. Sleep até próximo polling
    """
    
    def run(self) -> None:
        ticker = self.config["ticker"]
        interval = self.config.get("interval", "1m")
        max_duration_hours = self.config.get("max_duration_hours", 24)
        
        market_session = get_session_for_ticker(ticker)
        poll_interval = LiveDataProvider.POLL_INTERVALS.get(interval, 60)
        
        self.emit("SESSION_STARTED", {
            "ticker": ticker,
            "interval": interval,
            "market_session": market_session.name,
            "poll_interval_seconds": poll_interval,
        })
        
        # ============ Warmup ============
        provider = LiveDataProvider(ticker, interval, warmup_bars=200)
        try:
            warmup_data = provider.fetch_warmup()
        except Exception as e:
            self.emit("SESSION_ENDED", {
                "status": "error",
                "summary": {"error": f"Falha em warmup: {e}"},
            })
            return
        
        from indicators import compute_all
        full_data = compute_all(warmup_data)
        
        self.emit("WARMUP_COMPLETED", {
            "n_bars": len(full_data),
            "last_bar": full_data.index[-1].isoformat(),
        })
        
        # ============ Setup engine ============
        from gui.adapter import build_strategy, build_risk_guard
        from backtester import Backtester
        
        strategy = build_strategy(self.config)
        risk_guard = build_risk_guard(self.config)
        bt = Backtester(
            initial_capital=self.config.get("initial_capital", 100_000),
            commission=self.config.get("commission", 0.001),
            slippage=self.config.get("slippage", 0.001),
            risk_guard=risk_guard,
        )
        
        start_time = time.time()
        max_duration_seconds = max_duration_hours * 3600
        last_heartbeat = time.time()
        
        # ============ Loop principal ============
        while True:
            self.check_commands()
            if self._aborted:
                self._finalize(bt, status="aborted")
                return
            
            # Tempo total
            elapsed = time.time() - start_time
            if elapsed > max_duration_seconds:
                self.emit("MAX_DURATION_REACHED", {"elapsed_hours": elapsed / 3600})
                self._finalize(bt, status="completed")
                return
            
            # Market status
            status = get_market_status(market_session)
            
            self.emit("MARKET_STATUS", {
                "status": status.value,
                "ticker": ticker,
            })
            
            if status in (MarketStatus.WEEKEND, MarketStatus.HOLIDAY, MarketStatus.CLOSED):
                wait_seconds = min(seconds_until_next_open(market_session), 3600)
                self.emit("WAITING_FOR_MARKET", {
                    "current_status": status.value,
                    "sleep_seconds": wait_seconds,
                })
                # Sleep em chunks de 30s para responder a abort
                self._sleep_responsive(wait_seconds)
                continue
            
            # Fetch new bars
            new_bars = provider.poll_new_bars()
            
            if new_bars is not None and len(new_bars) > 0:
                new_bars = compute_all(pd.concat([full_data, new_bars]))[-len(new_bars):]
                
                for ts, bar in new_bars.iterrows():
                    # Adiciona ao dataset completo
                    full_data = pd.concat([full_data, pd.DataFrame([bar], index=[ts])])
                    if len(full_data) > 5000:
                        full_data = full_data.tail(5000)  # cap memória
                    
                    # Processa via mesma lógica do ReplayRunner
                    signals = strategy.gerar_sinais(full_data, ts)
                    for sig in signals:
                        self.emit("SIGNAL_GENERATED", {...})
                    
                    bar_result = bt.step(full_data, signals, ts)
                    for trade_evt in bar_result.get("trade_events", []):
                        self.emit(trade_evt["type"], trade_evt["payload"])
                    
                    self.emit("BAR_PROCESSED", {
                        "timestamp": int(ts.timestamp()),
                        "ticker": ticker,
                        "open": float(bar["Open"]),
                        "high": float(bar["High"]),
                        "low": float(bar["Low"]),
                        "close": float(bar["Close"]),
                        "is_live": True,
                    })
            
            # Métricas periódicas
            if time.time() - last_heartbeat > 30:
                self._emit_metrics(bt)
                self._emit_health(provider)
                last_heartbeat = time.time()
            
            # Sleep até próximo polling
            self._sleep_responsive(poll_interval)
    
    def _sleep_responsive(self, total_seconds: int) -> None:
        """Sleep em chunks pequenos; checa comandos e aborto."""
        chunks = max(1, total_seconds // 5)
        chunk_dur = total_seconds / chunks
        for _ in range(int(chunks)):
            if self._aborted:
                return
            time.sleep(chunk_dur)
            self.check_commands()
    
    def _emit_health(self, provider):
        self.emit("HEALTH_UPDATE", provider.get_health())
    
    def _emit_metrics(self, bt):
        metrics = bt.compute_running_metrics()
        self.emit("METRICS_UPDATE", {...})
    
    def _finalize(self, bt, status):
        self.emit("SESSION_ENDED", {
            "status": status,
            "summary": bt.compute_final_metrics(),
        })
```

### E4 — Idempotência via session_state

Live runs sobrevivem a reinício do servidor. Quando processo retoma:

```python
# db/repository.py — adicionar:
def get_session_state(self, session_id: str) -> dict:
    """
    Retorna snapshot que permite retomar live session.
    Inclui: posições abertas, last_processed_bar_ts, equity atual.
    """

def save_session_state(self, session_id: str, state: dict) -> None: ...
```

`LiveRunner` salva state a cada 5 minutos:
```python
self.repo.save_session_state(self.session_id, {
    "last_bar_ts": full_data.index[-1].isoformat(),
    "open_positions": [p.to_dict() for p in bt.open_positions],
    "equity": bt.current_equity,
})
```

Ao iniciar, verificar se existe state e oferecer retomada (decisão manual do usuário).

### E5 — Endpoint para iniciar Live via UI

Em `gui/routes/config.py`:

```python
elif mode == "live":
    # Validações específicas de live
    ticker = data["ticker"]
    from market_schedule import get_market_status, get_session_for_ticker
    market_session = get_session_for_ticker(ticker)
    status = get_market_status(market_session)
    
    if status == MarketStatus.HOLIDAY:
        return render_template("config.html.j2", 
            warning=f"{market_session.name} fechado hoje (feriado). Sessão iniciará mas aguardará abertura.",
            form_data=data), 200
    
    config = {
        "ticker": ticker,
        "interval": data.get("interval", "1m"),
        "max_duration_hours": int(data.get("max_duration_hours", 8)),
        "initial_capital": float(data.get("initial_capital", 100_000)),
        "commission": float(data.get("commission", 0.001)),
        "slippage": float(data.get("slippage", 0.001)),
        # ... strategy_params do preset
    }
    
    from gui.runners.live import LiveRunner
    runner_cls = LiveRunner
```

### E6 — Indicador de saúde na UI

`live.html.j2` ganha widget de health para sessões live:

```html
{% if session.mode == "live" %}
<div class="health-widget">
    <span>Status mercado: <strong id="market-status">—</strong></span>
    <span>Fetches: <strong id="fetch-count">0</strong></span>
    <span>Erros: <strong id="error-count">0</strong></span>
    <span>Última barra: <strong id="last-bar-time">—</strong></span>
    <span>Latência: <strong id="latency">—</strong></span>
</div>
{% endif %}
```

JS handler:
```javascript
socket.on("MARKET_STATUS", e => {
    document.getElementById("market-status").textContent = e.payload.status;
});

socket.on("HEALTH_UPDATE", e => {
    document.getElementById("fetch-count").textContent = e.payload.fetch_count;
    document.getElementById("error-count").textContent = e.payload.error_count;
    
    // Latência = now - last_bar_time
    if (e.payload.last_bar_time) {
        const lag = (Date.now() - new Date(e.payload.last_bar_time).getTime()) / 1000;
        document.getElementById("latency").textContent = `${Math.round(lag)}s`;
    }
});

socket.on("WAITING_FOR_MARKET", e => {
    document.getElementById("market-status").textContent = 
        `${e.payload.current_status} (próx. abertura em ${Math.round(e.payload.sleep_seconds/60)}min)`;
});
```

### E7 — Testes

**`tests/unit/test_market_schedule.py`** (mínimo 10 casos):

1. B3 OPEN às 11:00 de quarta-feira.
2. B3 PRE_OPEN às 9:50 (15min antes da abertura).
3. B3 AFTER_HOURS às 17:30.
4. B3 CLOSED às 23:00.
5. B3 WEEKEND aos sábados.
6. B3 HOLIDAY em 2026-12-25.
7. NYSE OPEN às 10:00 ET.
8. Forex tratado como 24h (exceto fim de semana).
9. `next_market_open` em sábado retorna segunda 10:00.
10. `get_session_for_ticker("^BVSP")` → B3.

**`tests/integration/test_live_runner.py`** (mínimo 6 casos):

1. **Warmup**: LiveRunner busca 200 barras antes de iniciar polling.
2. **Mercado fechado**: emit `WAITING_FOR_MARKET`, não polling.
3. **Idempotência**: 2 chamadas a `poll_new_bars` sem novas barras retornam None.
4. **Detecção de nova barra**: barra com ts > last_bar_time é processada.
5. **Erros em yfinance** incrementam error_count mas não quebram run.
6. **Abort responsivo**: aborto durante sleep retorna em < 10s.

**`tests/integration/test_live_recovery.py`** (mínimo 3 casos):

1. Save state + load state preserva equity, positions, last_bar_ts.
2. Re-iniciar runner com state existente retoma sem duplicar trades.
3. Crash sintético durante run salva state; reinício recupera.

### E8 — Mock de yfinance para testes

`tests/conftest.py`:

```python
@pytest.fixture
def mock_yfinance(monkeypatch):
    """Fixture que substitui yf.Ticker com mock controlável."""
    class MockHistory:
        def __init__(self, df):
            self.df = df
        def __call__(self, **kwargs):
            return self.df
    
    class MockTicker:
        def __init__(self, sym):
            self.sym = sym
            self.history = MockHistory(_generate_fake_ohlc(200))
    
    monkeypatch.setattr("yfinance.Ticker", MockTicker)
```

### E9 — Documentação `docs/LIVE_MODE.md`

Cobre:
- Como configurar sessão live
- Horários de pregão suportados
- Latência esperada (yfinance gratuito tem 15-20min de delay no Brasil)
- Limitações: não há tick data; partial fills não simulados
- Procedimento de recuperação após crash
- Como interpretar health indicators

---

## 4. Critério de Aceitação

- [ ] Suite completa passa (incluindo 19 novos testes)
- [ ] Live runner inicia sem erros durante horário de pregão
- [ ] Live runner aguarda corretamente fora de pregão
- [ ] Polling efetivamente detecta novas barras (sanity check manual em pregão real)
- [ ] Session state persiste e permite recuperação
- [ ] UI mostra health do data feed
- [ ] Aborto graceful em qualquer estado (warmup, polling, sleep)
- [ ] Erros transitórios em yfinance (rate limit, timeout) não derrubam a sessão
- [ ] `docs/LIVE_MODE.md` documenta limitações honestamente

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| yfinance rate-limit em sessões longas | Alta | Polling com backoff em erros; cache local agressivo |
| Latência maior que esperada no Brasil | Confirmada | Documentar 15-20min de delay claramente; indicador visual |
| Mudança de horário de verão | Média | `zoneinfo` cuida automaticamente |
| Splits/dividendos durante sessão live | Baixa | `auto_adjust=True` no yfinance |
| Discrepância yfinance vs corretora real | Alta | Documentar; este modo é paper, não execução real |
| Sessão "esquecida" rodando por dias | Média | `max_duration_hours` default 8; auto-finaliza |

---

## 6. Notas para o Claude Code

- **Não usar threading dentro do runner**: o processo já é dedicado. Apenas time.sleep + checks.
- **`pd.concat` em loop é caro**: usar `pd.concat([df1, df2])` somente em casos pequenos; para warmup full data, manter como list e converter periodicamente.
- **`auto_adjust=True`**: aplica ajuste de splits/dividendos. Importante para consistência com replay.
- **Backoff em erros**: erro em yfinance → dobrar interval temporariamente; retornar ao normal após sucesso.
- **Idempotência**: comparar `bar.timestamp` antes de processar; nunca confiar em "última posição".
- **Timezone awareness**: timestamps de yfinance vêm com tz. NUNCA fazer `dt.replace(tzinfo=None)` — converter explicitamente.
- **State save deve ser atômico**: write temp + rename.

---

## 7. Comandos de validação

```bash
pytest tests/unit/test_market_schedule.py -v
pytest tests/integration/test_live_runner.py -v
pytest tests/integration/test_live_recovery.py -v

# Manual durante pregão real
python -m gui.server
# Browser: configurar Live em PETR4.SA, interval 1m, durante pregão B3
# Esperar ~5 minutos
# Verificar barras chegando

# Manual fora de pregão
# Browser: configurar Live, fora de horário
# Verificar mensagem "aguardando abertura"
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — market_schedule | 1-1.5 dias |
| E2 — LiveDataProvider | 1.5-2 dias |
| E3 — LiveRunner | 2-3 dias |
| E4 — idempotência (state save/load) | 1-1.5 dias |
| E5 — config route update | 0.5 dia |
| E6 — health widget UI | 0.5-1 dia |
| E7 — testes (19 casos) | 2-3 dias |
| E8 — mock fixtures | 0.5 dia |
| E9 — docs | 0.5 dia |
| Buffer (yfinance edge cases, debug) | 1-2 dias |
| **Total** | **10-14 dias** |
