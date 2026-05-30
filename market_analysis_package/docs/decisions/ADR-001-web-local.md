# ADR-001 — Interface Gráfica: Web Local (Flask + SocketIO) sobre Desktop Nativo

**Status**: Accepted
**Data**: 2026-05-13
**Decisores**: Jeferson Wohanka
**Consulta técnica**: Claude (Anthropic)

---

## Contexto

O programa de Sprints 27-33 introduz uma interface gráfica para o `market_analysis`. A escolha de stack tecnológica é uma decisão de longo prazo: muda completamente o paradigma de desenvolvimento, distribuição, manutenção e extensibilidade futura.

As alternativas consideradas foram quatro:

### Opção A — Desktop nativo (PySide6 / Qt)
Janela nativa do SO, sem browser. Renderização direta. Estado da arte para aplicações desktop científicas (Spyder, JupyterLab Desktop, várias ferramentas quant).

### Opção B — Web local (Flask + SocketIO + Jinja2 + HTMX)
Servidor Flask roda em `127.0.0.1:5000`. Usuário acessa via navegador (Edge/Chrome) ou janela pywebview embarcada. Estado vive no Python; UI é HTML/JS leve.

### Opção C — Streamlit
Framework Python-first para dashboards. Re-renderiza tudo a cada interação.

### Opção D — Tauri / Electron + Python backend
Frontend moderno (React/Vue) compilado em janela nativa, comunicando com backend Python via IPC.

---

## Decisão

**Adotamos a Opção B — Web Local (Flask + SocketIO + Jinja2 + HTMX + Plotly + TradingView Lightweight Charts), embarcada em pywebview no empacotamento final (Sprint 33).**

---

## Racional

### Por que NÃO Opção A (Qt)

1. **Curva de aprendizado vertical**. PySide6 tem ~500 classes, model/view, signals/slots. Para um desenvolvedor solo focado em quant, custo de oportunidade é alto.
2. **Visualização financeira**: Qt tem QtCharts (limitado) ou bindings para Plotly (que viram canal Python→QWebEngineView de qualquer forma). O ganho de "nativo" se dissolve quando o componente que mais importa (gráfico de preços) acaba sendo HTML.
3. **Iteração lenta**. Modificar UI Qt exige reiniciar processo Python; web local permite F5 no browser durante desenvolvimento.
4. **Empacotamento Windows**: PyInstaller com Qt frequentemente tem issues de DLL conflict. Web local com pywebview é mais estável.
5. **Conhecimento futuro reutilizável**: tudo que aprende em Flask/HTMX serve para deploy remoto eventual; Qt é específico.

### Por que NÃO Opção C (Streamlit)

1. **Re-execução completa a cada interação** quebra o paradigma de simulação ao vivo (sessão precisa ser processo persistente).
2. **Customização visual limitada** — tabelas, layouts, charts seguem padrão Streamlit; difícil ter visual identidade.
3. **Sem SocketIO real-time** — push de eventos do simulador para UI é frágil.
4. **Estado fora do Streamlit é tortuoso** — exige `st.session_state` que não persiste entre sessões diferentes.

### Por que NÃO Opção D (Tauri/Electron + React)

1. **Sobreengenharia para single-user solo**. React + bundler + estado client + serialização IPC é stack adequado para SaaS multi-usuário, não para ferramenta pessoal.
2. **Bloat de tamanho**: Electron pesa 100+ MB; Tauri menos mas ainda exige toolchain Rust.
3. **Manutenção dupla**: dois lados (JS + Python) com lifecycle de dependências separados.
4. **Excluído de roadmap**: a opção "frontend React" foi deliberadamente removida da lista de extensões (ver `sprints/ROADMAP.md` seção "O que não está no roadmap").

### Por que SIM Opção B (web local)

1. **Stack mínimo, dependências leves**: Flask + SocketIO + Jinja2 já estão no `requirements.txt` do sistema atual (`app.py` legado). HTMX é zero-build (incluído via CDN ou cópia local de 12KB).
2. **Plotly e TradingView Lightweight Charts** são os melhores componentes de visualização financeira open-source — ambos web.
3. **Iteração rápida**: F5 mostra mudança; flask debug mode auto-reload.
4. **Servidor Python persistente** se encaixa naturalmente no modelo "sessão de simulação = processo de longa duração com SocketIO push".
5. **Empacotamento limpo**: pywebview embute Edge WebView2 (presente em Windows 10+); resultado final aparece como app desktop sem usuário precisar abrir browser.
6. **Reuso direto** do código existente (`app.py` antigo é base; refatorar > reescrever).

---

## Consequências

### Positivas

- Desenvolvimento mais rápido nos Sprints 27-33 (estimativa total: 7-9 semanas; com Qt seria 11-14)
- Familiaridade do desenvolvedor com web (HTML/JS básico é universal)
- Componentes de gráfico financeiro maduros (TradingView Lightweight Charts é o padrão de fato)
- Caminho de migração futuro: se um dia precisar acesso remoto, é trivial — só remove o `127.0.0.1` binding

### Negativas e mitigações

| Negativa | Mitigação |
|---|---|
| Browser pode ser fechado acidentalmente | Sessão persiste no servidor (Sprint 25 SQLite); reabrir URL recupera estado |
| Latência F5 inicial maior que Qt | Tolerável (< 1s); compensado por reload rápido |
| WebView2 dependência (pywebview no Windows) | Presente em Windows 10+ por padrão; documentar pré-requisito |
| Performance de gráficos com muitos pontos | TradingView Lightweight Charts é otimizado para isso; > 100k candles sem problema |
| Multi-process + SocketIO + Windows = complexidade | Sprint 27 inclui validação ponta-a-ponta com mock; plano B documentado abaixo |

### Riscos específicos do Windows com SocketIO + multiprocessing

**Sintoma esperado**: quando o `SessionManager` faz `multiprocessing.Process()` em Windows, Python usa `spawn` (não `fork`). Isso reinicializa todo o módulo no processo filho. Bibliotecas com estado global (matplotlib, alguns paths de pandas C-extension) podem comportar-se inconsistentemente.

**Plano B documentado**: se Sprint 27 detectar instabilidade insolúvel:

- Substituir `multiprocessing.Process` por `subprocess.Popen` com IPC via SQLite + filewatch
- O simulador vira um script CLI que escreve no DB; UI faz polling do DB
- SocketIO push degrada para SSE (Server-Sent Events) — mais simples, menos sensível a estado

Essa mudança não invalida o ADR principal (continua web local); apenas adapta o transporte interno.

---

## Métricas de validação

A decisão é considerada bem-sucedida se, ao fim do Sprint 33:

- Tempo médio para usuário iniciar uma simulação a partir do clique no `.exe`: < 5 segundos
- Latência entre evento no simulador e atualização no painel: < 500ms
- App empacotado: < 100 MB
- Funciona em Windows 10/11 sem instalação de Python pelo usuário

---

## Revisão

Esta ADR pode ser revista se:

1. Sprint 27 revelar incompatibilidade fundamental do stack com Windows (improvável; ver Plano B acima)
2. Necessidade de acesso multi-usuário concorrente surgir (fora do escopo atual)
3. Performance do gráfico revelar-se inadequada com > 1M candles (improvável; TradingView é otimizado para milhões)

Caso contrário, decisão é considerada permanente para o ciclo de vida deste programa.

---

## Referências

- `sprints/ROADMAP.md` — visão do programa
- `sprints/sprint_27_fundacao_ui.md` — implementação inicial
- `sprints/sprint_33_packaging.md` — empacotamento com pywebview
- TradingView Lightweight Charts: https://www.tradingview.com/lightweight-charts/
- HTMX: https://htmx.org/
- pywebview: https://pywebview.flowrl.com/
