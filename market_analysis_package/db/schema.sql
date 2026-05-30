-- ============================================================
-- market_analysis SQLite schema
-- Versão: 1.0
-- Criado no Sprint 25 (Bloco II)
-- 
-- Padrão de uso:
--   sqlite3 data/market_analysis.db < db/schema.sql
-- 
-- Notas:
-- - WAL mode habilitado para concorrência (multiple readers + single writer)
-- - Foreign keys ativas (PRAGMA por conexão também recomendado)
-- - Datas em ISO 8601 UTC
-- - Soft delete via deleted_at em sessions
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

-- ============================================================
-- Sessões de simulação (replay ou live)
-- ============================================================
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,            -- UUID v4
    name            TEXT NOT NULL,
    created_at      TEXT NOT NULL,               -- ISO 8601 UTC
    started_at      TEXT,
    ended_at        TEXT,
    status          TEXT NOT NULL                -- pending, running, completed, aborted, error
                    CHECK (status IN ('pending', 'running', 'completed', 'aborted', 'error', 'paused')),
    mode            TEXT NOT NULL                -- replay, live, imported
                    CHECK (mode IN ('replay', 'live', 'imported', 'backtest')),
    config_json     TEXT NOT NULL,               -- snapshot completo de params
    tickers_json    TEXT NOT NULL,               -- JSON array
    period_start    TEXT,                        -- só para replay
    period_end      TEXT,
    initial_capital REAL NOT NULL,
    final_equity    REAL,
    notes           TEXT,
    deleted_at      TEXT                         -- soft delete (NULL = ativa)
);

CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_mode ON sessions(mode);
CREATE INDEX IF NOT EXISTS idx_sessions_deleted ON sessions(deleted_at);

-- ============================================================
-- Sinais gerados (cada decisão da estratégia)
-- ============================================================
CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    ts              TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    tipo            TEXT NOT NULL                -- Compra, Venda
                    CHECK (tipo IN ('Compra', 'Venda')),
    estrategia      TEXT NOT NULL,               -- price_action, ensemble_ema, fibonacci, breakout
    preco           REAL NOT NULL,
    stop_loss       REAL NOT NULL,
    preco_alvo      REAL,
    forca           REAL,
    size_mult       REAL DEFAULT 1.0,
    filtered        INTEGER NOT NULL DEFAULT 0,  -- 0=executado, 1=filtrado
    filter_reason   TEXT,                        -- "regime_off", "macro_lock", "sentiment_neg", etc.
    context_json    TEXT,                        -- ADX, Hurst, RSI, etc. no momento
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_signals_session_ts ON signals(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_filtered ON signals(filtered);

-- ============================================================
-- Trades executados (entrada → exit completo)
-- ============================================================
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    signal_id       INTEGER,                     -- pode ser NULL se trade não veio de signal
    ticker          TEXT NOT NULL,
    side            TEXT NOT NULL                -- long, short
                    CHECK (side IN ('long', 'short')),
    
    -- Entrada
    entry_ts        TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    initial_size    INTEGER NOT NULL,
    initial_stop    REAL NOT NULL,
    initial_target  REAL,
    
    -- Partial exit (Sprint 1)
    partial_exit_ts     TEXT,
    partial_exit_price  REAL,
    partial_exit_size   INTEGER,
    breakeven_moved     INTEGER NOT NULL DEFAULT 0,
    breakeven_price     REAL,
    
    -- Chandelier (Sprint 13)
    chandelier_active   INTEGER NOT NULL DEFAULT 0,
    peak_price          REAL,                    -- peak high para long, peak low para short
    
    -- Exit final
    exit_ts         TEXT,
    exit_price      REAL,
    exit_reason     TEXT                         -- stop, target, manual, time_limit, chandelier, eod
                    CHECK (exit_reason IS NULL OR exit_reason IN 
                        ('stop', 'target', 'manual', 'time_limit', 'chandelier', 'eod', 'risk_guard')),
    
    -- P&L
    pnl_gross       REAL,                        -- antes de custos
    pnl_net         REAL,                        -- depois de slippage + comissão
    commission_paid REAL,
    slippage_paid   REAL,
    
    -- Contexto agregado
    bars_held       INTEGER,
    max_favorable_excursion REAL,                -- MFE em valor absoluto
    max_adverse_excursion   REAL,                -- MAE em valor absoluto
    
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (signal_id)  REFERENCES signals(id)  ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_session_id ON trades(session_id);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_entry_ts ON trades(entry_ts);
CREATE INDEX IF NOT EXISTS idx_trades_exit_reason ON trades(exit_reason);

-- ============================================================
-- Snapshots periódicos da equity curve (e métricas barra-a-barra)
-- ============================================================
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    ts              TEXT NOT NULL,
    equity_total    REAL NOT NULL,
    cash            REAL NOT NULL,
    position_value  REAL NOT NULL,               -- soma do market value das posições
    open_positions_count INTEGER NOT NULL DEFAULT 0,
    drawdown_total_pct REAL,                     -- MDD-equity (sprint 18)
    drawdown_capital_at_risk_pct REAL,           -- MDD-CAR (sprint 18)
    peak_equity REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_equity_session_ts ON equity_snapshots(session_id, ts);

-- ============================================================
-- Eventos genéricos da sessão (espelho do audit log)
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    ts              TEXT NOT NULL,
    event_type      TEXT NOT NULL,               -- ver docs/AUDIT_EVENTS.md
    payload_json    TEXT,
    audit_hash      TEXT,                        -- referência ao audit log (hash chain do Sprint 23)
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_audit_hash ON events(audit_hash);

-- ============================================================
-- Configs salvas (presets do usuário + presets built-in)
-- ============================================================
CREATE TABLE IF NOT EXISTS configs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    config_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_preset       INTEGER NOT NULL DEFAULT 0,  -- 1 = preset built-in (não deletável pela UI)
    -- Metadata adicionada pelos findings
    sharpe_oos_honest REAL,                      -- Sprint 21
    degradation_pct REAL,                        -- Sprint 21
    breakeven_slip_pct REAL                      -- Sprint 19
);

CREATE INDEX IF NOT EXISTS idx_configs_name ON configs(name);
CREATE INDEX IF NOT EXISTS idx_configs_is_preset ON configs(is_preset);

-- ============================================================
-- Eventos do Risk Guard (Sprint 24)
-- ============================================================
CREATE TABLE IF NOT EXISTS risk_guard_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    ts              TEXT NOT NULL,
    triggered_limit TEXT NOT NULL,               -- "max_drawdown_pct", "max_daily_loss_abs", etc.
    current_value   REAL,
    threshold       REAL,
    state_before    TEXT,                        -- OPEN, RESTRICTED, FROZEN
    state_after     TEXT,
    payload_json    TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_risk_session_ts ON risk_guard_events(session_id, ts);

-- ============================================================
-- Schema version tracking (para migrações futuras)
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER PRIMARY KEY,
    applied_at      TEXT NOT NULL,
    description     TEXT
);

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (1, datetime('now'), 'Initial schema (Sprint 25)');

-- ============================================================
-- Views úteis para queries comuns
-- ============================================================

-- View: resumo de cada sessão (campos calculados)
DROP VIEW IF EXISTS v_session_summary;
CREATE VIEW v_session_summary AS
SELECT
    s.id,
    s.name,
    s.created_at,
    s.started_at,
    s.ended_at,
    s.status,
    s.mode,
    s.tickers_json,
    s.initial_capital,
    s.final_equity,
    CASE 
        WHEN s.final_equity IS NOT NULL AND s.initial_capital > 0
        THEN (s.final_equity / s.initial_capital - 1.0) * 100.0
        ELSE NULL
    END AS total_return_pct,
    (SELECT COUNT(*) FROM trades t WHERE t.session_id = s.id) AS num_trades,
    (SELECT COUNT(*) FROM trades t WHERE t.session_id = s.id AND t.exit_reason IS NOT NULL) AS num_closed_trades,
    (SELECT COUNT(*) FROM signals sg WHERE sg.session_id = s.id) AS num_signals,
    (SELECT COUNT(*) FROM signals sg WHERE sg.session_id = s.id AND sg.filtered = 1) AS num_filtered_signals,
    (SELECT MIN(drawdown_total_pct) FROM equity_snapshots e WHERE e.session_id = s.id) AS worst_dd_equity_pct,
    (SELECT MIN(drawdown_capital_at_risk_pct) FROM equity_snapshots e WHERE e.session_id = s.id) AS worst_dd_car_pct
FROM sessions s
WHERE s.deleted_at IS NULL;

-- View: trades vencedores por sessão
DROP VIEW IF EXISTS v_winning_trades;
CREATE VIEW v_winning_trades AS
SELECT
    session_id,
    COUNT(*) AS n_wins,
    AVG(pnl_net) AS avg_win,
    SUM(pnl_net) AS total_wins_pnl,
    MAX(pnl_net) AS biggest_win
FROM trades
WHERE pnl_net > 0
GROUP BY session_id;

-- View: trades perdedores por sessão
DROP VIEW IF EXISTS v_losing_trades;
CREATE VIEW v_losing_trades AS
SELECT
    session_id,
    COUNT(*) AS n_losses,
    AVG(pnl_net) AS avg_loss,
    SUM(pnl_net) AS total_losses_pnl,
    MIN(pnl_net) AS biggest_loss
FROM trades
WHERE pnl_net <= 0
GROUP BY session_id;

-- View: métricas agregadas de performance por sessão
DROP VIEW IF EXISTS v_session_metrics;
CREATE VIEW v_session_metrics AS
SELECT
    s.id AS session_id,
    s.name,
    COALESCE(w.n_wins, 0) AS n_wins,
    COALESCE(l.n_losses, 0) AS n_losses,
    COALESCE(w.n_wins, 0) + COALESCE(l.n_losses, 0) AS n_trades_total,
    CASE 
        WHEN COALESCE(w.n_wins, 0) + COALESCE(l.n_losses, 0) > 0
        THEN CAST(COALESCE(w.n_wins, 0) AS REAL) / (COALESCE(w.n_wins, 0) + COALESCE(l.n_losses, 0)) * 100.0
        ELSE NULL
    END AS win_rate_pct,
    CASE 
        WHEN COALESCE(l.total_losses_pnl, 0) < 0
        THEN COALESCE(w.total_wins_pnl, 0) / ABS(l.total_losses_pnl)
        ELSE NULL
    END AS profit_factor,
    w.avg_win,
    l.avg_loss,
    w.biggest_win,
    l.biggest_loss
FROM sessions s
LEFT JOIN v_winning_trades w ON w.session_id = s.id
LEFT JOIN v_losing_trades  l ON l.session_id = s.id
WHERE s.deleted_at IS NULL;

-- ============================================================
-- Presets built-in (inseridos uma vez via INSERT OR IGNORE)
-- Os configs reais ficam em configs/presets/*.yaml e são 
-- importados pelo script de seed após criação do schema.
-- ============================================================

-- Nota: a tabela configs é populada via script de seed, não diretamente aqui
-- (para manter este arquivo de schema puramente estrutural).
