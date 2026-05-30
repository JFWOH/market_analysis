# Sprint 24 — Kill Switch e Circuit Breakers

**Bloco**: II (Hardening)
**Duração estimada**: 3-5 dias úteis
**Pré-requisito**: Sprint 23 fechado (`v0.23.0`)
**Status**: pending
**Tag ao fechar**: `v0.24.0`

---

## 1. Contexto

O `paper_trader.py` atual não tem mecanismo de proteção contra cenários onde algo dá errado. Em produção (ou em simulação que será apresentada como evidência), é necessário:

- **Limite de drawdown** — congela trading se equity cair X% abaixo do peak
- **Limite diário absoluto** — perda máxima em valor monetário antes de pausar
- **Throttling de ordens** — máximo N trades por hora (detecta loop infinito de sinais)
- **Limite de concentração** — máximo X% do capital em um único ticker
- **Watchdog externo** — processo independente que congela tudo se sistema principal não responder

Mesmo em paper trading, esses mecanismos são importantes para:
1. Validar comportamento esperado em cenários adversos
2. Estabelecer cultura de operação defensiva
3. Estar pronto para qualquer integração futura com corretora real

---

## 2. Objetivo

Implementar `RiskGuard` com limites configuráveis, integrar com `paper_trader.py`, e construir `watchdog.py` como processo independente.

---

## 3. Entregáveis

### E1 — Módulo `risk_guard.py`

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

class GuardState(str, Enum):
    OPEN = "OPEN"              # tudo permitido
    RESTRICTED = "RESTRICTED"  # sem novas posições, mantém existentes
    FROZEN = "FROZEN"          # zera tudo, recusa qualquer ação


@dataclass
class RiskLimits:
    max_drawdown_pct: float = 5.0          # 5% triggers RESTRICTED
    max_drawdown_pct_freeze: float = 10.0  # 10% triggers FROZEN
    max_daily_loss_abs: float = 5_000.0    # R$ 5k perda diária
    max_trades_per_hour: int = 20
    max_position_value_pct: float = 30.0   # concentração max em 1 ticker
    max_total_exposure_pct: float = 100.0  # exposição total (long+short abs)
    max_correlated_exposure_pct: float = 60.0  # ativos com corr > 0.7
    
    # Recuperação
    cool_down_after_restricted_minutes: int = 60
    require_manual_unfreeze: bool = True


@dataclass
class GuardEvent:
    timestamp: pd.Timestamp
    triggered_limit: str
    current_value: float
    threshold: float
    state_before: GuardState
    state_after: GuardState
    payload: dict


class RiskGuard:
    """
    Avalia, a cada decisão, se um limite foi violado.
    Mantém estado interno e expõe métodos de consulta.
    """
    
    def __init__(
        self,
        limits: RiskLimits,
        audit_logger=None,
    ):
        self.limits = limits
        self.state = GuardState.OPEN
        self._audit = audit_logger
        self._trade_log: list[tuple[pd.Timestamp, str]] = []
        self._peak_equity = None
        self._daily_pnl_start: float = 0.0
        self._daily_start_ts: pd.Timestamp = None
    
    def update_equity(self, ts: pd.Timestamp, equity: float) -> None:
        """Atualiza peak; verifica drawdown limits."""
        ...
    
    def can_open_position(
        self,
        ticker: str,
        size_value: float,
        current_positions: dict,
        ticker_correlations: dict | None = None,
    ) -> tuple[bool, str]:
        """
        Returns (allowed, reason). 
        Se allowed=False, reason explica qual limite foi violado.
        """
        ...
    
    def record_trade(self, ts: pd.Timestamp, ticker: str) -> None:
        """Registra trade no log para throttling check."""
        ...
    
    def force_unfreeze(self, reason: str) -> None:
        """Reset manual; loga no audit."""
        ...
    
    def get_status(self) -> dict:
        """Retorna snapshot do estado atual para UI."""
        ...
```

### E2 — Integração em `paper_trader.py`

Mínima invasão:

```python
class PaperTrader:
    def __init__(self, ..., risk_guard: RiskGuard | None = None):
        self._guard = risk_guard
    
    def open_position(self, signal, ts, equity):
        if self._guard:
            self._guard.update_equity(ts, equity)
            allowed, reason = self._guard.can_open_position(
                signal["ticker"],
                signal["size"] * signal["preco"],
                self.positions,
            )
            if not allowed:
                # Loga decisão de não-trade
                self._log_blocked_signal(signal, reason)
                return None
        # ... lógica existente
        if self._guard:
            self._guard.record_trade(ts, signal["ticker"])
```

### E3 — Módulo `watchdog.py`

Processo independente:

```python
import time
import os
import signal
from pathlib import Path

class Watchdog:
    """
    Processo separado que monitora heartbeat do main process.
    
    Se heartbeat não atualizado em N segundos, dispara freeze.
    """
    
    def __init__(
        self,
        heartbeat_file: Path,
        max_silence_seconds: int = 30,
        on_timeout: Callable = None,
        audit_logger=None,
    ):
        self.heartbeat_file = heartbeat_file
        self.max_silence = max_silence_seconds
        self.on_timeout = on_timeout or self._default_timeout_handler
        self._audit = audit_logger
        self._running = False
    
    def write_heartbeat(self) -> None:
        """Chamado pelo main process a cada N segundos."""
        self.heartbeat_file.write_text(str(time.time()))
    
    def run(self) -> None:
        """Loop principal do watchdog. Bloqueia."""
        self._running = True
        while self._running:
            time.sleep(5)
            try:
                last_beat = float(self.heartbeat_file.read_text().strip())
                silence = time.time() - last_beat
                if silence > self.max_silence:
                    self.on_timeout(silence)
            except (FileNotFoundError, ValueError):
                # heartbeat ainda não criado — tolerável nos primeiros segundos
                pass
    
    def _default_timeout_handler(self, silence_seconds: float) -> None:
        """Cria flag file que paper_trader checa periodicamente."""
        ...
```

CLI:
```bash
python -m watchdog \
  --heartbeat-file data/heartbeat.txt \
  --max-silence 30
```

### E4 — Configuração via YAML

Arquivo `configs/risk_limits.yaml`:

```yaml
default:
  max_drawdown_pct: 5.0
  max_drawdown_pct_freeze: 10.0
  max_daily_loss_abs: 5000.0
  max_trades_per_hour: 20
  max_position_value_pct: 30.0
  max_total_exposure_pct: 100.0
  max_correlated_exposure_pct: 60.0
  cool_down_after_restricted_minutes: 60
  require_manual_unfreeze: true

conservative:
  max_drawdown_pct: 2.0
  max_drawdown_pct_freeze: 5.0
  max_daily_loss_abs: 2000.0
  max_trades_per_hour: 10
  max_position_value_pct: 20.0
  max_total_exposure_pct: 60.0

aggressive:
  max_drawdown_pct: 10.0
  max_drawdown_pct_freeze: 20.0
  max_daily_loss_abs: 20000.0
  max_trades_per_hour: 50
```

### E5 — Testes `tests/unit/test_risk_guard.py`

Mínimo 12 casos:

1. **Estado inicial OPEN**, todos os limites OK.
2. **Drawdown 5%**: transição `OPEN → RESTRICTED`.
3. **Drawdown 10%**: transição `OPEN → FROZEN` direto.
4. **Recuperação de drawdown**: não volta automático de FROZEN (require_manual_unfreeze).
5. **Cool-down de RESTRICTED**: após N minutos sem nova violação, volta para OPEN.
6. **Daily loss limit**: dispara RESTRICTED ao atingir.
7. **Trades/hora**: 21º trade na mesma hora é bloqueado.
8. **Concentração**: tentar abrir 31% em um ticker é bloqueado.
9. **Correlação**: dois tickers com correlação 0.85 ultrapassando 60% do capital → bloqueado.
10. **Force unfreeze** funciona e é logado.
11. **Status snapshot** retorna campos esperados.
12. **Integração com paper_trader**: posição é bloqueada quando guard está RESTRICTED.

### E6 — Testes `tests/unit/test_watchdog.py`

Mínimo 5 casos:

1. **Heartbeat recente**: watchdog não dispara.
2. **Heartbeat antigo**: dispara timeout handler.
3. **Heartbeat inexistente nos primeiros 5s**: tolerado.
4. **Sinal de stop** (`SIGTERM`) interrompe watchdog graciosamente.
5. **Audit log recebe `KILL_SWITCH_ACTIVATED`** quando timeout dispara.

### E7 — Documentação `docs/RISK_GUARD.md`

Explica:
- Cada limite e seu racional
- Como configurar via YAML
- Como interpretar transições de estado
- Procedimento de unfreeze manual
- Limitações conhecidas (não substitui análise de risco humana)

---

## 4. Critério de Aceitação

- [ ] Suite completa passa (incluindo 17 novos testes)
- [ ] `risk_guard.py` tem cobertura ≥ 95%
- [ ] `watchdog.py` tem cobertura ≥ 85%
- [ ] Integração em `paper_trader.py` não quebra testes existentes
- [ ] Sanity check manual: cenário sintético de crash -30% em 20 barras é interrompido pelo guard antes do stop final
- [ ] Sanity check manual: watchdog congela sistema se main process for travado (kill -STOP)
- [ ] `configs/risk_limits.yaml` tem 3 perfis (default, conservative, aggressive)
- [ ] Todas as transições de estado registradas no audit log do Sprint 23

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Falsos positivos no throttling | Média | Limites configuráveis; perfil "aggressive" é mais permissivo |
| Correlação entre tickers exige dados | Média | Aceitar `ticker_correlations=None` (skip check); documentar |
| Watchdog em Windows: process inter-comunicação | Média | File-based heartbeat (não signals); funciona em qualquer OS |
| Estado do guard perdido em crash | Alta | Persistência opcional (Sprint 25 com SQLite) — neste sprint aceitar volátil |

---

## 6. Notas para o Claude Code

- **`update_equity` deve ser idempotente**: chamar duas vezes com mesmo ts/equity não duplica peak.
- **`_trade_log` para throttling**: deque com `maxlen=200`, filtragem por janela temporal a cada `record_trade`.
- **Daily reset**: detectar mudança de dia via `ts.date() != self._daily_start_ts.date()`.
- **Watchdog em processo separado**: usar `multiprocessing.Process` ou subprocess. Não threading (precisa morrer mesmo se main travar).
- **Heartbeat file**: escrita atômica (escrever em temp + rename) para evitar leitura de arquivo parcial.
- **Logs no audit**: estado mudou de X para Y, qual limite, valores atuais.

---

## 7. Comandos de validação

```bash
pytest tests/unit/test_risk_guard.py -v
pytest tests/unit/test_watchdog.py -v
pytest tests/ -q

# Sanity check manual
python -c "
from risk_guard import RiskGuard, RiskLimits
import pandas as pd

g = RiskGuard(RiskLimits())
g.update_equity(pd.Timestamp.now(), 100_000)
g.update_equity(pd.Timestamp.now(), 94_000)  # 6% DD
print(g.get_status())  # esperado: state=RESTRICTED
"

# Watchdog em background
python -m watchdog --heartbeat-file /tmp/hb.txt --max-silence 10 &
# Em outro terminal:
echo $(date +%s) > /tmp/hb.txt  # heartbeat fresco
sleep 15  # esperar timeout
# verificar logs
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — RiskGuard | 1-1.5 dias |
| E2 — integração | 0.5 dia |
| E3 — Watchdog | 0.5-1 dia |
| E4 — YAML config | 0.25 dia |
| E5 + E6 — testes (17 casos) | 1.5-2 dias |
| E7 — documentação | 0.25 dia |
| Buffer | 0.5 dia |
| **Total** | **3-5 dias** |
