# Sprint 29 — Visualização Rica (Charts + Painel ao Vivo)

**Bloco**: III (Interface Gráfica)
**Duração estimada**: 8-10 dias úteis
**Pré-requisito**: Sprint 28 fechado (`v0.28.0`)
**Status**: pending
**Tag ao fechar**: `v0.29.0`

---

## 1. Contexto

Até o Sprint 28, a UI funcionalmente roda mas mostra apenas log textual dos eventos. Este sprint **substitui o log puro pelo painel completo** com três áreas:

- **Painel superior** — gráfico candlestick principal com overlays (sinais, stops/targets, indicadores)
- **Painel inferior esquerdo** — métricas em tempo real com sparklines
- **Painel inferior direito** — log categorizado com expansão de contexto

Este é o sprint que define a **experiência diária** do usuário. Cada decisão visual aqui afeta usabilidade por anos. Princípios orientadores:
- **Decisões de não-trade são visíveis** (filtros bloqueados aparecem no log com motivo)
- **Densidade de informação alta** mas legível
- **Performance**: streaming de eventos não trava a UI mesmo em sessões longas

---

## 2. Objetivo

Construir o painel ao vivo completo, com TradingView Lightweight Charts para o gráfico principal, Plotly para sparklines, e UI responsiva a eventos via SocketIO.

---

## 3. Entregáveis

### E1 — Layout HTML do painel ao vivo

`gui/templates/live.html.j2` reescrito:

```html
{% extends "base.html.j2" %}
{% block title %}Live — {{ session.id[:8] }}{% endblock %}

{% block content %}
<div class="live-container">
    <!-- Header com session info + controles -->
    <header class="live-header">
        <div class="session-info">
            <h2>{{ session.config.ticker }} — {{ session.mode|upper }}</h2>
            <span class="session-id">{{ session.id[:8] }}</span>
            <span class="session-period">
                {{ session.config.start_date }} → {{ session.config.end_date }}
            </span>
        </div>
        <div class="progress-bar">
            <div id="progress-fill" style="width: 0%"></div>
            <span id="progress-text">0%</span>
        </div>
        <div class="controls">
            <button id="btn-pause" onclick="sendCommand('pause')">⏸ Pausar</button>
            <button id="btn-resume" onclick="sendCommand('resume')" disabled>▶ Retomar</button>
            <button id="btn-abort" onclick="confirmAbort()">⏹ Abortar</button>
            <span class="connection-status" id="conn-status">●</span>
        </div>
    </header>
    
    <!-- Painel superior: gráfico principal -->
    <section class="chart-section">
        <div class="chart-toolbar">
            <select id="indicator-select">
                <option value="">Nenhum</option>
                <option value="adx">ADX</option>
                <option value="hurst">Hurst</option>
                <option value="rsi">RSI</option>
            </select>
            <select id="ticker-select"></select>
        </div>
        <div id="main-chart" class="main-chart"></div>
        <div id="indicator-chart" class="indicator-chart"></div>
    </section>
    
    <!-- Painel inferior: métricas + log -->
    <section class="bottom-section">
        <div class="metrics-panel">
            <h3>Métricas em Tempo Real</h3>
            <div class="metric-grid">
                <div class="metric-card" data-metric="equity">
                    <span class="metric-label">Equity</span>
                    <span class="metric-value" id="m-equity">R$ —</span>
                    <div class="sparkline" id="sl-equity"></div>
                </div>
                <div class="metric-card" data-metric="pnl">
                    <span class="metric-label">P&L</span>
                    <span class="metric-value" id="m-pnl">R$ —</span>
                    <div class="sparkline" id="sl-pnl"></div>
                </div>
                <div class="metric-card" data-metric="drawdown">
                    <span class="metric-label">Drawdown (CAR)</span>
                    <span class="metric-value" id="m-dd">— %</span>
                    <div class="sparkline" id="sl-dd"></div>
                </div>
                <div class="metric-card" data-metric="sharpe">
                    <span class="metric-label">Sharpe</span>
                    <span class="metric-value" id="m-sharpe">—</span>
                </div>
                <div class="metric-card" data-metric="trades">
                    <span class="metric-label">Trades</span>
                    <span class="metric-value" id="m-trades">0</span>
                </div>
                <div class="metric-card" data-metric="winrate">
                    <span class="metric-label">Win Rate</span>
                    <span class="metric-value" id="m-winrate">— %</span>
                </div>
            </div>
        </div>
        
        <div class="log-panel">
            <h3>Log de Eventos</h3>
            <div class="log-filters">
                <label><input type="checkbox" data-cat="SIGNAL" checked> Sinais</label>
                <label><input type="checkbox" data-cat="ENTRY" checked> Entradas</label>
                <label><input type="checkbox" data-cat="EXIT" checked> Saídas</label>
                <label><input type="checkbox" data-cat="FILTER" checked> Filtros</label>
                <label><input type="checkbox" data-cat="ERROR" checked> Erros</label>
            </div>
            <div id="event-log" class="event-log"></div>
        </div>
    </section>
</div>
{% endblock %}

{% block scripts %}
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script src="{{ url_for('static', filename='js/live.js') }}"></script>
<script>
    window.SESSION_ID = "{{ session.id }}";
    window.SESSION_CONFIG = {{ session.config|tojson }};
    initLivePanel();
</script>
{% endblock %}
```

### E2 — `gui/static/js/live.js` — núcleo do painel

```javascript
// =====================================================
// gui/static/js/live.js — painel ao vivo
// =====================================================

const MAX_LOG_ENTRIES = 1000;       // ring buffer
const MAX_SPARKLINE_POINTS = 100;   // sparklines
const MAX_CHART_BARS = 500;         // chart principal

let socket = null;
let chart = null;
let candleSeries = null;
let signalMarkers = [];
let indicatorChart = null;
let indicatorSeries = null;

let logBuffer = [];
let sparklineData = {
    equity: [],
    pnl: [],
    drawdown: [],
};

function initLivePanel() {
    initChart();
    initSparklines();
    connectSocket();
    bindFilters();
}

// ============ Chart principal ============
function initChart() {
    const container = document.getElementById("main-chart");
    chart = LightweightCharts.createChart(container, {
        layout: {
            background: { type: "solid", color: "#1e1e1e" },
            textColor: "#d1d4dc",
        },
        grid: {
            vertLines: { color: "#2a2e39" },
            horzLines: { color: "#2a2e39" },
        },
        crosshair: { mode: 0 },
        rightPriceScale: { borderColor: "#485158" },
        timeScale: { borderColor: "#485158", timeVisible: true },
        height: 400,
    });
    
    candleSeries = chart.addCandlestickSeries({
        upColor: "#26a69a",
        downColor: "#ef5350",
        borderVisible: false,
        wickUpColor: "#26a69a",
        wickDownColor: "#ef5350",
    });
    
    // Responsive resize
    window.addEventListener("resize", () => {
        chart.applyOptions({ width: container.clientWidth });
    });
}

function addCandle(time, ohlc) {
    candleSeries.update({
        time: time,
        open: ohlc.open,
        high: ohlc.high,
        low: ohlc.low,
        close: ohlc.close,
    });
}

function addSignalMarker(time, signalType, price) {
    const marker = {
        time: time,
        position: signalType === "Compra" ? "belowBar" : "aboveBar",
        color: signalType === "Compra" ? "#26a69a" : "#ef5350",
        shape: signalType === "Compra" ? "arrowUp" : "arrowDown",
        text: signalType === "Compra" ? "C" : "V",
    };
    signalMarkers.push(marker);
    if (signalMarkers.length > 200) signalMarkers.shift();
    candleSeries.setMarkers(signalMarkers);
}

// ============ Sparklines ============
function initSparklines() {
    ["equity", "pnl", "dd"].forEach(name => {
        const div = document.getElementById(`sl-${name}`);
        Plotly.newPlot(div, [{
            x: [],
            y: [],
            type: "scatter",
            mode: "lines",
            line: { width: 1.5 },
        }], {
            margin: { l: 0, r: 0, t: 0, b: 0 },
            xaxis: { showticklabels: false, showgrid: false },
            yaxis: { showticklabels: false, showgrid: false },
            height: 30,
        }, { displayModeBar: false, staticPlot: true });
    });
}

function updateSparkline(name, value) {
    sparklineData[name].push(value);
    if (sparklineData[name].length > MAX_SPARKLINE_POINTS) {
        sparklineData[name].shift();
    }
    Plotly.update(
        document.getElementById(`sl-${name}`),
        { y: [sparklineData[name]] },
    );
}

// ============ Socket events ============
function connectSocket() {
    socket = io();
    
    socket.on("connect", () => {
        updateConnectionStatus("connected");
        socket.emit("join_session", { session_id: window.SESSION_ID });
    });
    
    socket.on("disconnect", () => updateConnectionStatus("disconnected"));
    
    socket.on("BAR_PROCESSED", e => {
        const p = e.payload;
        addCandle(p.timestamp, {
            open: p.open,
            high: p.high,
            low: p.low,
            close: p.close,
        });
    });
    
    socket.on("SIGNAL_GENERATED", e => {
        const p = e.payload;
        addSignalMarker(p.timestamp, p.tipo, p.preco);
        appendLog("SIGNAL", e.timestamp, 
            `${p.tipo} ${p.ticker} @ R$${p.preco.toFixed(2)} (${p.estrategia})`,
            p
        );
    });
    
    socket.on("SIGNAL_FILTERED", e => {
        const p = e.payload;
        appendLog("FILTER", e.timestamp,
            `Sinal bloqueado: ${p.filter_reason}`, p);
    });
    
    socket.on("TRADE_OPENED", e => {
        const p = e.payload;
        appendLog("ENTRY", e.timestamp,
            `Abriu ${p.side} ${p.ticker} ${p.size} @ R$${p.price.toFixed(2)}`, p);
    });
    
    socket.on("TRADE_CLOSED", e => {
        const p = e.payload;
        const pnlSign = p.realized_pnl >= 0 ? "+" : "";
        appendLog("EXIT", e.timestamp,
            `Fechou ${p.ticker} | P&L ${pnlSign}${p.realized_pnl.toFixed(2)} | ${p.exit_reason}`, p);
    });
    
    socket.on("METRICS_UPDATE", e => {
        updateMetrics(e.payload);
        updateProgress(e.payload.progress_pct);
    });
    
    socket.on("SESSION_ENDED", e => {
        appendLog(e.payload.status === "error" ? "ERROR" : "INFO",
            e.timestamp,
            `Sessão finalizada: ${e.payload.status}`, e.payload);
        showFinalizationModal(e.payload);
    });
}

// ============ Metrics update ============
function updateMetrics(m) {
    document.getElementById("m-equity").textContent = formatBRL(m.equity);
    document.getElementById("m-pnl").textContent = formatBRL(m.pnl);
    document.getElementById("m-dd").textContent = m.drawdown_capital_at_risk_pct.toFixed(2) + "%";
    document.getElementById("m-trades").textContent = m.n_trades;
    if (m.sharpe !== null) {
        document.getElementById("m-sharpe").textContent = m.sharpe.toFixed(2);
    }
    if (m.win_rate !== null) {
        document.getElementById("m-winrate").textContent = (m.win_rate * 100).toFixed(1) + "%";
    }
    
    updateSparkline("equity", m.equity);
    updateSparkline("pnl", m.pnl);
    updateSparkline("dd", m.drawdown_capital_at_risk_pct);
    
    // Cor dinâmica
    document.getElementById("m-pnl").style.color = m.pnl >= 0 ? "#26a69a" : "#ef5350";
}

// ============ Log ============
function appendLog(category, timestamp, message, payload) {
    const entry = { category, timestamp, message, payload };
    logBuffer.push(entry);
    if (logBuffer.length > MAX_LOG_ENTRIES) logBuffer.shift();
    
    if (!isCategoryVisible(category)) return;
    
    const log = document.getElementById("event-log");
    const div = document.createElement("div");
    div.className = `log-entry log-${category.toLowerCase()}`;
    div.dataset.category = category;
    
    const time = new Date(timestamp).toLocaleTimeString();
    div.innerHTML = `
        <span class="log-time">${time}</span>
        <span class="log-cat">${category}</span>
        <span class="log-msg">${escapeHtml(message)}</span>
        <details class="log-context">
            <summary>contexto</summary>
            <pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
        </details>
    `;
    log.appendChild(div);
    
    // Auto-scroll se já está no fundo
    if (log.scrollTop + log.clientHeight >= log.scrollHeight - 50) {
        log.scrollTop = log.scrollHeight;
    }
    
    // Trim DOM se cresceu demais
    while (log.children.length > MAX_LOG_ENTRIES) {
        log.removeChild(log.firstChild);
    }
}

function bindFilters() {
    document.querySelectorAll(".log-filters input").forEach(cb => {
        cb.addEventListener("change", () => {
            const cat = cb.dataset.cat;
            document.querySelectorAll(`.log-entry[data-category=${cat}]`)
                .forEach(el => el.style.display = cb.checked ? "" : "none");
        });
    });
}

function isCategoryVisible(category) {
    const cb = document.querySelector(`.log-filters input[data-cat=${category}]`);
    return cb ? cb.checked : true;
}

// ============ Commands ============
function sendCommand(action) {
    socket.emit("session_command", {
        session_id: window.SESSION_ID,
        command: { action: action },
    });
    
    if (action === "pause") {
        document.getElementById("btn-pause").disabled = true;
        document.getElementById("btn-resume").disabled = false;
    } else if (action === "resume") {
        document.getElementById("btn-pause").disabled = false;
        document.getElementById("btn-resume").disabled = true;
    }
}

function confirmAbort() {
    if (confirm("Abortar simulação? Esta ação não pode ser desfeita.")) {
        sendCommand("abort");
    }
}

// ============ Helpers ============
function formatBRL(v) {
    return "R$ " + v.toLocaleString("pt-BR", { 
        minimumFractionDigits: 2, 
        maximumFractionDigits: 2,
    });
}

function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
}

function updateProgress(pct) {
    document.getElementById("progress-fill").style.width = pct + "%";
    document.getElementById("progress-text").textContent = pct.toFixed(1) + "%";
}

function updateConnectionStatus(status) {
    const el = document.getElementById("conn-status");
    el.className = "connection-status status-" + status;
    el.title = status;
}

function showFinalizationModal(payload) {
    // Modal com link para relatório (implementado no Sprint 31)
    alert(`Sessão finalizada: ${payload.status}\nVer relatório completo em /sessions/${window.SESSION_ID}/report`);
}
```

### E3 — CSS `gui/static/css/live.css`

```css
/* === Container e layout === */
.live-container {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 60px);
    gap: 8px;
    padding: 8px;
    background: #131722;
    color: #d1d4dc;
}

.live-header {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px;
    background: #1e222d;
    border-radius: 4px;
}

.progress-bar {
    flex: 1;
    height: 24px;
    background: #2a2e39;
    border-radius: 12px;
    position: relative;
    overflow: hidden;
}

.progress-bar #progress-fill {
    height: 100%;
    background: linear-gradient(90deg, #26a69a, #4caf50);
    transition: width 0.3s ease;
}

.progress-bar #progress-text {
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    font-size: 12px;
    color: white;
}

.connection-status {
    font-size: 20px;
    color: #757575;
}
.status-connected { color: #26a69a; }
.status-disconnected { color: #ef5350; }

/* === Chart === */
.chart-section {
    flex: 1;
    min-height: 400px;
    background: #1e222d;
    border-radius: 4px;
    overflow: hidden;
}

.main-chart, .indicator-chart {
    width: 100%;
}

/* === Bottom panels === */
.bottom-section {
    display: grid;
    grid-template-columns: 1fr 1.5fr;
    gap: 8px;
    height: 40%;
}

.metrics-panel, .log-panel {
    background: #1e222d;
    border-radius: 4px;
    padding: 12px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.metric-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
    margin-top: 8px;
}

.metric-card {
    background: #2a2e39;
    padding: 8px;
    border-radius: 4px;
}

.metric-label {
    display: block;
    font-size: 11px;
    color: #758696;
    text-transform: uppercase;
}

.metric-value {
    display: block;
    font-size: 20px;
    font-weight: 600;
    margin: 4px 0;
}

.sparkline {
    height: 30px;
}

/* === Log === */
.log-filters {
    display: flex;
    gap: 12px;
    font-size: 12px;
    margin: 8px 0;
}

.event-log {
    flex: 1;
    overflow-y: auto;
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
    background: #131722;
    padding: 8px;
    border-radius: 4px;
}

.log-entry {
    padding: 4px;
    border-bottom: 1px solid #2a2e39;
    line-height: 1.5;
}

.log-time { color: #758696; margin-right: 8px; }
.log-cat {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    margin-right: 8px;
    font-weight: 600;
    font-size: 10px;
}

.log-signal .log-cat  { background: #2196f3; color: white; }
.log-entry .log-cat   { background: #26a69a; color: white; }
.log-exit .log-cat    { background: #ff9800; color: white; }
.log-filter .log-cat  { background: #757575; color: white; }
.log-error .log-cat   { background: #ef5350; color: white; }

.log-context summary {
    cursor: pointer;
    color: #758696;
    font-size: 10px;
}

.log-context pre {
    margin: 4px 0;
    padding: 4px 8px;
    background: #1e222d;
    border-radius: 3px;
    font-size: 11px;
    max-height: 200px;
    overflow: auto;
}
```

### E4 — Indicator chart sincronizado

Quando usuário seleciona indicador no dropdown:

```javascript
function showIndicator(name) {
    if (indicatorChart) {
        indicatorChart.remove();
        indicatorChart = null;
    }
    if (!name) return;
    
    const container = document.getElementById("indicator-chart");
    indicatorChart = LightweightCharts.createChart(container, {
        height: 120,
        // ... theme idêntico ao main chart
    });
    
    indicatorSeries = indicatorChart.addLineSeries({
        color: "#2196f3",
        lineWidth: 1.5,
    });
    
    // Sincronizar time scale
    chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        indicatorChart.timeScale().setVisibleLogicalRange(range);
    });
}
```

Backend deve emitir indicator values em `BAR_PROCESSED.payload.indicators`.

### E5 — Atualização do `ReplayRunner` (E1 do Sprint 28)

Adicionar ao `BAR_PROCESSED` payload os dados OHLC + indicadores:

```python
self.emit("BAR_PROCESSED", {
    "bar_index": i,
    "timestamp": int(current_ts.timestamp()),  # Unix epoch para Lightweight Charts
    "ticker": ticker,
    "open": float(current_bar["Open"].iloc[-1]),
    "high": float(current_bar["High"].iloc[-1]),
    "low": float(current_bar["Low"].iloc[-1]),
    "close": float(current_bar["Close"].iloc[-1]),
    "indicators": {
        "adx": float(current_bar["ADX"].iloc[-1]) if "ADX" in current_bar else None,
        "hurst": float(current_bar["Hurst"].iloc[-1]) if "Hurst" in current_bar else None,
        "rsi": float(current_bar["RSI"].iloc[-1]) if "RSI" in current_bar else None,
    },
})
```

### E6 — Reconexão e estado parcial

Quando cliente reconecta a sessão em curso:

```python
# gui/routes/live.py
@bp.route("/<session_id>/state")
def session_state(session_id):
    """REST endpoint que retorna estado atual da sessão."""
    repo = current_app.config["REPOSITORY"]
    
    # Últimas 500 barras + sinais + métricas
    return jsonify({
        "session": repo.get_session(session_id),
        "recent_signals": repo.list_signals(session_id, limit=200),
        "recent_trades": repo.list_trades(session_id, limit=50),
        "equity_curve": repo.get_equity_curve(session_id, limit=500),
    })
```

JS faz `fetch(/live/{id}/state)` ao conectar, popula chart e sparklines com dados históricos, então começa a receber novos eventos via socket.

### E7 — Testes

**`tests/e2e/test_live_panel.py`** (Playwright, mínimo 6 casos):

1. **Render**: página `/live/<id>` carrega sem erro JS.
2. **Chart aparece**: candle aparece após ~3 BAR_PROCESSED.
3. **Sinal renderiza**: marker aparece no chart após SIGNAL_GENERATED.
4. **Métrica atualiza**: após METRICS_UPDATE, valor é refletido na card.
5. **Log filter**: desmarcar categoria esconde entries.
6. **Reconexão**: refresh do browser durante sessão restaura estado.

**`tests/unit/test_replay_runner_payloads.py`** (mínimo 4 casos):

1. BAR_PROCESSED contém OHLC + indicadores.
2. SIGNAL_GENERATED contém context com indicadores.
3. METRICS_UPDATE contém todas as 7+ chaves esperadas.
4. SESSION_ENDED contém summary completo.

### E8 — Performance

Benchmark: sessão de 5000 barras (20 anos diários) em modo `instant`:
- Tempo total: < 60 segundos
- Memória JS: < 200 MB no browser
- DOM nodes do log: nunca passa de MAX_LOG_ENTRIES

---

## 4. Critério de Aceitação

- [ ] Suite completa passa (incluindo 10 novos testes)
- [ ] Página `/live/<id>` renderiza candlestick + métricas + log
- [ ] Cada SIGNAL_GENERATED produz seta no chart
- [ ] Trades produzem entradas no log com cores corretas
- [ ] Sinais filtrados aparecem no log (motivos visíveis)
- [ ] Sparklines atualizam suavemente
- [ ] Pause/resume/abort funcionam visualmente
- [ ] Filtros de log escondem/mostram categorias
- [ ] Reconexão após refresh restaura estado parcial
- [ ] Benchmark: 5000 barras em instant < 60s, browser estável

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Lightweight Charts API changes entre versões | Média | Pinar versão exata; copiar para `static/vendor/` se necessário |
| Performance ruim com muitos signals (>500 markers) | Média | Trim de markers antigos (já implementado); throttling |
| Sparklines Plotly lentas | Média | `staticPlot: true` evita event listeners; alternativa: Chart.js mini |
| Browser crash em sessão muito longa | Baixa | Ring buffer no DOM (já implementado) |
| Tema claro vs escuro | Baixa | Apenas escuro nesta versão; opção configurável em sprint futuro |

---

## 6. Notas para o Claude Code

- **Lightweight Charts v4** é a versão estável atual; documentação em https://tradingview.github.io/lightweight-charts/
- **Time format**: Lightweight Charts aceita Unix timestamp (segundos, não ms) OU ISO date string `"YYYY-MM-DD"`. Para intraday, usar timestamp.
- **Sincronização de time scales**: `subscribeVisibleLogicalRangeChange` propaga zoom/pan entre charts.
- **Ring buffer no DOM**: remover children antigos em vez de innerHTML='' (mais eficiente).
- **Throttle de métricas**: backend já emite a cada N barras (Sprint 28). Frontend não precisa fazer throttle adicional.
- **CSS variables** para tema: facilita ajustes finos depois.
- **Não usar React/Vue** ainda. HTMX + JS vanilla é suficiente e mais simples de debugar.

---

## 7. Comandos de validação

```bash
pytest tests/e2e/test_live_panel.py -v --headed
pytest tests/unit/test_replay_runner_payloads.py -v

# Benchmark manual
python -m gui.server
# Browser: replay 2005-2025 sobre ^BVSP, velocidade instant
# Verificar tempo total e estabilidade do browser

# Visual sanity check
# Configurar replay 2008-06 a 2009-06, ver o crash no chart
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — HTML do painel | 0.5 dia |
| E2 — live.js (núcleo) | 2-2.5 dias |
| E3 — CSS | 1 dia |
| E4 — indicator chart | 0.5 dia |
| E5 — runner payload update | 0.25 dia |
| E6 — reconexão (state endpoint) | 0.5-1 dia |
| E7 — testes (10 casos) | 1.5-2 dias |
| E8 — performance tuning | 0.5-1 dia |
| Buffer (cross-browser issues, polish) | 1-1.5 dias |
| **Total** | **8-10 dias** |
