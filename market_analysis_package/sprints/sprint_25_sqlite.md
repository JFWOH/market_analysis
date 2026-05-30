# Sprint 25 — Backend SQLite

**Bloco**: II (Hardening)
**Duração estimada**: 5-7 dias úteis
**Pré-requisito**: Sprint 24 fechado (`v0.24.0`)
**Status**: pending
**Tag ao fechar**: `v0.25.0`

---

## 1. Contexto

O estado do `paper_trader.py` hoje é persistido em arquivos JSON (`.paper_positions.json`, `paper_trades.json`). Isso funciona para single-user single-machine mas:

- **Não escala** para múltiplas sessões simultâneas (Bloco III precisa).
- **Não permite queries analíticas** ("todas as sessões com PF > 1.5 no último mês").
- **Concorrência frágil** — duas escritas simultâneas podem corromper o arquivo.
- **Histórico ilegível** sem ferramenta de inspeção dedicada.

SQLite resolve tudo isso sem introduzir dependência pesada (vem com Python stdlib), e mantém o sistema empacotável como executável local. PostgreSQL/TimescaleDB seriam overkill nesta fase — entram em programa futuro quando houver volume real.

---

## 2. Objetivo

Substituir a persistência em JSON por SQLite, com schema versionado e camada de acesso tipada, **sem quebrar nenhum teste existente**.

---

## 3. Entregáveis

### E1 — Schema `db/schema.sql`

```sql
-- =========================================================================
-- market_analysis SQLite Schema v1
-- =========================================================================
-- Convenções:
-- - Todos os IDs são UUID v4 (TEXT)
-- - Timestamps em ISO 8601 UTC (TEXT)
-- - Valores monetários em REAL (não INTEGER * 100 — perda de simplicidade)
-- - JSON payloads em TEXT
-- =========================================================================

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- ============ TABELA: schema_version ============
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT
);

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (1, datetime('now'), 'Initial schema — Sprint 25');

-- ============ TABELA: sessions ============
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('replay', 'live')),
    config_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'aborted', 'error')),
    summary_json TEXT,
    audit_log_file TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);

-- ============ TABELA: signals ============
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    signal_type TEXT NOT NULL CHECK (signal_type IN ('Compra', 'Venda')),
    price REAL NOT NULL,
    stop_loss REAL,
    target REAL,
    strategy_name TEXT NOT NULL,
    forca REAL,
    was_filtered INTEGER NOT NULL DEFAULT 0,
    filter_reason TEXT,
    context_json TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_signals_session ON signals(session_id);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_filtered ON signals(was_filtered);

-- ============ TABELA: trades ============
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    initial_size REAL NOT NULL,
    initial_stop REAL,
    initial_target REAL,
    exit_time TEXT,
    exit_price REAL,
    exit_reason TEXT CHECK (exit_reason IN ('stop', 'target', 'partial', 'breakeven', 'chandelier', 'time', 'manual', 'risk_guard')),
    final_size REAL,
    realized_pnl REAL,
    commission_paid REAL,
    partial_count INTEGER DEFAULT 0,
    breakeven_moved INTEGER DEFAULT 0,
    strategy_name TEXT,
    signal_id INTEGER,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades(entry_time);

-- ============ TABELA: equity_snapshots ============
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    position_value REAL NOT NULL,
    drawdown_total_pct REAL,
    drawdown_capital_at_risk_pct REAL,
    n_open_positions INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_equity_session_ts ON equity_snapshots(session_id, timestamp);

-- ============ TABELA: events ============
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO' CHECK (severity IN ('DEBUG', 'INFO', 'WARNING', 'ERROR')),
    message TEXT NOT NULL,
    context_json TEXT,
    audit_hash TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);

-- ============ TABELA: configs (presets) ============
CREATE TABLE IF NOT EXISTS configs (
    name TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_builtin INTEGER NOT NULL DEFAULT 0
);

-- ============ TABELA: risk_guard_events ============
CREATE TABLE IF NOT EXISTS risk_guard_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    triggered_limit TEXT NOT NULL,
    current_value REAL,
    threshold REAL,
    state_before TEXT NOT NULL,
    state_after TEXT NOT NULL,
    payload_json TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_riskguard_session ON risk_guard_events(session_id);

-- ============ VIEW: session_summary ============
CREATE VIEW IF NOT EXISTS v_session_summary AS
SELECT
    s.id,
    s.mode,
    s.status,
    s.started_at,
    s.ended_at,
    (SELECT COUNT(*) FROM trades t WHERE t.session_id = s.id) AS num_trades,
    (SELECT COUNT(*) FROM signals sig WHERE sig.session_id = s.id) AS num_signals,
    (SELECT COUNT(*) FROM signals sig WHERE sig.session_id = s.id AND sig.was_filtered = 1) AS num_filtered,
    (SELECT SUM(realized_pnl) FROM trades t WHERE t.session_id = s.id) AS total_pnl,
    (SELECT MAX(drawdown_capital_at_risk_pct) FROM equity_snapshots e WHERE e.session_id = s.id) AS max_dd_car,
    (SELECT MAX(drawdown_total_pct) FROM equity_snapshots e WHERE e.session_id = s.id) AS max_dd_total
FROM sessions s;
```

### E2 — Camada de acesso `db/repository.py`

```python
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Iterator

DEFAULT_DB_PATH = Path("data/market_analysis.db")


@dataclass
class SessionRecord:
    id: str
    mode: str
    config: dict
    started_at: datetime
    ended_at: Optional[datetime]
    status: str
    summary: Optional[dict]
    audit_log_file: Optional[str]
    notes: Optional[str]


@dataclass
class TradeRecord:
    id: str
    session_id: str
    ticker: str
    side: str
    entry_time: datetime
    entry_price: float
    # ... (todos os campos da tabela trades)


class Repository:
    """
    Camada única de acesso ao SQLite.
    Thread-safe via connection-per-thread.
    """
    
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
    
    @contextmanager
    def _conn(self):
        """Connection context manager. WAL mode + foreign keys."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _ensure_schema(self) -> None:
        """Aplica schema.sql se necessário."""
        ...
    
    # ============ Sessions ============
    def create_session(
        self,
        mode: str,
        config: dict,
        audit_log_file: str = None,
    ) -> str:
        """Cria sessão e retorna UUID."""
        ...
    
    def end_session(
        self,
        session_id: str,
        status: str,
        summary: dict,
    ) -> None: ...
    
    def get_session(self, session_id: str) -> Optional[SessionRecord]: ...
    
    def list_sessions(
        self,
        status: str = None,
        limit: int = 50,
        order_by: str = "started_at DESC",
    ) -> list[SessionRecord]: ...
    
    # ============ Signals ============
    def add_signal(self, session_id: str, signal_data: dict) -> int: ...
    def list_signals(
        self,
        session_id: str,
        was_filtered: bool = None,
    ) -> list[dict]: ...
    
    # ============ Trades ============
    def add_trade(self, session_id: str, trade_data: dict) -> str: ...
    def update_trade_exit(
        self,
        trade_id: str,
        exit_data: dict,
    ) -> None: ...
    def list_trades(self, session_id: str) -> list[TradeRecord]: ...
    
    # ============ Equity ============
    def add_equity_snapshot(
        self,
        session_id: str,
        snapshot: dict,
    ) -> None: ...
    def get_equity_curve(
        self,
        session_id: str,
    ) -> list[dict]: ...
    
    # ============ Events ============
    def add_event(
        self,
        session_id: str,
        category: str,
        message: str,
        severity: str = "INFO",
        context: dict = None,
        audit_hash: str = None,
    ) -> None: ...
    
    def list_events(
        self,
        session_id: str,
        category: str = None,
        since: datetime = None,
    ) -> Iterator[dict]: ...
    
    # ============ Configs (presets) ============
    def save_preset(self, name: str, config: dict, description: str = "") -> None: ...
    def get_preset(self, name: str) -> Optional[dict]: ...
    def list_presets(self) -> list[dict]: ...
    
    # ============ Aggregate queries ============
    def get_session_summary(self, session_id: str) -> dict:
        """Usa view v_session_summary."""
        ...
    
    def list_session_summaries(self, **filters) -> list[dict]: ...
```

### E3 — Reescrita do `paper_trader.py`

API externa **idêntica** ao atual (zero quebras). Mudança interna:

- Construtor aceita `repository: Repository | None = None`.
- Se `repository` é fornecido, todas as operações persistem no SQLite.
- Se `None`, fallback para JSON (retrocompatibilidade durante transição).
- Métodos públicos (open_position, close_position, get_metrics) retornam mesmos tipos.

### E4 — Script `scripts/migrate_json_to_sqlite.py`

One-shot migration:

```bash
python scripts/migrate_json_to_sqlite.py \
  --positions-file .paper_positions.json \
  --trades-file paper_trades.json \
  --db-path data/market_analysis.db \
  --dry-run  # opcional
```

- Lê JSONs existentes.
- Cria sessão "legacy_import" com timestamp original.
- Insere trades e snapshots derivados.
- Loga inconsistências sem abortar (registra em `migration_report.txt`).

### E5 — Migração de presets

`configs/presets/*.yaml` → tabela `configs` via script de seed:

```bash
python scripts/seed_presets.py
```

Carrega:
- `sprint_13_reference.yaml`
- `sprint_2_baseline.yaml`
- `conservative.yaml`

Marca como `is_builtin = 1`.

### E6 — Testes `tests/unit/test_repository.py`

Mínimo 20 casos:

1. **Schema aplicado** automaticamente em DB nova.
2. **Schema versionado** — versão registrada em `schema_version`.
3. **CRUD sessions**: create, get, list, end.
4. **CRUD trades**: add, update_exit, list.
5. **CRUD signals**: filtered vs unfiltered.
6. **Equity snapshots**: ordenação temporal.
7. **Events**: filtro por categoria.
8. **Presets**: save, get, list, builtin marker.
9. **Foreign key**: deletar sessão deleta trades cascata.
10. **JSON serialization**: dicts complexos preservados.
11. **Timestamps**: ISO 8601 round-trip sem perda de precisão.
12. **View summary**: contagens corretas.
13. **Concorrência (2 threads)**: escritas simultâneas não corrompem.
14. **Concorrência (2 processos)**: WAL mode permite leitura concorrente.
15. **Performance**: 10k inserts em < 5 segundos.
16. **Idempotência**: re-aplicar schema em DB existente não quebra.
17. **Migração de dados ausentes**: campos NULL tratados corretamente.
18. **List with filters**: status, limit, order_by funcionam.
19. **Aggregate queries**: get_session_summary retorna dados corretos.
20. **Validação CHECK**: insert com `mode='invalid'` falha.

### E7 — Testes `tests/unit/test_paper_trader_sqlite.py`

Mínimo 6 casos garantindo retrocompatibilidade:

1. Todos os testes existentes do `test_paper_trader.py` passam com `repository=Repository()`.
2. Mesmo teste sem repository (modo JSON legacy) passa.
3. State após restart é idêntico ao state pré-restart.
4. Múltiplas sessões simultâneas não interferem.
5. Audit log + DB ficam consistentes (mesmo hash referenciado em ambos).
6. Recovery após crash sintético: posições abertas são detectadas e reportadas.

### E8 — Documentação `docs/DATABASE.md`

Explica:
- Schema completo com diagrama ER (ASCII art ou Mermaid)
- Queries comuns
- Procedimento de backup (cópia simples do .db file)
- Migrations futuras (placeholder para versionamento)

---

## 4. Critério de Aceitação

- [ ] Suite completa passa (519+ existentes + 26 novos)
- [ ] `repository.py` tem cobertura ≥ 90%
- [ ] Schema aplicado automaticamente em DB nova
- [ ] Migração funciona em dados JSON reais existentes
- [ ] Performance: queries analíticas básicas em < 100ms (medido)
- [ ] WAL mode confirmado: `PRAGMA journal_mode;` retorna 'wal'
- [ ] Foreign keys funcionam (DELETE cascata testado)
- [ ] `paper_trader.py` API pública inalterada
- [ ] `docs/DATABASE.md` documenta schema completo

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Quebra de testes existentes do paper_trader | Alta | API pública estritamente preservada; testes legacy rodam com repo opcional |
| SQLite locking em WAL mode em Windows | Baixa-Média | Testar explicitamente em CI Windows; documentar workarounds |
| Migração perde dados | Média | Dry-run obrigatório antes de produção; logs detalhados |
| Schema mudará em sprints futuros | Alta | `schema_version` table + placeholder para migrations |
| Performance ruim em queries de grandes históricos | Média | Indices apropriados; medir com fixture de 100k trades |

---

## 6. Notas para o Claude Code

- **Não usar SQLAlchemy ORM**. Dependência pesada para benefício marginal nesta fase. SQL puro via `sqlite3`.
- **Connection per call** com context manager — não manter long-lived connections.
- **`uuid.uuid4().hex`** para IDs (sem hífens para queries mais limpas).
- **Timestamps**: sempre converter `datetime` ↔ ISO 8601 string explicitamente. Nunca confiar em conversão automática.
- **JSON columns**: serializar com `json.dumps(default=str)` para datetimes; deserializar com `json.loads` direto (string fica string).
- **WAL mode**: importante em Windows porque permite leitura concorrente durante escrita.
- **Pragma settings**: aplicar em toda conexão (não no schema apenas).
- **Backup**: documentar que `.db-wal` e `.db-shm` precisam ser copiados juntos com `.db`, OU executar `PRAGMA wal_checkpoint(FULL)` antes da cópia.

---

## 7. Comandos de validação

```bash
pytest tests/unit/test_repository.py -v
pytest tests/unit/test_paper_trader_sqlite.py -v
pytest tests/ -q  # suite completa

# Sanity check: schema aplicado
python -c "
from db.repository import Repository
r = Repository()
import sqlite3
conn = sqlite3.connect('data/market_analysis.db')
cursor = conn.execute('SELECT version FROM schema_version')
print(cursor.fetchall())  # esperado: [(1,)]
"

# Migração dry-run
python scripts/migrate_json_to_sqlite.py --dry-run

# Seed presets
python scripts/seed_presets.py
sqlite3 data/market_analysis.db "SELECT name FROM configs"
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — schema.sql | 0.5-1 dia |
| E2 — Repository | 1.5-2 dias |
| E3 — paper_trader rewrite (mantendo API) | 1 dia |
| E4 — migração script | 0.5 dia |
| E5 — seed presets | 0.25 dia |
| E6 + E7 — testes (26 casos) | 1.5-2 dias |
| E8 — docs | 0.25 dia |
| Buffer | 0.5 dia |
| **Total** | **5-7 dias** |
