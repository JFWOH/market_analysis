# ORQUESTRAÇÃO — Protocolo de Trabalho do Claude Code

Este documento define **como** o Claude Code deve executar os sprints do programa `market_analysis` (Sprints 18-33). É complementar ao `CLAUDE.md` (que define as convenções de código) — aqui está o protocolo de **execução e controle**.

Salve este arquivo como `ORCHESTRATION.md` na raiz do projeto. O Claude Code deve lê-lo no início de cada sessão de sprint.

---

## Princípio central: trabalho por checkpoints

O desenvolvedor (Jeferson) controla o trabalho via **checkpoints**, não via aprovação linha-a-linha. Cada sprint é dividido em grupos de tarefas. Ao fim de cada grupo, o Claude Code **PARA**, produz um **RELATÓRIO DE CHECKPOINT**, e **aguarda aprovação explícita** antes de continuar.

O Claude Code NUNCA avança para o próximo checkpoint sem o desenvolvedor dizer "aprovado", "siga", "continue" ou equivalente.

---

## Os três checkpoints de cada sprint

### Checkpoint 1 — PLANO (read-only)
- Ler `CLAUDE.md`, `ORCHESTRATION.md`, o arquivo do sprint (`sprints/sprint_NN_*.md`), e o código existente relevante.
- Produzir um **plano detalhado** de implementação SEM escrever nenhum arquivo.
- O plano deve listar: cada arquivo a criar/modificar, a ordem, as assinaturas de função principais, os casos de teste previstos, e quaisquer dúvidas ou decisões que precisam de input humano.
- **PARAR**. Aguardar aprovação do plano.

> Use o **Plan Mode** do Claude Code para este checkpoint (Shift+Tab duas vezes, ou inicie com `--permission-mode plan`). Em Plan Mode, a escrita é estruturalmente bloqueada — garantia de que nada é tocado antes da aprovação.

### Checkpoint 2 — NÚCLEO TESTADO
- Implementar a lógica central do sprint + seus testes (a ordem exata está no arquivo do sprint).
- Test-first quando o sprint indicar: testes antes ou junto da implementação.
- Rodar os testes novos isoladamente, depois a suite completa.
- **PARAR**. Produzir RELATÓRIO DE CHECKPOINT (formato abaixo). Aguardar aprovação.

### Checkpoint 3 — INTEGRAÇÃO + ENTREGÁVEIS
- Implementar integrações, scripts, e preencher o template de findings (se houver).
- Rodar a suite completa novamente.
- **PARAR**. Produzir RELATÓRIO FINAL DO SPRINT. Aguardar aprovação para o merge.

Sprints maiores (ex.: 25, 27, 29, 32) podem ter 4-5 checkpoints. O Claude Code deve **propor** a divisão em checkpoints no Checkpoint 1 (plano) e o desenvolvedor aprova ou ajusta.

---

## Formato obrigatório do RELATÓRIO DE CHECKPOINT

Ao parar em qualquer checkpoint, o Claude Code produz um relatório EXATAMENTE neste formato:

```
═══════════════════════════════════════════════
RELATÓRIO DE CHECKPOINT — Sprint NN — Checkpoint X de Y
═══════════════════════════════════════════════

## O que foi feito
- [lista objetiva de arquivos criados/modificados, com contagem de linhas]

## Testes
- Testes novos: N criados, N passando
- Suite completa: XXX passando / YYY total (baseline era 519)
- Cobertura do código novo: XX%
- Tempo de execução: XXs

## Decisões tomadas
- [qualquer decisão de implementação que não estava explícita no sprint]
- [se nenhuma: "Nenhuma decisão fora do especificado."]

## Desvios do plano
- [qualquer coisa que saiu diferente do plano aprovado no Checkpoint 1]
- [se nenhum: "Nenhum desvio."]

## Bloqueios ou dúvidas
- [qualquer coisa que precisa de decisão humana]
- [se nenhum: "Nenhum bloqueio."]

## Próximo checkpoint
- [o que será feito no próximo grupo de tarefas]

## Diff resumido
- [git diff --stat do que foi feito neste checkpoint]

═══════════════════════════════════════════════
AGUARDANDO APROVAÇÃO PARA CONTINUAR
═══════════════════════════════════════════════
```

---

## Regras invioláveis de execução

1. **Nunca pular checkpoint.** Mesmo que pareça óbvio continuar, PARE e reporte.

2. **Nunca modificar testes existentes** para fazer código novo passar. Os 519 testes legados são verdade estabelecida. Se um quebra, o problema está no código novo. Reportar como bloqueio.

3. **A suite completa precisa passar** antes de cada relatório de checkpoint (exceto Checkpoint 1, que é read-only). Se não passar, o relatório deve dizer claramente quais testes falham e por quê — e NÃO avançar.

4. **Respeitar o layout flat** (ver `CLAUDE.md` seção 1.5). Nunca criar pasta `market_analysis/`. Módulos vão na raiz.

5. **Um commit por entregável**, seguindo Conventional Commits (ver `CLAUDE.md` seção 3). Não fazer um commit-monstro no fim.

6. **Não fazer merge sozinho.** O merge para `main` é decisão do desenvolvedor, sempre.

7. **Não expandir escopo.** Implementar exatamente o que o sprint pede. Ideias de melhoria vão para a seção "Decisões/dúvidas" do relatório, não para o código.

8. **Reportar honestamente.** Se algo não funcionou, se um teste é frágil, se uma decisão foi um chute — dizer no relatório. O valor do checkpoint é a honestidade.

---

## Sobre o Plan Mode e permissões

- **Checkpoint 1** sempre em **Plan Mode** (read-only). Garante que o plano é só plano.
- **Checkpoints 2 e 3**: modo `default` (aprovação por ação) ou `acceptEdits` (auto-aceita edições de arquivo) — escolha do desenvolvedor. Recomendação para começar: `default`, para ver cada escrita até ganhar confiança no agente.
- O guard phrase **"não implemente ainda, só planeje"** mantém o Claude Code em modo de planejamento se você quiser iterar no plano antes de liberar a escrita.

---

## Ritmo recomendado para o primeiro sprint (18)

Como este é o primeiro sprint com o Claude Code neste programa, vá mais devagar para calibrar:

- Leia o plano do Checkpoint 1 com atenção. É onde você descobre se o agente entendeu o sprint.
- No Checkpoint 2, confira se os 12 testes fazem sentido antes de aprovar.
- Se o agente se comportar bem no Sprint 18, afrouxe o controle nos seguintes (ex.: `acceptEdits`, checkpoints maiores).
- Se o agente desviar, aperte (mais checkpoints, revisão de cada arquivo).

A confiança no agente é construída por evidência, sprint a sprint — não concedida de antemão.

---

## O que fazer ao fim de cada sprint

Depois do Checkpoint final aprovado:

1. Desenvolvedor faz o merge para `main` com tag `v0.NN.0`
2. Rodar a suite completa na `main` pós-merge (sanity check)
3. Se for sprint do Bloco I: confirmar que o finding foi preenchido
4. Atualizar status do sprint para "fechado" no `ROADMAP.md`
5. Após Sprint 22: preencher `MARCO_BLOCO_I.md` antes de iniciar Sprint 23
```
