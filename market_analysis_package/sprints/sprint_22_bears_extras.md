# Sprint 22 — Validação em Bears Não-Canônicos

**Bloco**: I (Auditoria)
**Duração estimada**: 5-7 dias úteis
**Pré-requisito**: Sprint 21 fechado (`v0.21.0`)
**Status**: pending
**Tag ao fechar**: `v0.22.0`

---

## 1. Contexto

Os 7 cenários atuais (GFC 2008 ^BVSP/^GSPC, COVID 2020, 2022 bear ^IXIC, 2015 BR bear) são os **bears famosos**. Tudo que o operador médio se lembra está testado. Mas:

- **Bears regionais** (Argentina 2001, Turquia 2018, Rússia 1998-2014) raramente entram em validações brasileiras, e cada um tem dinâmica diferente.
- **Bears asiáticos** (Asia 1997, China 2015-2016, Japão "lost decade" 1990-2003) testam comportamento em regimes culturalmente/estruturalmente distintos.
- **Bears mean-reverting brutais** (sem crash linear, oscilação severa em banda) são exatamente onde trend-following com filtro de regime tipicamente fracassa.

7 cenários é amostra pequena com viés de seleção (sobrevivência narrativa: testou-se o que o autor lembrou). Sistema robusto deveria passar em **15+ cenários diversos**, incluindo regimes adversos não-canônicos.

---

## 2. Objetivo

Expandir `bear_market_validation.py` para 15+ cenários, executar com a **config validada no Sprint 21** (não a do RELATORIO_TECNICO original), e expor honestamente onde o sistema falha.

---

## 3. Entregáveis

### E1 — Lista expandida em `scenarios/bears_v2.yaml`

```yaml
# Schema:
# - id: identificador
#   name: nome legível
#   ticker: símbolo yfinance
#   start: YYYY-MM-DD
#   end: YYYY-MM-DD
#   category: enum [crash_linear, regional, mean_reverting_brutal, lost_decade]
#   notes: contexto

scenarios:
  # === Originais (controle) ===
  - id: gfc_2008_bvsp
    name: "GFC 2008 — IBOVESPA"
    ticker: "^BVSP"
    start: 2008-06-01
    end: 2009-06-30
    category: crash_linear
  
  - id: gfc_2008_gspc
    name: "GFC 2008 — S&P 500"
    ticker: "^GSPC"
    start: 2008-06-01
    end: 2009-06-30
    category: crash_linear
  
  - id: covid_2020_bvsp
    name: "COVID 2020 — IBOVESPA"
    ticker: "^BVSP"
    start: 2020-01-01
    end: 2020-06-30
    category: crash_linear
  
  - id: bear_2022_ixic
    name: "2022 Tech Bear — NASDAQ"
    ticker: "^IXIC"
    start: 2022-01-01
    end: 2022-12-31
    category: crash_linear
  
  - id: br_bear_2015
    name: "2015-2016 Brazilian Bear"
    ticker: "^BVSP"
    start: 2015-01-01
    end: 2016-01-31
    category: crash_linear
  
  # === Novos: regionais ===
  - id: argentina_2001
    name: "Argentina Convertibility Crisis"
    ticker: "^MERV"
    start: 2001-01-01
    end: 2002-06-30
    category: regional
    notes: "Crise da paridade peso-dólar; default soberano"
  
  - id: russia_2014
    name: "Russia Ruble Crisis"
    ticker: "IMOEX.ME"
    start: 2014-06-01
    end: 2015-06-30
    category: regional
    notes: "Sanções + colapso do petróleo"
  
  - id: turkey_2018
    name: "Turkey Lira Crisis"
    ticker: "XU100.IS"
    start: 2018-05-01
    end: 2019-01-31
    category: regional
  
  # === Novos: asiáticos ===
  - id: asia_1997_hsi
    name: "Asia Financial Crisis — Hong Kong"
    ticker: "^HSI"
    start: 1997-07-01
    end: 1998-12-31
    category: regional
  
  - id: china_2015
    name: "China Stock Crash 2015-2016"
    ticker: "000001.SS"
    start: 2015-06-01
    end: 2016-02-29
    category: crash_linear
  
  - id: japan_lost_decade_segment
    name: "Japan Lost Decade — segment 1995-2003"
    ticker: "^N225"
    start: 1995-01-01
    end: 2003-12-31
    category: lost_decade
    notes: "Range deflacionário plurianual; tipicamente quebra trend-following"
  
  # === Novos: mean-reverting brutais ===
  - id: euro_sovereign_2011
    name: "European Sovereign Debt Crisis"
    ticker: "^STOXX50E"
    start: 2011-05-01
    end: 2012-12-31
    category: mean_reverting_brutal
  
  - id: br_mini_bear_2011
    name: "Brazil Mini-Bear 2011-2012"
    ticker: "^BVSP"
    start: 2011-04-01
    end: 2012-06-30
    category: mean_reverting_brutal
  
  - id: vol_spike_2018_feb
    name: "Volmageddon Feb 2018"
    ticker: "^GSPC"
    start: 2018-01-15
    end: 2018-04-30
    category: mean_reverting_brutal
    notes: "Spike isolado de volatilidade; teste de filtros de regime"
  
  - id: brl_crisis_2020_h2
    name: "BRL Devaluation 2020 H2"
    ticker: "BRL=X"
    start: 2020-07-01
    end: 2020-12-31
    category: regional
    notes: "Cenário forex; teste de adaptive thresholds"
```

Total: **15 cenários** (5 originais + 10 novos).

### E2 — Script `scripts/bear_market_validation_v2.py`

- Lê `scenarios/bears_v2.yaml`.
- Executa cada cenário com config validada no Sprint 21.
- Coleta métricas:
  - Sharpe, PF, Win Rate
  - MDD total + MDD capital-at-risk (do Sprint 18)
  - Tempo no mercado %
  - Alpha vs B&H
  - Custos baseline e estressados (do Sprint 19): slip 0.1% e slip 0.3%
- Tratamento de dados ausentes:
  - Se yfinance não tem dados para o ticker no período, marcar cenário como `data_unavailable` e continuar.
  - Salvar log de quais cenários tiveram dados ausentes.
- Output: `findings/sprint_22_data/bears_complete.csv`

### E3 — Visualizações

1. **Forest plot** de Sharpe por cenário, com intervalo de confiança bootstrap (N=1000):
   - Eixo Y: cenários ordenados por categoria
   - Eixo X: Sharpe com IC 95%
   - Linha vertical em 0 (breakeven)
2. **Forest plot** de MDD capital-at-risk por cenário.
3. **Forest plot** de Alpha vs B&H por cenário.
4. **Scatter** Sharpe vs Time-in-Market por categoria — revela se sistema "funciona ficando fora".
5. **Bar chart** comparativo por categoria (mediana de Sharpe).

Salvar PNGs em `findings/sprint_22_data/plots/`.

### E4 — Testes `tests/unit/test_bear_validation.py`

Mínimo 6 casos:

1. Schema do YAML é validado (campos obrigatórios presentes).
2. Cenário sintético com crash conhecido produz MDD esperado.
3. Cenário sintético com mean-reversion produz `num_trades > N` (sistema opera).
4. Bootstrap CI determinístico com seed.
5. Cenário com data unavailable não quebra script; produz row marcado.
6. Forest plot é gerado sem erros para dados de teste.

### E5 — Relatório `findings/sprint_22_bears_complete.md`

Estrutura obrigatória:

```markdown
# Finding Sprint 22 — Bears Não-Canônicos

## TL;DR
[1-2 frases: "Em X de 15 cenários, sistema preservou capital (MDD-CAR < 5%). 
Em Y cenários, sistema TEVE drawdown maior que B&H."]

## Resultados por categoria
### Crash linear (N cenários)
[Tabela]
### Regional (N cenários)  
[Tabela]
### Mean-reverting brutal (N cenários)
[Tabela]
### Lost decade (1 cenário)
[Tabela]

## Forest plots
[Embedded: 5 plots do E3]

## Cenários onde o sistema FALHOU
[Lista honesta, com diagnóstico:
 - Categoria?
 - Por quê provavelmente falhou?
 - É padrão recuperável (ajuste de parâmetros) ou estrutural?]

## Cenários com data_unavailable
[Lista; documentar limitação de fonte de dados]

## Implicações estratégicas
[Quando recomendar o sistema, quando NÃO recomendar.
Cenário cliente: "estratégia recomendada para mercados X mas com 
cautela em mercados Y."]

## Decisões tomadas
[Atualização do RELATORIO_TECNICO.md seção 7 (Resultados Empíricos):
substituir "7/7 cenários" pela tabela mais ampla e honesta.]
```

---

## 4. Critério de Aceitação

- [ ] Suite completa passa
- [ ] `scenarios/bears_v2.yaml` tem ≥ 15 cenários, ≥ 4 categorias
- [ ] CSV `bears_complete.csv` contém todos os cenários executáveis
- [ ] 5 PNGs de forest plot existem
- [ ] Relatório expõe cenários onde sistema falhou (sem maquiagem)
- [ ] `RELATORIO_TECNICO.md` seção 7 atualizada com a base expandida
- [ ] Se sistema falha em mean-reverting brutal (categoria), isso aparece em letras grandes no TL;DR

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Tickers regionais (^MERV, IMOEX.ME) sem dados via yfinance | Alta | Marcar como `data_unavailable`; documentar limitação |
| Cenários muito antigos (1997, 1998) com qualidade duvidosa | Média | Validar dados antes de incluir; preferir índices que existem em yfinance |
| Sistema falha em > 50% dos novos cenários | Média | Esperado em parte. Reposicionar produto se necessário |
| Computacionalmente caro (15 cenários × otimização) | Baixa | Sem otimização aqui; só backtest com config fixa |

---

## 6. Notas para o Claude Code

- **Dados regionais via yfinance**: alguns tickers funcionam (^STOXX50E, ^N225, XU100.IS); outros são parciais (^MERV histórico curto). Tratar gracefully.
- **Bootstrap CI**: usar `n_samples = 1000`, resample com replacement do array de trades.
- **Forest plots**: usar `errorbar` do matplotlib; ordenar cenários por categoria.
- **Cores por categoria**: definir paleta consistente:
  - crash_linear: azul
  - regional: laranja
  - mean_reverting_brutal: vermelho
  - lost_decade: cinza
- **Validação do YAML**: usar `pydantic` ou validação manual; campos obrigatórios = `id, name, ticker, start, end, category`.

---

## 7. Comandos de validação

```bash
pytest tests/unit/test_bear_validation.py -v
python scripts/bear_market_validation_v2.py
ls findings/sprint_22_data/
cat findings/sprint_22_bears_complete.md | head -50
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — YAML expandido + validação | 0.5 dia |
| E2 — script de execução | 1-1.5 dias |
| E3 — visualizações (forest plots + scatter + bar) | 1 dia |
| E4 — testes | 0.5-1 dia |
| E5 — relatório (interpretação cuidadosa) | 1.5-2 dias |
| Buffer (dados ausentes, edge cases) | 1 dia |
| **Total** | **5-7 dias** |

---

## 9. Próximo passo após este sprint

Após o Sprint 22 fechar, **antes do Sprint 23 começar**, criar `findings/MARCO_BLOCO_I.md` — decisão estratégica de continuidade. Detalhes no template separado.
