# Sprint 30 — Histórico de Sessões e Comparação A/B

**Bloco**: III (Interface Gráfica)
**Duração estimada**: 5-7 dias úteis
**Pré-requisito**: Sprint 29 fechado (`v0.29.0`)
**Status**: pending
**Tag ao fechar**: `v0.30.0`

---

## 1. Contexto

Os sprints anteriores entregam configuração e observação ao vivo. Falta a peça que torna o uso **prático ao longo do tempo**: navegar pelo histórico de sessões já rodadas, encontrar a que importa, e comparar lado a lado configurações alternativas.

Sem essa funcionalidade, o usuário roda simulações soltas e perde o trabalho de comparação. Com ela, cada sessão vira evidência cumulativa em uma base de conhecimento.

A pergunta operacional que esta tela responde: **"Esta config é melhor que aquela?"** — sem precisar de planilha externa.

---

## 2. Objetivo

Construir `/sessions` com tabela filtrável + paginada, e `/compare?ids=A,B,C,D` com curvas sobrepostas e métricas lado a lado.

---

## 3. Entregáveis

### E1 — Rota `GET /sessions`

`gui/routes/sessions.py` expandido:

```python
from flask import Blueprint, render_template, request, current_app, jsonify

bp = Blueprint("sessions", __name__, url_prefix="/sessions")


@bp.route("/")
def list_sessions():
    repo = current_app.config["REPOSITORY"]
    
    # Query params para filtros
    filters = {
        "status": request.args.get("status"),
        "mode": request.args.get("mode"),
        "ticker": request.args.get("ticker"),
        "preset": request.args.get("preset"),
        "since": request.args.get("since"),
        "until": request.args.get("until"),
    }
    filters = {k: v for k, v in filters.items() if v}
    
    sort_by = request.args.get("sort", "started_at")
    sort_dir = request.args.get("dir", "desc")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    
    summaries = repo.list_session_summaries(
        filters=filters,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    
    total = repo.count_sessions(filters)
    
    return render_template(
        "sessions.html.j2",
        sessions=summaries,
        filters=filters,
        page=page,
        per_page=per_page,
        total=total,
        n_pages=(total + per_page - 1) // per_page,
    )


@bp.route("/<session_id>")
def session_detail(session_id):
    """Detail page (placeholder; full report no Sprint 31)."""
    repo = current_app.config["REPOSITORY"]
    session = repo.get_session(session_id)
    if not session:
        return "Not found", 404
    return render_template("session_detail.html.j2", session=session)


@bp.route("/<session_id>/rerun", methods=["POST"])
def rerun_session(session_id):
    """Re-executa sessão com mesma config."""
    repo = current_app.config["REPOSITORY"]
    mgr = current_app.config["SESSION_MANAGER"]
    
    original = repo.get_session(session_id)
    if not original:
        return jsonify({"error": "Session not found"}), 404
    
    from gui.runners.replay import ReplayRunner
    new_id = mgr.start_session(
        mode=original.mode,
        config=original.config,
        runner_cls=ReplayRunner,
    )
    return jsonify({"new_session_id": new_id})


@bp.route("/<session_id>/delete", methods=["POST"])
def delete_session(session_id):
    """Soft delete (marca como deletada; mantém audit trail)."""
    repo = current_app.config["REPOSITORY"]
    repo.soft_delete_session(session_id)
    return jsonify({"ok": True})
```

### E2 — Template `gui/templates/sessions.html.j2`

```html
{% extends "base.html.j2" %}
{% block title %}Sessões{% endblock %}
{% block content %}
<div class="sessions-container">
    <header class="sessions-header">
        <h1>Histórico de Sessões</h1>
        <div class="header-actions">
            <button id="btn-compare" onclick="compareSelected()" disabled>
                Comparar selecionadas (<span id="n-selected">0</span>)
            </button>
            <a href="{{ url_for('config.config_page') }}" class="btn-primary">
                + Nova Simulação
            </a>
        </div>
    </header>
    
    <form method="get" class="filters-bar">
        <select name="status">
            <option value="">Todos status</option>
            <option value="completed" {% if filters.status == "completed" %}selected{% endif %}>Completo</option>
            <option value="running">Rodando</option>
            <option value="aborted">Abortado</option>
            <option value="error">Erro</option>
        </select>
        <select name="mode">
            <option value="">Todos modos</option>
            <option value="replay">Replay</option>
            <option value="live">Live</option>
        </select>
        <input type="text" name="ticker" placeholder="Ticker" value="{{ filters.ticker or '' }}">
        <input type="date" name="since" value="{{ filters.since or '' }}">
        <input type="date" name="until" value="{{ filters.until or '' }}">
        <button type="submit">Filtrar</button>
        <a href="{{ url_for('sessions.list_sessions') }}">Limpar</a>
    </form>
    
    <table class="sessions-table">
        <thead>
            <tr>
                <th><input type="checkbox" id="select-all"></th>
                <th><a href="?sort=started_at&dir={% if filters.sort_dir == 'asc' %}desc{% else %}asc{% endif %}">Data ↕</a></th>
                <th>Tickers</th>
                <th>Modo</th>
                <th>Duração</th>
                <th><a href="?sort=total_pnl">P&L</a></th>
                <th><a href="?sort=sharpe">Sharpe</a></th>
                <th><a href="?sort=max_dd_car">MDD-CAR</a></th>
                <th><a href="?sort=max_dd_total">MDD-Total</a></th>
                <th>Trades</th>
                <th>Status</th>
                <th>Ações</th>
            </tr>
        </thead>
        <tbody>
        {% for s in sessions %}
            <tr data-session-id="{{ s.id }}">
                <td><input type="checkbox" class="select-row" value="{{ s.id }}"></td>
                <td>{{ s.started_at|datetimeformat }}</td>
                <td>{{ s.tickers|join(", ") }}</td>
                <td>{{ s.mode }}</td>
                <td>{{ s.duration_str }}</td>
                <td class="{% if s.total_pnl >= 0 %}positive{% else %}negative{% endif %}">
                    {{ s.total_pnl|currency }}
                </td>
                <td>{{ "%.2f"|format(s.sharpe) if s.sharpe else "—" }}</td>
                <td>{{ "%.2f%%"|format(s.max_dd_car) if s.max_dd_car else "—" }}</td>
                <td>{{ "%.2f%%"|format(s.max_dd_total) if s.max_dd_total else "—" }}</td>
                <td>{{ s.num_trades }}</td>
                <td><span class="status-badge status-{{ s.status }}">{{ s.status }}</span></td>
                <td class="actions">
                    <a href="{{ url_for('sessions.session_detail', session_id=s.id) }}" title="Ver">👁</a>
                    {% if s.status == 'completed' %}
                    <a href="{{ url_for('report.report_page', session_id=s.id) }}" title="Relatório">📄</a>
                    {% endif %}
                    <button onclick="rerunSession('{{ s.id }}')" title="Re-executar">⟳</button>
                    <button onclick="deleteSession('{{ s.id }}')" title="Excluir" class="danger">🗑</button>
                </td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    
    <nav class="pagination">
        {% if page > 1 %}
        <a href="?page={{ page - 1 }}">← Anterior</a>
        {% endif %}
        <span>Página {{ page }} de {{ n_pages }} ({{ total }} sessões)</span>
        {% if page < n_pages %}
        <a href="?page={{ page + 1 }}">Próxima →</a>
        {% endif %}
    </nav>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='js/sessions.js') }}"></script>
{% endblock %}
```

### E3 — JS `gui/static/js/sessions.js`

```javascript
let selectedSessions = new Set();
const MAX_COMPARE = 4;

document.getElementById("select-all").addEventListener("change", e => {
    document.querySelectorAll(".select-row").forEach(cb => {
        cb.checked = e.target.checked;
        toggleSelect(cb.value, cb.checked);
    });
});

document.querySelectorAll(".select-row").forEach(cb => {
    cb.addEventListener("change", e => toggleSelect(e.target.value, e.target.checked));
});

function toggleSelect(sessionId, checked) {
    if (checked) {
        if (selectedSessions.size >= MAX_COMPARE) {
            alert(`Máximo ${MAX_COMPARE} sessões para comparação`);
            document.querySelector(`.select-row[value='${sessionId}']`).checked = false;
            return;
        }
        selectedSessions.add(sessionId);
    } else {
        selectedSessions.delete(sessionId);
    }
    
    document.getElementById("n-selected").textContent = selectedSessions.size;
    document.getElementById("btn-compare").disabled = selectedSessions.size < 2;
}

function compareSelected() {
    if (selectedSessions.size < 2) return;
    const ids = Array.from(selectedSessions).join(",");
    window.location.href = `/compare?ids=${ids}`;
}

function rerunSession(sessionId) {
    if (!confirm("Re-executar com mesma config?")) return;
    fetch(`/sessions/${sessionId}/rerun`, { method: "POST" })
        .then(r => r.json())
        .then(data => {
            if (data.new_session_id) {
                window.location.href = `/live/${data.new_session_id}`;
            }
        });
}

function deleteSession(sessionId) {
    if (!confirm("Excluir esta sessão? (soft delete, audit trail preservado)")) return;
    fetch(`/sessions/${sessionId}/delete`, { method: "POST" })
        .then(() => {
            document.querySelector(`tr[data-session-id='${sessionId}']`).remove();
        });
}
```

### E4 — Rota `GET /compare`

`gui/routes/compare.py`:

```python
from flask import Blueprint, render_template, request, current_app

bp = Blueprint("compare", __name__)


@bp.route("/compare")
def compare_page():
    ids_param = request.args.get("ids", "")
    session_ids = [s.strip() for s in ids_param.split(",") if s.strip()]
    
    if len(session_ids) < 2:
        return "Pelo menos 2 sessões necessárias", 400
    if len(session_ids) > 4:
        return "Máximo 4 sessões", 400
    
    repo = current_app.config["REPOSITORY"]
    sessions_data = []
    for sid in session_ids:
        session = repo.get_session(sid)
        if not session:
            continue
        sessions_data.append({
            "session": session,
            "equity_curve": repo.get_equity_curve(sid),
            "trades": repo.list_trades(sid),
            "summary": repo.get_session_summary(sid),
        })
    
    return render_template("compare.html.j2", sessions_data=sessions_data)
```

### E5 — Template `gui/templates/compare.html.j2`

```html
{% extends "base.html.j2" %}
{% block title %}Comparação{% endblock %}
{% block content %}
<div class="compare-container">
    <header>
        <h1>Comparação de {{ sessions_data|length }} sessões</h1>
        <a href="{{ url_for('sessions.list_sessions') }}">← Voltar para Sessões</a>
    </header>
    
    <!-- Gráfico de equity sobreposto -->
    <section class="compare-chart">
        <h2>Curvas de Equity</h2>
        <div id="equity-chart" style="height: 500px;"></div>
    </section>
    
    <!-- Tabela de métricas lado a lado -->
    <section class="compare-metrics">
        <h2>Métricas</h2>
        <table>
            <thead>
                <tr>
                    <th>Métrica</th>
                    {% for d in sessions_data %}
                    <th>
                        <a href="{{ url_for('sessions.session_detail', session_id=d.session.id) }}">
                            {{ d.session.id[:8] }}
                        </a>
                        <br><small>{{ d.session.config.ticker }}</small>
                    </th>
                    {% endfor %}
                </tr>
            </thead>
            <tbody>
                <tr><td>Período</td>
                    {% for d in sessions_data %}<td>{{ d.session.config.start_date }} → {{ d.session.config.end_date }}</td>{% endfor %}
                </tr>
                <tr><td>P&L Total</td>
                    {% for d in sessions_data %}<td>{{ d.summary.total_pnl|currency }}</td>{% endfor %}
                </tr>
                <tr><td>Sharpe</td>
                    {% for d in sessions_data %}<td>{{ "%.2f"|format(d.summary.sharpe) }}</td>{% endfor %}
                </tr>
                <tr><td>Profit Factor</td>
                    {% for d in sessions_data %}<td>{{ "%.2f"|format(d.summary.profit_factor) }}</td>{% endfor %}
                </tr>
                <tr><td>Win Rate</td>
                    {% for d in sessions_data %}<td>{{ "%.1f%%"|format(d.summary.win_rate * 100) }}</td>{% endfor %}
                </tr>
                <tr><td>MDD (Capital-at-Risk)</td>
                    {% for d in sessions_data %}<td>{{ "%.2f%%"|format(d.summary.max_dd_car) }}</td>{% endfor %}
                </tr>
                <tr><td>MDD (Total)</td>
                    {% for d in sessions_data %}<td>{{ "%.2f%%"|format(d.summary.max_dd_total) }}</td>{% endfor %}
                </tr>
                <tr><td>Time in Market</td>
                    {% for d in sessions_data %}<td>{{ "%.1f%%"|format(d.summary.time_in_market_pct) }}</td>{% endfor %}
                </tr>
                <tr><td>Nº Trades</td>
                    {% for d in sessions_data %}<td>{{ d.summary.num_trades }}</td>{% endfor %}
                </tr>
                <tr><td>Sinais bloqueados</td>
                    {% for d in sessions_data %}<td>{{ d.summary.num_filtered }} / {{ d.summary.num_signals }}</td>{% endfor %}
                </tr>
            </tbody>
        </table>
    </section>
    
    <!-- Distribuição de trades comparativa -->
    <section class="compare-trade-dist">
        <h2>Distribuição de P&L por Trade</h2>
        <div id="trade-histogram" style="height: 400px;"></div>
    </section>
    
    <!-- Diff de config -->
    <section class="compare-config-diff">
        <h2>Diferenças de Configuração</h2>
        <div id="config-diff"></div>
    </section>
</div>
{% endblock %}

{% block scripts %}
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script>
window.SESSIONS_DATA = {{ sessions_data|tojson }};
</script>
<script src="{{ url_for('static', filename='js/compare.js') }}"></script>
{% endblock %}
```

### E6 — JS `gui/static/js/compare.js`

```javascript
const COLORS = ["#26a69a", "#ef5350", "#2196f3", "#ff9800"];

function init() {
    plotEquityCurves();
    plotTradeHistogram();
    renderConfigDiff();
}

function plotEquityCurves() {
    const traces = window.SESSIONS_DATA.map((d, i) => ({
        x: d.equity_curve.map(p => p.timestamp),
        y: d.equity_curve.map(p => p.equity),
        type: "scatter",
        mode: "lines",
        name: `${d.session.id.slice(0,8)} (${d.session.config.ticker})`,
        line: { color: COLORS[i], width: 2 },
    }));
    
    Plotly.newPlot("equity-chart", traces, {
        title: "Curvas de Equity Sobrepostas",
        xaxis: { title: "Data" },
        yaxis: { title: "Equity (R$)" },
        hovermode: "x unified",
        showlegend: true,
        paper_bgcolor: "#1e222d",
        plot_bgcolor: "#131722",
        font: { color: "#d1d4dc" },
    });
}

function plotTradeHistogram() {
    const traces = window.SESSIONS_DATA.map((d, i) => ({
        x: d.trades.map(t => t.realized_pnl).filter(p => p !== null),
        type: "histogram",
        name: d.session.id.slice(0, 8),
        opacity: 0.6,
        marker: { color: COLORS[i] },
        nbinsx: 30,
    }));
    
    Plotly.newPlot("trade-histogram", traces, {
        title: "P&L por Trade",
        xaxis: { title: "P&L (R$)" },
        yaxis: { title: "Frequência" },
        barmode: "overlay",
        paper_bgcolor: "#1e222d",
        plot_bgcolor: "#131722",
        font: { color: "#d1d4dc" },
    });
}

function renderConfigDiff() {
    /**
     * Compara configs das sessões; mostra apenas chaves que diferem.
     */
    const sessions = window.SESSIONS_DATA;
    const allKeys = new Set();
    sessions.forEach(s => {
        Object.keys(s.session.config).forEach(k => allKeys.add(k));
        if (s.session.config.strategy_params) {
            Object.keys(s.session.config.strategy_params).forEach(k => allKeys.add(`strategy_params.${k}`));
        }
    });
    
    const diffRows = [];
    for (const key of allKeys) {
        const values = sessions.map(s => getNestedValue(s.session.config, key));
        const allEqual = values.every(v => JSON.stringify(v) === JSON.stringify(values[0]));
        if (!allEqual) {
            diffRows.push({ key, values });
        }
    }
    
    const div = document.getElementById("config-diff");
    if (diffRows.length === 0) {
        div.innerHTML = "<p><em>Configurações idênticas.</em></p>";
        return;
    }
    
    let html = "<table><thead><tr><th>Parâmetro</th>";
    sessions.forEach(s => html += `<th>${s.session.id.slice(0,8)}</th>`);
    html += "</tr></thead><tbody>";
    
    for (const row of diffRows) {
        html += `<tr><td><code>${row.key}</code></td>`;
        row.values.forEach(v => html += `<td>${JSON.stringify(v)}</td>`);
        html += "</tr>";
    }
    html += "</tbody></table>";
    div.innerHTML = html;
}

function getNestedValue(obj, path) {
    return path.split(".").reduce((o, k) => o?.[k], obj);
}

init();
```

### E7 — Repository methods

Adicionar em `db/repository.py`:

```python
def list_session_summaries(
    self,
    filters: dict = None,
    sort_by: str = "started_at",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Usa view v_session_summary com filtros dinâmicos.
    """
    ...

def count_sessions(self, filters: dict = None) -> int: ...

def soft_delete_session(self, session_id: str) -> None:
    """Marca como deletada (adicionar coluna `deleted_at` ao schema)."""
    ...
```

Schema change: adicionar `deleted_at TEXT` a `sessions`. Migration script.

### E8 — Testes

**`tests/integration/test_sessions_list.py`** (mínimo 6 casos):

1. **Listagem sem filtros** retorna sessões ordenadas por data.
2. **Filtro por status** funciona.
3. **Filtro por ticker** funciona.
4. **Paginação**: page=2 com per_page=10 retorna 11-20.
5. **Soft delete**: sessão deletada não aparece na listagem (mas existe no DB).
6. **Sort by sharpe asc** ordena corretamente.

**`tests/e2e/test_compare.py`** (mínimo 4 casos):

1. **Compare 2 sessões**: chart com 2 traces, tabela com 2 colunas.
2. **Compare 4 sessões**: chart com 4 traces, tabela com 4 colunas.
3. **Config diff** identifica apenas chaves divergentes.
4. **Compare 1 sessão** retorna erro 400.

---

## 4. Critério de Aceitação

- [ ] Suite completa passa (incluindo 10 novos testes)
- [ ] `/sessions` lista todas com paginação
- [ ] Filtros por status, mode, ticker, datas funcionam
- [ ] Ordenação por qualquer coluna funciona
- [ ] Selecionar 2-4 sessões habilita botão de comparação
- [ ] `/compare?ids=A,B,C,D` renderiza chart sobreposto + tabela + diff
- [ ] Re-executar sessão dispara nova com mesma config
- [ ] Soft delete preserva audit trail mas remove da listagem

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Plotly lento com curvas muito longas | Média | Downsample para 1000 pontos antes de plotar |
| Comparação > 4 sessões fica visualmente ruim | Confirmada | Limite hard de 4 implementado |
| Soft delete polui queries | Média | Filtro `WHERE deleted_at IS NULL` em todas as listings |
| Config diff complexo (nested objects) | Média | `getNestedValue` recursivo; limite de profundidade 3 |

---

## 6. Notas para o Claude Code

- **Downsampling de curvas**: se equity_curve tem > 2000 pontos, fazer LTTB (Largest Triangle Three Buckets) para 1000 pontos. Implementar em Python ou JS.
- **Filtros via URL params**: bookmarkable. Não usar formulário POST.
- **Não usar DataTables.js**: simplicidade primeiro. Server-side rendering com filtros em URL.
- **Ordenação**: clicks no header atualizam `?sort=col&dir=asc|desc`.
- **Config diff**: comparar JSON estruturado, não strings. Trees aninhadas com dot notation.
- **Soft delete**: nunca DELETE real — preserva audit trail e permite restore manual via SQL.

---

## 7. Comandos de validação

```bash
pytest tests/integration/test_sessions_list.py -v
pytest tests/e2e/test_compare.py -v --headed

# Manual: criar 4 sessões diferentes, comparar
python -m gui.server
# Browser: /sessions, marcar 4, clicar Comparar
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — rotas sessions | 0.5 dia |
| E2 — template sessions | 0.5-1 dia |
| E3 — sessions.js | 0.5 dia |
| E4 — rota compare | 0.25 dia |
| E5 — template compare | 0.5-1 dia |
| E6 — compare.js (3 charts + diff) | 1-1.5 dias |
| E7 — repository methods | 0.5 dia |
| E8 — testes | 1-1.5 dias |
| Buffer (polish, edge cases) | 0.5-1 dia |
| **Total** | **5-7 dias** |
