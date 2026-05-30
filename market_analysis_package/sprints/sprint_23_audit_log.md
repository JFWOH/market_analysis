# Sprint 23 — Audit Log Append-Only com Hash Chain

**Bloco**: II (Hardening)
**Duração estimada**: 4-6 dias úteis
**Pré-requisito**: Marco do Bloco I documentado (`findings/MARCO_BLOCO_I.md`)
**Status**: pending
**Tag ao fechar**: `v0.23.0`

---

## 1. Contexto

O sistema atual produz logs em texto via `logger.debug`/`logger.info`, mas não há **rastro imutável de decisões**. Para qualquer uso operacional sério — auditoria, compliance, debugging post-mortem, replay de cenários — precisa-se de um log onde:

- Cada decisão (sinal gerado, filtro aplicado, posição aberta, exit acionado) é registrada com timestamp e contexto.
- Não há possibilidade de modificar registros anteriores sem ser detectado.
- Cadeia de hashes (Merkle-chain simples) torna corrupção evidente.

Esta é a **fundação** para tudo no Bloco III: o relatório de sessão na UI lê do audit log; o replay tool reconstrói decisões; testes A/B comparam logs entre configs.

---

## 2. Objetivo

Implementar `audit_log.py` como módulo central, integrar nos pontos críticos do motor, e validar integridade da chain.

---

## 3. Entregáveis

### E1 — Módulo `audit_log.py`

```python
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import hashlib
import json
from typing import Any, Iterator

GENESIS_HASH = "0" * 64

@dataclass(frozen=True)
class AuditEntry:
    timestamp: str        # ISO 8601 UTC
    sequence: int         # incrementa monotonicamente dentro do arquivo
    event_type: str       # SIGNAL_GENERATED, SIGNAL_FILTERED, etc.
    session_id: str
    payload: dict         # contexto da decisão
    prev_hash: str
    this_hash: str        # SHA-256 do JSON de (sem this_hash)
    
    @classmethod
    def create(cls, event_type, session_id, payload, prev_hash, sequence):
        """Cria entry calculando this_hash automaticamente."""
        ...
    
    def verify_self(self) -> bool:
        """Verifica que this_hash bate com o conteúdo."""
        ...
    
    def to_jsonl_line(self) -> str:
        """Serializa como JSON em uma linha (sem newline)."""
        ...


class AuditLogger:
    """
    Logger append-only persistido em JSONL.
    
    Um arquivo por dia: logs/audit/YYYY-MM-DD.jsonl
    Cada entry tem hash do conteúdo + hash da entry anterior (chain).
    """
    
    def __init__(self, base_dir: Path = Path("logs/audit")):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._current_file = None
        self._current_date = None
        self._sequence = 0
        self._last_hash = GENESIS_HASH
    
    def append(
        self,
        event_type: str,
        session_id: str,
        payload: dict,
    ) -> str:
        """
        Adiciona entry. Retorna this_hash.
        
        Thread-safe via lock interno (importante para multi-process via fcntl).
        """
        ...
    
    def close(self) -> None:
        """Flush e fecha file handle."""
        ...


def verify_chain(log_file: Path) -> dict:
    """
    Lê arquivo JSONL inteiro e valida:
    1. Cada entry tem this_hash correto
    2. prev_hash de entry N+1 == this_hash de entry N
    3. sequence é monotônico
    4. timestamps são monotônicos (ou empate)
    
    Returns
    -------
    dict com:
        - valid: bool
        - n_entries: int
        - first_corrupt_index: int (-1 se válido)
        - corruption_type: str (None se válido)
        - last_hash: str
    """
    ...


def replay(
    log_file: Path,
    from_ts: datetime = None,
    to_ts: datetime = None,
    event_types: list[str] = None,
    session_id: str = None,
) -> Iterator[AuditEntry]:
    """
    Itera entries do log, filtradas por janela temporal, tipo, ou sessão.
    """
    ...
```

### E2 — Tipos de eventos canônicos

Definir constantes em `audit_log.py`:

```python
class EventType:
    # Lifecycle de sessão
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_ENDED = "SESSION_ENDED"
    SESSION_ABORTED = "SESSION_ABORTED"
    
    # Estratégia
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    SIGNAL_FILTERED = "SIGNAL_FILTERED"  # filtrado por regime, sentimento, etc.
    SIGNAL_DEDUPED = "SIGNAL_DEDUPED"
    
    # Trading
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_PARTIAL_CLOSED = "POSITION_PARTIAL_CLOSED"
    BREAKEVEN_MOVED = "BREAKEVEN_MOVED"
    POSITION_CLOSED = "POSITION_CLOSED"
    
    # Risk
    RISK_LIMIT_TRIGGERED = "RISK_LIMIT_TRIGGERED"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
    
    # Sistema
    CORRECTION = "CORRECTION"  # para "consertar" entry anterior sem modificá-la
    HEALTH_CHECK = "HEALTH_CHECK"
```

Payload por evento deve ter schema consistente. Documentar em `docs/AUDIT_EVENTS.md` (criado neste sprint).

### E3 — Integração nos pontos críticos

Modificações **mínimas** em:

- `strategy.py::gerar_sinais()` — append `SIGNAL_GENERATED` para cada sinal bruto; `SIGNAL_FILTERED` quando filtro bloqueia (com motivo no payload).
- `backtester.py` — append `POSITION_OPENED`, `POSITION_PARTIAL_CLOSED`, `BREAKEVEN_MOVED`, `POSITION_CLOSED` em transições de estado.
- `paper_trader.py` — mesmas integrações do backtester.

Implementação: passar `audit_logger` opcional para essas classes (default `None` — não loga, preserva retrocompatibilidade).

```python
class CombinedStrategy:
    def __init__(self, ..., audit_logger: AuditLogger | None = None):
        self._audit = audit_logger
    
    def gerar_sinais(self, data, ts):
        # ... lógica existente
        if self._audit and signal is not None:
            self._audit.append(
                EventType.SIGNAL_GENERATED,
                session_id=self._session_id,
                payload={
                    "ticker": ticker,
                    "tipo": signal["tipo"],
                    "preco": signal["preco"],
                    "stop_loss": signal["stop_loss"],
                    "estrategia": signal["estrategia"],
                    "context": {...},  # ADX, Hurst, etc.
                },
            )
```

### E4 — Testes `tests/unit/test_audit_log.py`

Mínimo 15 casos:

1. **Append básico**: entry persistida em arquivo correto, hash calculado.
2. **Chain integrity**: dois appends consecutivos têm prev_hash correto.
3. **Verify chain válida**: arquivo legítimo passa em `verify_chain`.
4. **Detecção de modificação**: alterar 1 byte em entry intermediária faz `verify_chain` retornar `valid=False` e identificar índice correto.
5. **Detecção de remoção**: remover entry do meio é detectado.
6. **Detecção de reordenação**: trocar ordem de entries é detectado.
7. **Replay com filtro temporal**: retorna apenas entries na janela.
8. **Replay com filtro de event_type**: filtragem correta.
9. **Replay com filtro de session_id**: isolamento entre sessões.
10. **Rotação diária**: ao mudar de dia, novo arquivo é criado mantendo continuidade da chain (prev_hash do primeiro do novo dia = last_hash do anterior).
11. **Thread-safety**: 10 threads appendando concorrentemente produzem chain válida.
12. **Sequence monotônico**: nunca decresce.
13. **Genesis**: primeira entry de arquivo novo tem `prev_hash = GENESIS_HASH` ou hash do arquivo anterior.
14. **Payload com tipos não-serializáveis** (datetime, numpy float) é tratado: ValueError ou conversão automática (decidir e testar).
15. **Performance**: 10k appends em < 5 segundos (SSD).

### E5 — CLI `python -m audit_log`

```bash
# Verificar integridade
python -m audit_log verify logs/audit/2026-05-13.jsonl

# Replay com filtros
python -m audit_log replay \
  --from "2026-05-13T10:00" \
  --to "2026-05-13T11:00" \
  --event-type SIGNAL_GENERATED \
  --session-id abc-123

# Estatísticas
python -m audit_log stats logs/audit/2026-05-13.jsonl
```

Saída em texto colorido (verde/vermelho) para legibilidade.

### E6 — Documentação `docs/AUDIT_EVENTS.md`

Schema canônico de cada event_type, com exemplo de payload:

```markdown
# Audit Log — Schema de Eventos

## SIGNAL_GENERATED

Disparado quando estratégia gera um sinal bruto, antes de qualquer filtro.

Payload:
```json
{
  "ticker": "PETR4.SA",
  "tipo": "Compra",
  "preco": 34.50,
  "stop_loss": 33.10,
  "preco_alvo": 37.30,
  "estrategia": "ensemble_ema",
  "forca": 0.78,
  "context": {
    "ADX": 28.4,
    "Hurst": 0.61,
    "RSI": 54.2
  }
}
```

[... e assim para todos os 12+ tipos]
```

---

## 4. Critério de Aceitação

- [ ] Suite completa passa (incluindo 15 novos testes)
- [ ] `audit_log.py` tem cobertura ≥ 95%
- [ ] CLI funciona para os 3 subcomandos (verify, replay, stats)
- [ ] Integração nos 3 módulos críticos (strategy, backtester, paper_trader) preserva 100% dos testes existentes
- [ ] `docs/AUDIT_EVENTS.md` documenta todos os event_types
- [ ] Rodar uma simulação completa produz log auditável (manual sanity check)
- [ ] Corrupção manual de log é detectada (manual sanity check)
- [ ] Performance: append não bloqueia simulação por mais que 1ms por evento

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| File locking em Windows entre processos | Média | Usar `portalocker` ou `msvcrt.locking`; testar com 2 processos |
| Hash collision (teoricamente impossível) | Negligenciável | SHA-256; documentar premissa |
| Logs crescem rapidamente | Média | Rotação diária + sugestão de compressão para arquivos > 7 dias |
| Conversão de tipos numpy/pandas no payload | Alta | Helper `_to_json_safe` que converte explicitamente |
| Integração quebra testes existentes | Média | `audit_logger=None` como default; verificar via CI |

---

## 6. Notas para o Claude Code

- **Atomicidade do append**: escrever no arquivo + flush antes de retornar hash. Se processo morrer entre escrita e flush, próximo `verify_chain` detecta entry parcial.
- **JSON serialization**: helper `_to_json_safe(obj)` que trata `datetime`, `np.int64`, `np.float64`, `pd.Timestamp`. Tipos não conversíveis levantam ValueError com mensagem clara.
- **Concorrência**: usar `threading.Lock` dentro do processo; `portalocker.lock(file, EXCLUSIVE)` entre processos.
- **Rotação de arquivo**: detectada por `datetime.utcnow().date() != self._current_date`. Ao rotacionar, primeira entry do novo arquivo carrega `prev_hash = last_hash do arquivo anterior` (não GENESIS_HASH, exceto no primeiro dia da história).
- **`verify_chain` deve ser eficiente**: streaming, não carregar arquivo inteiro em memória. Suporte para arquivos de centenas de MB.
- **Replay**: também streaming, iterator pattern.
- **Não usar pickle em payload** — apenas tipos JSON-serializáveis.

---

## 7. Comandos de validação

```bash
pytest tests/unit/test_audit_log.py -v
pytest tests/ -q  # suite completa

# Sanity checks manuais
python -c "
from audit_log import AuditLogger
logger = AuditLogger()
for i in range(100):
    logger.append('SIGNAL_GENERATED', 'test-session', {'i': i})
"
python -m audit_log verify logs/audit/$(date +%Y-%m-%d).jsonl

# Teste de corrupção (manual)
# 1. Rodar simulação
# 2. Editar 1 byte de um log file
# 3. python -m audit_log verify <file>
# 4. Esperado: detecta + reporta índice
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — módulo principal | 1.5-2 dias |
| E2 — schema de eventos | 0.5 dia |
| E3 — integração nos 3 módulos | 1 dia |
| E4 — testes (15 casos) | 1.5-2 dias |
| E5 — CLI | 0.5 dia |
| E6 — documentação | 0.5 dia |
| Buffer | 0.5 dia |
| **Total** | **4-6 dias** |
