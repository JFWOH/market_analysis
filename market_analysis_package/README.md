# Pacote de Desenvolvimento — `market_analysis` Sprints 18-33

Este pacote contém o **plano completo** de evolução do projeto `market_analysis` — 16 sprints organizados em três blocos sequenciais, com toda a documentação necessária para que o Claude Code (ou qualquer desenvolvedor) execute o programa de ponta a ponta.

Não é código pronto a rodar. É **especificação executável**: cada arquivo aqui foi escrito para ser consumido por um agente que vai implementar, sprint por sprint, dentro do repositório existente em `H:\PYTHON\market_analysis`.

---

## Visão de uma página

```
┌──────────────────────────────────────────────────────────────────┐
│ BLOCO I — AUDITORIA           Sprints 18-22    ~5-7 semanas      │
│ Saber a verdade sobre o que o sistema atual faz                  │
└──────────────────────────────────────────────────────────────────┘
                              │
              ╔═══════════════╧═══════════════╗
              ║  MARCO DE DECISÃO ESTRATÉGICA ║
              ║  findings/MARCO_BLOCO_I.md    ║
              ║  Produto? Laboratório? Rework?║
              ╚═══════════════╤═══════════════╝
                              │
┌──────────────────────────────────────────────────────────────────┐
│ BLOCO II — HARDENING          Sprints 23-26    ~4-5 semanas      │
│ Fundação operacional: audit log, kill switch, SQLite, CI         │
└──────────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────────┐
│ BLOCO III — INTERFACE GRÁFICA Sprints 27-33    ~7-9 semanas      │
│ Control Center web local com replay + paper trading live         │
└──────────────────────────────────────────────────────────────────┘
```

---

## Estrutura do pacote

```
market_analysis_package/
├── CLAUDE.md                       ← convenções inegociáveis para o agente
├── README.md                        ← este arquivo
├── pyproject.toml                   ← configuração consolidada do projeto
│
├── sprints/                         ← 16 sprints + roadmap
│   ├── ROADMAP.md
│   ├── sprint_18_metricas.md
│   ├── sprint_19_custos.md
│   ├── sprint_20_decomposicao.md
│   ├── sprint_21_walkforward.md
│   ├── sprint_22_bears_extras.md
│   ├── sprint_23_audit_log.md
│   ├── sprint_24_killswitch.md
│   ├── sprint_25_sqlite.md
│   ├── sprint_26_ci.md
│   ├── sprint_27_fundacao_ui.md
│   ├── sprint_28_replay.md
│   ├── sprint_29_charts.md
│   ├── sprint_30_historico.md
│   ├── sprint_31_relatorios.md
│   ├── sprint_32_live.md
│   └── sprint_33_packaging.md
│
├── docs/decisions/                  ← Architecture Decision Records
│   ├── ADR-001-web-local.md
│   ├── ADR-002-sqlite-backend.md
│   └── ADR-003-audit-chain.md
│
├── findings/                        ← templates de resultado dos sprints
│   ├── MARCO_BLOCO_I.md             ← decisão estratégica entre Blocos
│   ├── sprint_18_mdd_dual.md
│   ├── sprint_19_cost_sensitivity.md
│   ├── sprint_20_factor_decomp.md
│   ├── sprint_21_walkforward_honest.md
│   └── sprint_22_bears_complete.md
│
├── db/
│   └── schema.sql                   ← schema SQLite (Sprint 25)
│
├── configs/presets/                 ← será populado pelos sprints
├── scenarios/                       ← bears v2 (Sprint 22)
├── gui/                             ← Bloco III
├── tests/                           ← unit, integration, e2e
└── .github/workflows/               ← CI (Sprint 26)
```

Pastas vazias estão presentes para que a estrutura final do projeto seja clara antes de qualquer linha ser implementada.

> **⚠️ Layout FLAT — leia antes de implementar.** O projeto real usa módulos Python soltos na raiz (`strategy.py`, `backtester.py`, etc.), NÃO uma pasta `market_analysis/`. Todos os caminhos neste pacote já foram traduzidos para o layout flat (`metrics.py`, não `market_analysis/metrics.py`). A pasta `db/` e a futura `gui/` são as únicas subpastas que são pacotes Python de verdade. Detalhes completos em `CLAUDE.md` seção 1.5. **Não crie pasta `market_analysis/` na raiz.**

---

## Como o agente deve usar este pacote

### Passo 1 — Leitura inicial
1. `CLAUDE.md` — convenções inegociáveis. Lido primeiro, sempre.
2. `sprints/ROADMAP.md` — visão de todo o programa.
3. `docs/decisions/ADR-001`, `ADR-002`, `ADR-003` — decisões arquiteturais já tomadas.

### Passo 2 — Execução de sprint
Para cada sprint, na ordem:

1. Ler `sprints/sprint_NN_<slug>.md` inteiro
2. Criar branch `sprint-NN-<slug>` a partir de `main`
3. Implementar entregáveis na ordem (E1, E2, E3...)
4. Cada entregável tem PR próprio
5. Suite completa (`pytest tests/ -q`) deve passar antes de cada PR
6. Ao fim, preencher `findings/sprint_NN_<topic>.md` se aplicável
7. Merge final em `main` com tag `v0.NN.0`

### Passo 3 — Após Sprint 22 (último do Bloco I)
**Antes** de iniciar Sprint 23, preencher `findings/MARCO_BLOCO_I.md` com decisão estratégica baseada nos findings dos 5 sprints anteriores.

A decisão escolhida (Cenário A, B ou C) determina se Blocos II e III prosseguem como planejado, com ajustes, ou são suspensos para rework.

---

## Princípios fundadores

Três frases que resumem o espírito do programa. Em caso de dúvida sobre qualquer decisão, retornar a elas:

1. **Verdade antes de feature** — o Bloco I existe para descobrir o que o sistema realmente faz, mesmo se isso reescrever o headline.
2. **Reversibilidade** — todo sprint é reversível por `git revert` sem quebrar os anteriores.
3. **A UI é consumidora, não criadora** — o motor define a verdade; a UI a visualiza.

---

## Estimativas

- **Total**: 16 sprints, 78-104 dias úteis
- **Ritmo integral** (8h/dia): 16-21 semanas
- **Ritmo meio-período** (4h/dia): 32-42 semanas
- **Buffer**: 20% já incluído em cada sprint individual

---

## O que está e o que **não** está

### ✅ Está no programa
- Auditoria honesta da base atual (Bloco I)
- Hardening operacional: audit log, kill switch, SQLite, CI (Bloco II)
- Interface gráfica web local com replay + paper trading live (Bloco III)
- Empacotamento como `.exe` Windows

### ❌ Não está no programa (decisão consciente)
- HMM regime classifier (sugerido em roadmap antigo; entra em programa futuro se necessário)
- Features macro (VIX, yield curve, spreads)
- Risk parity portfolio
- Reinforcement learning agent
- Integração com corretora real via FIX (sistema permanece paper-only)
- Frontend React/Next.js (UI Jinja2 + HTMX é suficiente)
- Multi-usuário / autenticação avançada (single-user por design)

Itens excluídos não foram esquecidos. Foram **deliberadamente despriorizados** para que este programa seja terminável em horizonte razoável.

---

## Onde começar agora

```bash
cd H:\PYTHON\market_analysis

# Copiar este pacote para dentro do repositório
# (preservar estrutura de pastas)

git checkout -b sprint-18-metricas
# Abrir sprints/sprint_18_metricas.md
# Seguir entregáveis E1 → E5
```

---

## Validação do pacote

Antes de começar Sprint 18, conferir que estes arquivos existem e fazem sentido:

- [ ] `CLAUDE.md` — convenções claras
- [ ] `sprints/ROADMAP.md` — visão dos 16 sprints
- [ ] 16 arquivos `sprints/sprint_*.md`
- [ ] 5 templates `findings/sprint_*.md` + `findings/MARCO_BLOCO_I.md`
- [ ] 3 ADRs em `docs/decisions/`
- [ ] `db/schema.sql` (referência do Sprint 25)
- [ ] `pyproject.toml` consolidado

Se algum estiver ausente, este pacote está incompleto.

---

## Filosofia em uma linha

> Disciplina simples, resultado composto. Cada sprint adiciona uma camada verificável. No fim, o sistema sabe sobre si mesmo coisas que hoje não sabe.

Pronto para começar. Sprint 18, dia 1.
