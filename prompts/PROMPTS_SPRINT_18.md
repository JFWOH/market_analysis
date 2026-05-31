# Prompts do Sprint 18 — Claude Code DESKTOP (aba Code)

Use estes prompts em sequência. Após cada um, o Claude Code para e produz um relatório. Você revisa e só então cola o próximo.

**Pré-requisito**: você já está no branch `sprint-18-metricas`, com o venv ativado, e abriu o projeto `H:\PYTHON\market_analysis` no Claude Code Desktop.

---

## Como controlar o modo no Desktop

O Claude Code Desktop tem um **seletor de modo ao lado do botão de enviar** (e também responde a `Shift+Tab` para ciclar). Os modos que vamos usar:

- **plan** (Plan Mode) — read-only. Claude lê e raciocina, mas NÃO escreve arquivos nem roda comandos. O modo atual aparece na barra de status (você verá algo como "⏸ plan mode on").
- **default** — Claude pede aprovação antes de cada escrita de arquivo ou comando. É o modo de maior supervisão para execução.
- **acceptEdits** — auto-aceita edições de arquivo (sem pedir a cada uma). Mais rápido, menos controle. Use só depois de ganhar confiança no agente.

Para o primeiro sprint, a recomendação é: **plan** no Checkpoint 1, **default** nos Checkpoints 2 e 3.

> Dica: o seletor fica perto do campo de digitação. Antes de colar cada prompt, confira na barra de status que você está no modo certo.

---

## CHECKPOINT 1 — Plano (no modo PLAN)

> **Antes de colar**: selecione o modo **plan** no seletor ao lado do botão de enviar (ou Shift+Tab até ver "plan mode on" na barra de status). Isso bloqueia escrita — garante que o plano é só plano.

Cole:

```
Leia, nesta ordem: ORCHESTRATION.md, CLAUDE.md, sprints/sprint_18_metricas.md.

Depois leia o código existente relevante: backtester.py (foque em como a equity
curve e o valor das posições são rastreados ao longo da simulação) e dê uma olhada
em tests/unit/test_backtester.py para entender o estilo dos testes do projeto.

Então produza um PLANO DETALHADO de implementação do Sprint 18, seguindo o protocolo
de checkpoints do ORCHESTRATION.md. NÃO implemente nada ainda — só planeje.

O plano deve conter:
1. A assinatura exata da função compute_drawdown_dual (parâmetros, retorno, docstring resumida)
2. Onde no backtester.py a integração vai entrar (qual método, que campos novos)
3. A lista dos 12 casos de teste, cada um com uma frase do que valida
4. A estrutura do script scripts/rerun_bear_validation_dual_mdd.py
5. Sua proposta de divisão em checkpoints (quantos, o que cada um cobre)
6. Quaisquer dúvidas ou decisões que precisam de input meu antes de começar

Lembre: layout flat — metrics.py vai na raiz, não em market_analysis/.
```

**O que revisar no plano:**
- A assinatura de `compute_drawdown_dual` faz sentido? Bate com o que o sprint pede?
- Os 12 testes cobrem os casos do sprint (always-long, nunca opera, short, partial exit, etc.)?
- A proposta de divisão em checkpoints é razoável?
- Há dúvida que você precisa responder antes?

Se o plano estiver bom: troque o modo para **default** no seletor e responda `Plano aprovado. Implemente o Checkpoint 2.`
Se precisar ajuste: continue em **plan** e responda apontando o que mudar, terminando com `não implemente ainda, só revise o plano.`

---

## CHECKPOINT 2 — Núcleo testado (E1 + E3)

> **Antes de colar**: troque o seletor de modo para **default**. Confira na barra de status que saiu do plan mode.

Cole:

```
Implemente o Checkpoint 2 conforme o plano aprovado:

1. Crie metrics.py na raiz com a função compute_drawdown_dual (E1 do sprint).
   Função pura: sem I/O, sem prints. Use numpy vetorizado, não loops.

2. Crie tests/unit/test_metrics.py com os 12 casos de teste (E3 do sprint).
   Todos determinísticos (seeds fixas onde houver RNG).

3. Rode primeiro os testes novos isolados:
   pytest tests/unit/test_metrics.py -v
   Depois a suite completa:
   pytest tests/ -q

4. Descomente a linha "metrics" em py-modules no pyproject.toml.

5. Faça um commit para cada entregável (E1 e E3 separados ou juntos, seu critério,
   seguindo Conventional Commits).

Então PARE e produza o RELATÓRIO DE CHECKPOINT no formato do ORCHESTRATION.md.
Não avance para a integração no backtester sem minha aprovação.

Lembre: a baseline é 519 testes. Após o Checkpoint 2 devem ser 519 + 12 = 531, todos passando.
```

**O que revisar no relatório:**
- Os 12 testes passam? A suite completa segue em 531 (519+12)?
- A função `compute_drawdown_dual` está limpa (sem I/O, vetorizada)? — use o **diff visual** do desktop para conferir.
- Algum desvio do plano? Alguma decisão fora do especificado?
- Cobertura do `metrics.py` ≥ 95%?

Se bom: `Checkpoint 2 aprovado. Siga para o Checkpoint 3.`

---

## CHECKPOINT 3 — Integração + entregáveis (E2 + E4 + E5)

> Permaneça no modo **default**. (Se já confia no agente após o Checkpoint 2, pode trocar para **acceptEdits** para menos interrupções — mas no primeiro sprint, default é mais seguro.)

Cole:

```
Implemente o Checkpoint 3 conforme o plano:

1. Integre compute_drawdown_dual no backtester.py (E2 do sprint). Mudança
   NÃO-quebrante: mantenha o campo max_drawdown_pct existente; adicione os novos
   campos (max_drawdown_capital_at_risk_pct, time_in_market_pct).

2. Crie scripts/rerun_bear_validation_dual_mdd.py (E4). Ele reaproveita a lógica
   de bear_market_validation existente, roda os 7 cenários, coleta as duas métricas
   de MDD, e salva o CSV em findings/sprint_18_data/bears_dual_mdd.csv + o gráfico PNG.

3. Rode o script e gere os dados reais.

4. Preencha findings/sprint_18_mdd_dual.md com os números reais obtidos (E5).
   Substitua todos os <preencher> pelos valores que o script produziu.

5. Rode a suite completa de novo: pytest tests/ -q

6. Commit para cada entregável.

ATENÇÃO ao .gitignore: o projeto ignora *.png globalmente. O PNG em
findings/sprint_18_data/ precisa de uma exceção. Adicione ao .gitignore:
   !findings/**/*.png
e reporte isso no relatório.

Então PARE e produza o RELATÓRIO FINAL DO SPRINT. Não faça merge — isso é decisão minha.
```

**O que revisar no relatório final:**
- A integração no backtester quebrou algum dos 519 testes legados? (não pode)
- O script rodou e gerou CSV + PNG de verdade?
- O finding foi preenchido com números reais, não placeholders?
- A suite completa passa?
- O `.gitignore` ganhou a exceção para os PNGs de findings?

Se tudo bom, você faz o merge manualmente (no terminal integrado do desktop ou no seu cmd):

```
git checkout main
git merge --no-ff sprint-18-metricas -m "merge: Sprint 18 - drawdown dual base"
git tag v0.18.0
pytest tests/ -q          # sanity check pós-merge
```

---

## Lembrete sobre o que observar neste primeiro sprint

Este é o teste de calibração do Claude Code. Preste atenção em:

- Ele seguiu o layout flat (metrics.py na raiz, não market_analysis/metrics.py)?
- Ele parou nos checkpoints ou tentou emendar tudo?
- Os relatórios foram honestos (admitiu decisões, desvios, dúvidas)?
- Ele respeitou "não modificar testes existentes"?
- Os commits seguiram Conventional Commits?

Vantagem do desktop aqui: use o **diff visual** e a **árvore de arquivos** para revisar cada checkpoint mais rápido. Você vê o metrics.py nascer na raiz (confirmando o layout flat) sem dar `dir`.

Se ele se comportou bem no Sprint 18: nos próximos pode afrouxar (acceptEdits, checkpoints maiores).
Se desviou: aperte o controle (mais checkpoints, revisão de cada arquivo via diff visual).
