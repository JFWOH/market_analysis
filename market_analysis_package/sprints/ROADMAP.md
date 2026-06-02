# ROADMAP — Programa de Evolução `market\\\_analysis`

**Versão**: 1.0
**Última atualização**: 2026-05-13
**Período coberto**: Sprints 18-33 (16 sprints, \~16-21 semanas)

\---

## Visão de uma página

```
┌──────────────────────────────────────────────────────────────────┐
│ BLOCO I — AUDITORIA           Sprints 18-22    \\\~5-7 semanas      │
│ Saber a verdade sobre o que o sistema atual faz                  │
└──────────────────────────────────────────────────────────────────┘
                              │
              ╔═══════════════╧═══════════════╗
              ║  MARCO DE DECISÃO ESTRATÉGICA ║
              ║  findings/MARCO\\\_BLOCO\\\_I.md    ║
              ║  Produto? Laboratório? Rework?║
              ╚═══════════════╤═══════════════╝
                              │
┌──────────────────────────────────────────────────────────────────┐
│ BLOCO II — HARDENING          Sprints 23-26    \\\~4-5 semanas      │
│ Fundação operacional: audit log, kill switch, SQLite, CI         │
└──────────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────────┐
│ BLOCO III — INTERFACE GRÁFICA Sprints 27-33    \\\~7-9 semanas      │
│ Control Center web local com replay + paper trading live         │
└──────────────────────────────────────────────────────────────────┘
```

\---

## Princípios fundadores

1. **Verdade antes de feature** — Bloco I pode reescrever o headline. Aceitar findings desconfortáveis é o ponto.
2. **Reversibilidade** — todo sprint reversível por `git revert` sem quebra dos anteriores.
3. **A UI é consumidora** — motor define a verdade; UI a visualiza.

\---

## Bloco I — Auditoria (Sprints 18-22)

|Sprint|Tema|Dias|Saída crítica|✅ v0.18.0|
|-|-|-:|-|-|
|18|Desambiguação de MDD (total vs capital-at-risk)|3-4|`findings/sprint\\\\\\\_18\\\\\\\_mdd\\\\\\\_dual.md`|✅ v0.19.0|
|19|Sensibilidade a custos (slippage + comissão)|3-4|`findings/sprint\\\\\\\_19\\\\\\\_cost\\\\\\\_sensitivity.md`|⬜|
|20|Decomposição fatorial (alpha vs exposição)|5-7|`findings/sprint\\\\\\\_20\\\\\\\_factor\\\\\\\_decomp.md`|⬜|
|21|Walk-forward com re-otimização honesta|7-10|`findings/sprint\\\\\\\_21\\\\\\\_walkforward\\\\\\\_honest.md`|⬜|
|22|Bears não-canônicos (15+ cenários)|5-7|`findings/sprint\\\\\\\_22\\\\\\\_bears\\\\\\\_complete.md`|⬜|

**Marco final**: `findings/MARCO\\\_BLOCO\\\_I.md` define se Bloco II prossegue com:

* Cenário A — Sistema é produto (alpha confirmado)
* Cenário B — Sistema é laboratório (alpha parcialmente artefato; UI vira ferramenta de pesquisa)
* Cenário C — Sistema precisa rework (suspender II e III)

\---

## Bloco II — Hardening (Sprints 23-26)

|Sprint|Tema|Dias|Saída crítica|
|-|-|-:|-|
|23|Audit log append-only com hash chain|4-6|`audit\\\_log.py`|
|24|Kill switch + circuit breakers + watchdog|3-5|`risk\\\_guard.py`|
|25|Backend SQLite (substitui JSON)|5-7|`db/`|
|26|Containerização + CI GitHub Actions|3-5|`.github/workflows/ci.yml`|

\---

## Bloco III — Interface Gráfica (Sprints 27-33)

|Sprint|Tema|Dias|Saída crítica|
|-|-|-:|-|
|27|Fundação UI (SessionManager + Flask + SocketIO)|6-8|`gui/` esqueleto funcional|
|28|Integração com motor real (Replay Histórico)|5-7|`gui/adapter.py::ReplayRunner`|
|29|Visualização rica (TradingView Charts + Plotly)|8-10|painel ao vivo completo|
|30|Histórico e comparação A/B|5-7|rotas `/sessions` e `/compare`|
|31|Relatórios de sessão (HTML standalone + PDF)|6-8|template + rota `/report`|
|32|Paper Trading Live (polling yfinance em pregão)|10-14|`gui/adapter.py::LiveRunner`|
|33|Empacotamento (.exe com pywebview)|5-7|`market\\\_analysis.spec` + `.bat`|

\---

## Fluxo de uma sessão de uso (estado final)

```
1. Usuário abre Control Center (clica no .exe ou .bat)
   └─> pywebview abre janela; Flask sobe em 127.0.0.1:5000

2. Usuário vai para /config
   └─> escolhe preset "Sprint-13 reference"
   └─> seleciona tickers, período, modo (Replay ou Live)
   └─> clica "Iniciar simulação"

3. Sistema dispara processo de simulação
   └─> SessionManager.spawn(config) -> session\\\_id UUID
   └─> Backend redireciona para /live/<session\\\_id>

4. Painel ao vivo mostra em tempo real:
   ├── Gráfico candlestick + sinais + stops/targets
   ├── Métricas (equity, P\\\&L, drawdown, Sharpe)
   └── Log categorizado (incluindo decisões de NÃO-trade)

5. Ao fim da simulação:
   └─> Relatório completo em /sessions/<id>/report
   └─> Exportável como HTML standalone ou PDF
   └─> Comparável com outras sessões em /compare

6. Tudo persistido em SQLite + audit log imutável
```

\---

## Estimativas globais

* **Total**: 16 sprints, 78-104 dias úteis
* **Ritmo integral** (8h/dia): 16-21 semanas (\~4-5 meses)
* **Ritmo meio-período** (4h/dia): 32-42 semanas (\~8-10 meses)

Buffer de 20% já incluído nas estimativas individuais.

\---

## Riscos macro do programa

|Risco|Probabilidade|Impacto|Mitigação|
|-|-|-|-|
|Findings do Bloco I forçam rework|Média|Alto|Aceitação explícita no Marco; Cenário C documentado|
|SocketIO + multiprocessing Windows|Média|Médio|Validação em Sprint 27 com mock; plano B documentado em ADR-001|
|yfinance rate-limit em Live|Alta|Baixo|Cache agressivo + retry; documentar limitações|
|Scope creep na UI|Alta|Médio|Sprint fecha estrito; backlog separado|
|Auditoria revela alpha < 0,5 Sharpe|Baixa-Média|Alto|Cenário B/C; reposicionar como ferramenta de pesquisa|

\---

## O que **não** está no roadmap (por decisão consciente)

Mencionados em discussões anteriores e **excluídos** deste programa:

* ❌ HMM regime classifier (sugerido em roadmap antigo) — exige experimento exploratório barato antes; entra em programa futuro
* ❌ Features macro (VIX, yield curve) — mesma razão
* ❌ Risk parity portfolio — modesto retorno esperado
* ❌ Reinforcement learning agent — fora de escopo
* ❌ Integração com corretora real (FIX) — fora de escopo; sistema permanece paper-only
* ❌ Frontend React/Next.js — UI Jinja2 + HTMX é suficiente
* ❌ Multi-usuário / autenticação avançada — single-user por design

Itens excluídos não foram esquecidos. Foram **deliberadamente despriorizados** para que este programa seja terminável.

\---

## Como começar (Sprint 18, dia 1)

```bash
git checkout -b sprint-18-metricas
# Ler sprints/sprint\\\_18\\\_metricas.md inteiro
# Implementar E1 (módulo metrics.py)
# Implementar E3 (testes)
# Implementar E2 (integração backtester)
# Implementar E4 (script re-execução)
# Implementar E5 (findings)
# Suite completa passa
# PR para main
```

Estrutura idêntica para todos os outros sprints. Disciplina simples; resultado composto.

\---

## Tabela de dependências

```
S18 ──┐
      ├─> S19 ──> S20 ──> S21 ──> S22 ──┐
      │                                 │
      │                          \\\[MARCO BLOCO I]
      │                                 │
      └─────────────────────────────────┴──> S23 ──> S24 ──> S25 ──> S26 ──┐
                                                                          │
                                                                          ▼
                                                                         S27 ──> S28
                                                                                  │
                                                                                  ▼
                                                                                 S29 ──> S30
                                                                                          │
                                                                                          ▼
                                                                                         S31 ──> S32 ──> S33
```

Cada seta é dependência forte: sprint posterior não inicia antes do anterior fechar.

\---

**Documento vivo**: cada sprint fechado atualiza esta tabela com status e ajusta estimativas. Versão 2.0 esperada após o Marco do Bloco I.

