# Sprint 31 — Relatórios de Sessão (HTML standalone + PDF)

**Bloco**: III (Interface Gráfica)
**Duração estimada**: 6-8 dias úteis
**Pré-requisito**: Sprint 30 fechado (`v0.30.0`)
**Status**: pending
**Tag ao fechar**: `v0.31.0`

---

## 1. Contexto

Até aqui, o usuário pode rodar simulações, observar em tempo real, comparar resultados na UI. Falta o **entregável que justifica a existência do produto**: um relatório completo, navegável, exportável, que responde com clareza "qual foi a performance, e por quê?".

O relatório precisa ser:
- **Completo** — incluindo dados que normalmente são deixados de fora (sinais filtrados, contas a duas bases de MDD)
- **Standalone** — abre sem servidor, todos os assets inline
- **Auditável** — referencia o session_id, audit_log file, configs específicas
- **Honesto** — banner condicional baseado no resultado do Marco do Bloco I

---

## 2. Objetivo

Gerar relatório completo em HTML standalone e PDF, com 9 seções fixas. Refletir o cenário definido em `findings/MARCO_BLOCO_I.md` (produto / laboratório / rework).

---

## 3. Entregáveis

### E1 — Determinação do banner condicional

`report_banner.py`:

```python
from enum import Enum
from pathlib import Path


class ProductCenario(str, Enum):
    PRODUTO = "produto"          # Cenário A — Marco do Bloco I
    LABORATORIO = "laboratorio"  # Cenário B
    REWORK = "rework"             # Cenário C
    UNDETERMINED = "undetermined" # Marco ainda não tomado


BANNER_HTML = {
    ProductCenario.PRODUTO: """
        <div class="banner banner-green">
            <strong>Sistema validado para uso de pesquisa.</strong>
            Auditoria do Bloco I (Sprints 18-22) confirmou alpha incremental e robustez.
            Métricas reportadas representam performance esperada em OOS.
        </div>
    """,
    ProductCenario.LABORATORIO: """
        <div class="banner banner-yellow">
            <strong>Ferramenta de pesquisa — não recomendada para operação real.</strong>
            Auditoria revelou que parte do alpha reportado é explicado por exposição a fatores conhecidos.
            Use este relatório para análise comparativa, não como base de decisão de capital.
        </div>
    """,
    ProductCenario.REWORK: """
        <div class="banner banner-red">
            <strong>Sistema em rework — resultados não confiáveis.</strong>
            Auditoria revelou problemas estruturais. Resultados aqui são para fins de debugging apenas.
        </div>
    """,
    ProductCenario.UNDETERMINED: """
        <div class="banner banner-gray">
            Auditoria do Bloco I ainda não foi finalizada. Métricas devem ser interpretadas com cautela.
        </div>
    """,
}


def get_current_cenario() -> ProductCenario:
    """
    Lê findings/MARCO_BLOCO_I.md, extrai cenário declarado.
    
    O arquivo deve ter linha:
        CENARIO_FINAL: <produto|laboratorio|rework>
    """
    marco_file = Path("findings/MARCO_BLOCO_I.md")
    if not marco_file.exists():
        return ProductCenario.UNDETERMINED
    
    content = marco_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.startswith("CENARIO_FINAL:"):
            value = line.split(":", 1)[1].strip().lower()
            try:
                return ProductCenario(value)
            except ValueError:
                pass
    return ProductCenario.UNDETERMINED


def get_banner_html() -> str:
    return BANNER_HTML[get_current_cenario()]
```

### E2 — Template `gui/templates/report.html.j2`

Estrutura completa em 9 seções:

```html
{% extends "base.html.j2" %}
{% block title %}Relatório — {{ session.id[:8] }}{% endblock %}

{% block content %}
<div class="report">
    {{ banner_html|safe }}
    
    <!-- ============ Seção 1: Cabeçalho ============ -->
    <header class="report-header">
        <h1>Relatório de Sessão</h1>
        <table class="header-info">
            <tr>
                <th>ID</th><td><code>{{ session.id }}</code></td>
                <th>Modo</th><td>{{ session.mode|upper }}</td>
            </tr>
            <tr>
                <th>Início</th><td>{{ session.started_at|datetimeformat }}</td>
                <th>Fim</th><td>{{ session.ended_at|datetimeformat }}</td>
            </tr>
            <tr>
                <th>Status</th><td><span class="status-{{ session.status }}">{{ session.status }}</span></td>
                <th>Duração simulada</th><td>{{ session.config.start_date }} → {{ session.config.end_date }}</td>
            </tr>
            <tr>
                <th>Ticker(s)</th><td colspan="3">{{ session.config.ticker }}</td>
            </tr>
        </table>
        
        <details>
            <summary>Configuração completa</summary>
            <pre>{{ session.config|tojson(indent=2) }}</pre>
        </details>
    </header>
    
    <!-- ============ Seção 2: Sumário de performance ============ -->
    <section id="sec-performance">
        <h2>2. Sumário de Performance</h2>
        <table class="metrics-table">
            <tr><th>Sharpe Ratio</th><td>{{ "%.2f"|format(metrics.sharpe) }}</td>
                <th>Sortino Ratio</th><td>{{ "%.2f"|format(metrics.sortino) }}</td></tr>
            <tr><th>Calmar Ratio</th><td>{{ "%.2f"|format(metrics.calmar) }}</td>
                <th>Profit Factor</th><td>{{ "%.2f"|format(metrics.profit_factor) }}</td></tr>
            <tr><th>Win Rate</th><td>{{ "%.1f%%"|format(metrics.win_rate * 100) }}</td>
                <th>Expectativa/trade</th><td>{{ metrics.expectancy|currency }}</td></tr>
            <tr><th>MDD (Equity Total)</th><td>{{ "%.2f%%"|format(metrics.max_dd_total) }}</td>
                <th>MDD (Capital-at-Risk)</th><td><strong>{{ "%.2f%%"|format(metrics.max_dd_car) }}</strong></td></tr>
            <tr><th>CAGR</th><td>{{ "%.2f%%"|format(metrics.cagr) }}</td>
                <th>Total Return</th><td>{{ "%.2f%%"|format(metrics.total_return_pct) }}</td></tr>
            <tr><th>Time in Market</th><td>{{ "%.1f%%"|format(metrics.time_in_market_pct) }}</td>
                <th>Capital Final</th><td>{{ metrics.final_equity|currency }}</td></tr>
        </table>
        
        <p class="note">
            <strong>Nota:</strong> MDD (Capital-at-Risk) considera apenas o capital efetivamente exposto.
            MDD (Equity Total) inclui caixa ocioso e tipicamente é menor.
            Para operação real, considerar primariamente o MDD-CAR.
        </p>
    </section>
    
    <!-- ============ Seção 3: Curva de equity ============ -->
    <section id="sec-equity">
        <h2>3. Curva de Equity e Drawdown</h2>
        <img src="data:image/png;base64,{{ chart_equity_b64 }}" alt="Equity curve">
        <details>
            <summary>Dados brutos</summary>
            <p>{{ equity_curve|length }} pontos amostrados</p>
        </details>
    </section>
    
    <!-- ============ Seção 4: Distribuição de trades ============ -->
    <section id="sec-trades">
        <h2>4. Distribuição de Trades</h2>
        <div class="grid-2">
            <img src="data:image/png;base64,{{ chart_pnl_hist_b64 }}" alt="P&L histogram">
            <img src="data:image/png;base64,{{ chart_holding_b64 }}" alt="Holding period">
        </div>
        <table class="summary-table">
            <tr><th>Total de trades</th><td>{{ trade_stats.n }}</td></tr>
            <tr><th>Vencedores</th><td>{{ trade_stats.n_wins }} ({{ "%.1f%%"|format(trade_stats.win_rate * 100) }})</td></tr>
            <tr><th>Perdedores</th><td>{{ trade_stats.n_losses }} ({{ "%.1f%%"|format((1 - trade_stats.win_rate) * 100) }})</td></tr>
            <tr><th>Avg Win</th><td>{{ trade_stats.avg_win|currency }}</td></tr>
            <tr><th>Avg Loss</th><td>{{ trade_stats.avg_loss|currency }}</td></tr>
            <tr><th>Maior Win</th><td>{{ trade_stats.max_win|currency }}</td></tr>
            <tr><th>Maior Loss</th><td>{{ trade_stats.max_loss|currency }}</td></tr>
            <tr><th>Avg Holding</th><td>{{ trade_stats.avg_holding_bars }} bars</td></tr>
        </table>
    </section>
    
    <!-- ============ Seção 5: Decomposição por ticker ============ -->
    {% if is_multi_ticker %}
    <section id="sec-ticker-decomp">
        <h2>5. Decomposição por Ticker</h2>
        <table>
            <thead>
                <tr><th>Ticker</th><th>Trades</th><th>P&L</th><th>Sharpe</th><th>Win Rate</th></tr>
            </thead>
            <tbody>
                {% for tk, st in ticker_breakdown.items() %}
                <tr><td>{{ tk }}</td><td>{{ st.n_trades }}</td>
                    <td>{{ st.pnl|currency }}</td>
                    <td>{{ "%.2f"|format(st.sharpe) }}</td>
                    <td>{{ "%.1f%%"|format(st.win_rate * 100) }}</td></tr>
                {% endfor %}
            </tbody>
        </table>
        <img src="data:image/png;base64,{{ chart_ticker_contrib_b64 }}" alt="Contribuição por ticker">
    </section>
    {% endif %}
    
    <!-- ============ Seção 6: Análise de filtros ============ -->
    <section id="sec-filters">
        <h2>6. Análise de Filtros (decisões de NÃO-trade)</h2>
        <p class="note">
            Esta seção é frequentemente omitida em relatórios comerciais. Aqui é crítica:
            saber quando e por que o sistema escolheu <em>não operar</em> é tão importante quanto saber quando operou.
        </p>
        <table>
            <thead>
                <tr><th>Categoria de filtro</th><th>Sinais bloqueados</th><th>%</th></tr>
            </thead>
            <tbody>
                {% for cat, count in filter_breakdown.items() %}
                <tr><td>{{ cat }}</td><td>{{ count }}</td>
                    <td>{{ "%.1f%%"|format(100 * count / filter_total) }}</td></tr>
                {% endfor %}
                <tr class="total-row">
                    <td><strong>Total bloqueado</strong></td>
                    <td>{{ filter_total }}</td>
                    <td>{{ "%.1f%%"|format(100 * filter_total / (filter_total + n_executed_signals)) }}</td>
                </tr>
            </tbody>
        </table>
        <p>
            De {{ filter_total + n_executed_signals }} sinais brutos gerados,
            {{ filter_total }} foram bloqueados ({{ "%.1f%%"|format(100 * filter_total / (filter_total + n_executed_signals)) }})
            e {{ n_executed_signals }} resultaram em entrada.
        </p>
    </section>
    
    <!-- ============ Seção 7: Comparação com Buy-and-Hold ============ -->
    <section id="sec-bnh">
        <h2>7. Comparação com Buy-and-Hold</h2>
        <table>
            <tr>
                <th></th>
                <th>Sistema</th>
                <th>B&H</th>
                <th>Diferença</th>
            </tr>
            <tr><td>Total Return</td>
                <td>{{ "%.2f%%"|format(metrics.total_return_pct) }}</td>
                <td>{{ "%.2f%%"|format(bnh_metrics.total_return_pct) }}</td>
                <td class="{% if metrics.total_return_pct > bnh_metrics.total_return_pct %}positive{% else %}negative{% endif %}">
                    {{ "%+.2fpp"|format(metrics.total_return_pct - bnh_metrics.total_return_pct) }}
                </td>
            </tr>
            <tr><td>Sharpe</td>
                <td>{{ "%.2f"|format(metrics.sharpe) }}</td>
                <td>{{ "%.2f"|format(bnh_metrics.sharpe) }}</td>
                <td>{{ "%+.2f"|format(metrics.sharpe - bnh_metrics.sharpe) }}</td>
            </tr>
            <tr><td>MDD (CAR)</td>
                <td>{{ "%.2f%%"|format(metrics.max_dd_car) }}</td>
                <td>{{ "%.2f%%"|format(bnh_metrics.max_dd) }}</td>
                <td>{{ "%+.2fpp"|format(metrics.max_dd_car - bnh_metrics.max_dd) }}</td>
            </tr>
            <tr><td>Beta</td>
                <td>{{ "%.2f"|format(factor_metrics.beta) }}</td>
                <td>1.00</td>
                <td>—</td>
            </tr>
            <tr><td>Alpha (anual)</td>
                <td>{{ "%.2f%%"|format(factor_metrics.alpha_annual * 100) }}</td>
                <td>—</td>
                <td>p-value: {{ "%.3f"|format(factor_metrics.alpha_pvalue) }}</td>
            </tr>
            <tr><td>Correlation</td>
                <td colspan="3">{{ "%.2f"|format(factor_metrics.correlation) }}</td>
            </tr>
        </table>
        <img src="data:image/png;base64,{{ chart_system_vs_bnh_b64 }}" alt="Sistema vs B&H">
    </section>
    
    <!-- ============ Seção 8: Log completo ============ -->
    <section id="sec-log">
        <h2>8. Log Completo de Eventos</h2>
        <p>{{ events|length }} eventos registrados.</p>
        <div class="log-filter-controls">
            <input type="search" id="log-search" placeholder="Filtrar...">
            <select id="log-cat-filter">
                <option value="">Todas categorias</option>
                <option value="SIGNAL">Sinais</option>
                <option value="ENTRY">Entradas</option>
                <option value="EXIT">Saídas</option>
                <option value="FILTER">Filtros</option>
            </select>
        </div>
        <table class="event-log-table" id="event-log-table">
            <thead><tr><th>Timestamp</th><th>Categoria</th><th>Mensagem</th></tr></thead>
            <tbody>
                {% for evt in events %}
                <tr data-cat="{{ evt.category }}">
                    <td>{{ evt.timestamp|datetimeformat }}</td>
                    <td><span class="cat-badge cat-{{ evt.category|lower }}">{{ evt.category }}</span></td>
                    <td>{{ evt.message }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </section>
    
    <!-- ============ Seção 9: Limitações e disclaimers ============ -->
    <section id="sec-disclaimers">
        <h2>9. Limitações e Notas Metodológicas</h2>
        <ul>
            <li>
                <strong>Custos modelados:</strong> 
                comissão {{ "%.3f%%"|format(session.config.commission * 100) }},
                slippage {{ "%.3f%%"|format(session.config.slippage * 100) }}.
                Custos reais podem ser 2-5× maiores em ativos pouco líquidos ou sizes grandes.
                Ver Sprint 19 (Sensibilidade a Custos) para análise detalhada.
            </li>
            <li>
                <strong>Fonte de dados:</strong> Yahoo Finance via yfinance.
                Dados intraday têm latência típica de 15-20 minutos no mercado brasileiro.
                Splits e dividendos são ajustados pela própria fonte.
            </li>
            <li>
                <strong>Determinismo:</strong> esta simulação é totalmente reprodutível.
                <code>session_id={{ session.id }}</code>.
                <code>audit_log={{ session.audit_log_file }}</code>.
            </li>
            <li>
                <strong>Diferença simulação ↔ real:</strong>
                paper trading não captura impacto de mercado, partial fills realísticos,
                rejeição de ordens, ou latência da corretora.
            </li>
            <li>
                <strong>Walk-forward honesto:</strong> 
                {% if session.config.strategy_params.get("validated_by_walkforward") %}
                config validada via re-otimização honesta (Sprint 21).
                {% else %}
                config NÃO validada via re-otimização honesta. Sharpe IS pode estar inflado.
                {% endif %}
            </li>
        </ul>
        
        <footer class="report-footer">
            <p>
                Relatório gerado em {{ generated_at|datetimeformat }}<br>
                Versão do sistema: {{ system_version }}<br>
                Tag do banco de dados: <code>{{ db_schema_version }}</code>
            </p>
        </footer>
    </section>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='js/report.js') }}"></script>
{% endblock %}
```

### E3 — Geração de gráficos estáticos

`gui/report_generator.py`:

```python
import io
import base64
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")  # backend não-interativo


class ReportGenerator:
    """Gera todos os artefatos visuais de um relatório."""
    
    def __init__(self, session_id: str, repository):
        self.session_id = session_id
        self.repo = repository
        self.session = repo.get_session(session_id)
        self.metrics = repo.get_session_summary(session_id)
        self.trades = repo.list_trades(session_id)
        self.events = list(repo.list_events(session_id))
        self.equity = repo.get_equity_curve(session_id)
    
    def generate_all(self) -> dict:
        """Gera todos os charts, retorna dict com base64-encoded PNGs."""
        return {
            "chart_equity_b64": self._plot_equity(),
            "chart_pnl_hist_b64": self._plot_pnl_hist(),
            "chart_holding_b64": self._plot_holding(),
            "chart_system_vs_bnh_b64": self._plot_system_vs_bnh(),
            "chart_ticker_contrib_b64": self._plot_ticker_contrib() if self._is_multi_ticker() else None,
        }
    
    def _fig_to_b64(self, fig) -> str:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#1e222d")
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    
    def _plot_equity(self) -> str:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), 
                                         gridspec_kw={"height_ratios": [2, 1]},
                                         facecolor="#1e222d")
        # Equity
        timestamps = [pd.Timestamp(p["timestamp"]) for p in self.equity]
        equity = [p["equity"] for p in self.equity]
        ax1.plot(timestamps, equity, color="#26a69a", linewidth=1.5)
        ax1.set_title("Curva de Equity", color="white")
        ax1.set_facecolor("#131722")
        ax1.tick_params(colors="white")
        ax1.grid(color="#2a2e39", alpha=0.5)
        
        # Drawdown
        dd = [p["drawdown_capital_at_risk_pct"] for p in self.equity]
        ax2.fill_between(timestamps, 0, [-d for d in dd], color="#ef5350", alpha=0.6)
        ax2.set_title("Drawdown (Capital-at-Risk)", color="white")
        ax2.set_facecolor("#131722")
        ax2.tick_params(colors="white")
        ax2.grid(color="#2a2e39", alpha=0.5)
        
        return self._fig_to_b64(fig)
    
    # ... outros métodos análogos
    
    def compute_trade_stats(self) -> dict: ...
    def compute_filter_breakdown(self) -> dict: ...
    def compute_bnh_comparison(self) -> dict: ...
    def compute_factor_metrics(self) -> dict: ...
```

### E4 — Rota `GET /sessions/<id>/report`

```python
# gui/routes/report.py
from flask import Blueprint, render_template, current_app, abort
from datetime import datetime
from report_banner import get_banner_html
from gui.report_generator import ReportGenerator

bp = Blueprint("report", __name__, url_prefix="/sessions")


@bp.route("/<session_id>/report")
def report_page(session_id: str):
    repo = current_app.config["REPOSITORY"]
    session = repo.get_session(session_id)
    if not session:
        abort(404)
    if session.status not in ("completed", "aborted"):
        return render_template("report_not_ready.html.j2", session=session)
    
    gen = ReportGenerator(session_id, repo)
    charts = gen.generate_all()
    
    context = {
        "session": session,
        "metrics": gen.metrics,
        "trade_stats": gen.compute_trade_stats(),
        "filter_breakdown": gen.compute_filter_breakdown(),
        "n_executed_signals": gen.n_executed_signals,
        "filter_total": gen.filter_total,
        "bnh_metrics": gen.compute_bnh_comparison(),
        "factor_metrics": gen.compute_factor_metrics(),
        "events": gen.events,
        "equity_curve": gen.equity,
        "is_multi_ticker": gen._is_multi_ticker(),
        "ticker_breakdown": gen.compute_ticker_breakdown() if gen._is_multi_ticker() else None,
        "banner_html": get_banner_html(),
        "generated_at": datetime.utcnow(),
        "system_version": "0.31.0",
        "db_schema_version": 1,
        **charts,
    }
    
    return render_template("report.html.j2", **context)
```

### E5 — Export HTML standalone

```python
@bp.route("/<session_id>/report/export/html")
def export_html(session_id: str):
    """HTML standalone com todos assets inline."""
    # Renderiza template normalmente
    html_content = render_template("report_standalone.html.j2", ...)
    
    # Inline CSS, JS, fontes
    inlined = inline_external_assets(html_content)
    
    return Response(
        inlined,
        mimetype="text/html",
        headers={
            "Content-Disposition": f'attachment; filename="report_{session_id[:8]}.html"',
        },
    )
```

`report_standalone.html.j2` é como o normal mas sem `{% extends %}` — tudo inline.

### E6 — Export PDF via Playwright

```python
@bp.route("/<session_id>/report/export/pdf")
def export_pdf(session_id: str):
    """PDF via Playwright print-to-PDF."""
    from playwright.sync_api import sync_playwright
    
    report_url = url_for("report.report_page", session_id=session_id, _external=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(report_url)
        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"},
        )
        browser.close()
    
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="report_{session_id[:8]}.pdf"',
        },
    )
```

### E7 — JS `gui/static/js/report.js`

```javascript
// Filtro de log na página de relatório
document.getElementById("log-search").addEventListener("input", filterLog);
document.getElementById("log-cat-filter").addEventListener("change", filterLog);

function filterLog() {
    const search = document.getElementById("log-search").value.toLowerCase();
    const cat = document.getElementById("log-cat-filter").value;
    
    document.querySelectorAll("#event-log-table tbody tr").forEach(row => {
        const text = row.textContent.toLowerCase();
        const rowCat = row.dataset.cat;
        const matchesSearch = !search || text.includes(search);
        const matchesCat = !cat || rowCat === cat;
        row.style.display = matchesSearch && matchesCat ? "" : "none";
    });
}
```

### E8 — Testes

**`tests/unit/test_report_generator.py`** (mínimo 6 casos):

1. **Geração completa**: ReportGenerator produz todas as chaves esperadas.
2. **Charts não vazios**: cada base64 tem mais que 100 caracteres.
3. **Multi-ticker detection**: corretamente identifica sessões com múltiplos tickers.
4. **Trade stats**: avg_win, avg_loss calculados corretamente.
5. **Filter breakdown**: contagem por categoria correta.
6. **B&H comparison**: para sessão sintética long-only durante uptrend, sistema bate ou empata B&H.

**`tests/e2e/test_report_export.py`** (mínimo 4 casos):

1. **HTML standalone**: arquivo exportado tem >50KB, abre sem servidor.
2. **PDF**: arquivo exportado tem páginas válidas.
3. **Banner condicional**: alterar MARCO_BLOCO_I.md muda banner no relatório.
4. **Sessão incompleta**: status='running' retorna página "not ready".

### E9 — Documentação `docs/REPORTS.md`

Documenta:
- Estrutura das 9 seções
- Como interpretar cada métrica
- Diferença entre 3 banners
- Como exportar e arquivar relatórios

---

## 4. Critério de Aceitação

- [ ] Suite completa passa (incluindo 10 novos testes)
- [ ] Relatório de sessão real tem todas as 9 seções renderizadas
- [ ] Banner condicional muda conforme MARCO_BLOCO_I.md
- [ ] Export HTML standalone abre sem servidor (testar abrindo arquivo .html offline)
- [ ] Export PDF gera arquivo válido (≥ 5 páginas para sessão típica)
- [ ] Seção de "filtros" mostra decisões de NÃO-trade explicitamente
- [ ] MDD em duas bases (CAR e Total) aparece com label e nota explicativa
- [ ] Relatório é informacionalmente equivalente OU superior ao `bear_market_validation.py` atual

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Playwright pesado para instalação | Alta | Documentar; tornar PDF export opcional |
| HTML standalone muito grande (>5MB) | Média | Otimizar PNGs (dpi 100 em vez de 150); avaliar SVG |
| Tempo de geração lento para sessões grandes | Média | Cache em SQLite de chart bytes; gerar sob demanda |
| Banner condicional não atualiza | Baixa | Não cachear `get_banner_html()` |
| Matplotlib em modo headless quebra em alguns ambientes | Baixa | Backend "Agg" explícito |

---

## 6. Notas para o Claude Code

- **Matplotlib backend**: SEMPRE `matplotlib.use("Agg")` antes de qualquer import. Sem isso, em servidor headless, crashes.
- **Base64 PNG inline**: trade-off de tamanho vs portabilidade. Para relatórios standalone, vale a pena.
- **Fontes em PDF**: WeasyPrint requer fontes do sistema; Playwright renderiza nativamente. Preferir Playwright.
- **Dados completos**: relatório deve funcionar mesmo sem audit_log (campo opcional na sessão).
- **Não usar Jupyter/papermill**: complexidade desnecessária.
- **Performance**: gerar todos os charts toma tempo. Considerar cache em `reports/` cache directory.
- **HTML standalone**: tudo inline (CSS via `<style>`, JS via `<script>`, fonts via base64 data: URLs).

---

## 7. Comandos de validação

```bash
pytest tests/unit/test_report_generator.py -v
pytest tests/e2e/test_report_export.py -v

# Manual
python -m gui.server
# Browser: rodar replay 2008-06 a 2009-06 sobre ^BVSP
# Após finalização: /sessions/<id>/report
# Verificar 9 seções, banner, MDD em duas bases
# Exportar HTML: abrir offline em browser
# Exportar PDF: verificar páginas
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — banner condicional | 0.25 dia |
| E2 — template report.html | 1.5 dias |
| E3 — ReportGenerator + charts | 1.5-2 dias |
| E4 — rota report | 0.5 dia |
| E5 — export HTML standalone | 0.5-1 dia |
| E6 — export PDF (Playwright) | 0.5-1 dia |
| E7 — report.js | 0.25 dia |
| E8 — testes (10 casos) | 1.5-2 dias |
| E9 — docs | 0.25 dia |
| Buffer | 0.5 dia |
| **Total** | **6-8 dias** |
