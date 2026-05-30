# Finding Sprint 22 — Bears Não-Canônicos: Validação Expandida

**Status**: 🔴 template — preencher após execução do Sprint 22
**Data**: <YYYY-MM-DD>
**Autor**: Jeferson Wohanka
**Sprint relacionado**: `sprints/sprint_22_bears_extras.md`
**Tag pós-finding**: `v0.22.0`

---

## TL;DR

Validação expandida em **15+ cenários** (vs 7 originais), incluindo:
- 5 crashes lineares clássicos (controle)
- 4 cenários regionais (Argentina, Rússia, Turquia, Ásia 1997)
- 3 mean-reverting brutais (Euro 2011, BR 2011-12, Volmageddon 2018)
- 1 lost decade (Japão 1995-2003)

**Resultado consolidado** (com config validada no Sprint 21):

- Cenários **aprovados** (Sharpe > 0 e MDD-CAR < 10%): <preencher>/<total>
- Cenários onde sistema **falhou** (Sharpe < 0 ou MDD-CAR > 15%): <preencher>/<total>
- Cenários com **dados indisponíveis**: <preencher>

**Por categoria**:

| Categoria | Aprovados | Reprovados | Indisponíveis |
|---|---|---|---|
| Crash linear | <preencher> | <preencher> | <preencher> |
| Regional | <preencher> | <preencher> | <preencher> |
| Mean-reverting brutal | <preencher> | <preencher> | <preencher> |
| Lost decade | <preencher> | <preencher> | <preencher> |

**Veredito**: <sistema robusto cross-cenário | parcial | frágil em categoria X>

---

## Metodologia

- **Lista completa**: `scenarios/bears_v2.yaml`
- **Config usada**: <Sprint-13 reference | Robusta simplificada do Sprint 21.5>
- **Métricas coletadas por cenário**:
  - Sharpe, PF, Win Rate
  - MDD total (Sprint 18) e MDD-capital-at-risk (Sprint 18)
  - Time-in-market %
  - Alpha vs B&H
  - PF estressado com slip 0.3% (Sprint 19)
- **Bootstrap CI**: N=1000 resamples para intervalos de confiança 95% no Sharpe
- **Dados indisponíveis**: cenários onde yfinance não retorna histórico completo são marcados separadamente

---

## Resultados por categoria

### Crash linear (5 cenários — controle)

| Cenário | Ticker | Sharpe (IC 95%) | MDD-equity | MDD-CAR | Alpha vs B&H | Status |
|---|---|---|---|---|---|---|
| GFC 2008 ^BVSP | ^BVSP | <preencher> | <preencher>% | <preencher>% | +<preencher>pp | <preencher> |
| GFC 2008 ^GSPC | ^GSPC | <preencher> | <preencher>% | <preencher>% | +<preencher>pp | <preencher> |
| COVID 2020 ^BVSP | ^BVSP | <preencher> | <preencher>% | <preencher>% | +<preencher>pp | <preencher> |
| Bear 2022 ^IXIC | ^IXIC | <preencher> | <preencher>% | <preencher>% | +<preencher>pp | <preencher> |
| 2015 BR bear | ^BVSP | <preencher> | <preencher>% | <preencher>% | +<preencher>pp | <preencher> |

**Subtotal aprovados**: <N>/5

**Comentário**: <espera-se que todos passem; são os cenários onde o sistema foi originalmente validado>

### Regional (4 cenários — novos)

| Cenário | Ticker | Sharpe (IC 95%) | MDD-equity | MDD-CAR | Alpha vs B&H | Status |
|---|---|---|---|---|---|---|
| Argentina 2001 | ^MERV | <preencher> | <preencher>% | <preencher>% | <preencher>pp | <preencher> |
| Rússia 2014 | IMOEX.ME | <preencher> | <preencher>% | <preencher>% | <preencher>pp | <preencher> |
| Turquia 2018 | XU100.IS | <preencher> | <preencher>% | <preencher>% | <preencher>pp | <preencher> |
| Ásia 1997 — HSI | ^HSI | <preencher> | <preencher>% | <preencher>% | <preencher>pp | <preencher> |

**Subtotal aprovados**: <N>/4

**Comentário**: <esses são cenários com dinâmicas específicas — moeda, geopolítica, contágio. Sistema robusto deveria preservar capital aqui também.>

### Mean-reverting brutal (3 cenários — exatamente onde trend-following sofre)

| Cenário | Ticker | Sharpe (IC 95%) | MDD-equity | MDD-CAR | Alpha vs B&H | Status |
|---|---|---|---|---|---|---|
| Euro sovereign 2011 | ^STOXX50E | <preencher> | <preencher>% | <preencher>% | <preencher>pp | <preencher> |
| BR mini-bear 2011 | ^BVSP | <preencher> | <preencher>% | <preencher>% | <preencher>pp | <preencher> |
| Volmageddon 2018 | ^GSPC | <preencher> | <preencher>% | <preencher>% | <preencher>pp | <preencher> |

**Subtotal aprovados**: <N>/3

**Comentário**: <esta categoria é onde a tese "filtro de regime previne entradas em mean-reverting" é testada. Se sistema falha aqui, a defesa é insuficiente.>

### Lost decade (1 cenário — caso extremo)

| Cenário | Ticker | Sharpe (IC 95%) | MDD-equity | MDD-CAR | Alpha vs B&H | Status |
|---|---|---|---|---|---|---|
| Japan 1995-2003 | ^N225 | <preencher> | <preencher>% | <preencher>% | <preencher>pp | <preencher> |

**Comentário**: <range deflacionário plurianual; tipicamente quebra trend-following. Esperado: tempo no mercado < 20%, Sharpe próximo de zero, MDD-CAR baixo. Se sistema NÃO ficar fora, é diagnóstico de falha no filtro de regime para este regime específico.>

### Forex (1 cenário — sanity check)

| Cenário | Ticker | Trades | Sharpe | Status |
|---|---|---|---|---|
| BRL Devaluation 2020 H2 | BRL=X | <preencher> | <preencher> | <preencher> |

**Comentário**: <a tabela do RELATORIO_TECNICO mostra 0 trades em BRL=X com config Sprint-13; este cenário valida ou contradiz>

---

## Forest plots

### Sharpe por cenário (IC 95% bootstrap)

`findings/sprint_22_data/plots/forest_sharpe.png`

Visualização ordenada por categoria, com linha vertical em Sharpe=0. Cenários com IC inteiramente positivo são "significantemente positivos"; cenários cruzando zero são inconclusivos.

### MDD-CAR por cenário

`findings/sprint_22_data/plots/forest_mdd_car.png`

### Alpha vs B&H por cenário

`findings/sprint_22_data/plots/forest_alpha.png`

### Sharpe vs Time-in-Market (scatter por categoria)

`findings/sprint_22_data/plots/scatter_sharpe_tim.png`

Insight esperado: cenários onde sistema ficou fora 80%+ do tempo têm Sharpe-CAR alto (capital empregado teve edge) ou MDD-CAR baixo (não houve drama no pouco que operou).

### Mediana por categoria (bar chart)

`findings/sprint_22_data/plots/category_medians.png`

---

## Cenários onde sistema FALHOU

Listagem honesta dos casos onde o sistema teve Sharpe < 0 ou MDD-CAR > 15%:

### <Cenário 1>
- **Categoria**: <preencher>
- **Diagnóstico do operador**: <por que o filtro de regime não impediu entrada? por que trades foram para SL repetidamente?>
- **Causa provável**: <ex: ADX e Hurst estavam acima do limiar mas em regime "trending para baixo" que quebra inesperadamente>
- **Recuperável**: <Sim, com ajuste X | Não, é falha estrutural>

### <Cenário 2>
<repetir estrutura>

---

## Cenários com data_unavailable

Listagem com motivo:

| Cenário | Ticker | Motivo |
|---|---|---|
| <ex: Asia 1997 — HSI> | ^HSI | yfinance retorna apenas dados pós-2000 para este símbolo |
| <preencher> | <preencher> | <preencher> |

**Limitação documentada**: dados regionais de mercados emergentes nos anos 1990 são parcialmente cobertos por yfinance gratuito. Para análise completa, fonte alternativa (Bloomberg, Refinitiv) seria necessária — fora do escopo atual.

---

## Interpretação consolidada

### Onde o sistema funciona consistentemente

<preencher categorias e tipos onde performance é positiva e estável>

Exemplo: "Sistema preserva capital de forma consistente em crashes lineares (5/5) e crashes regionais com componente de moeda (3/4). Em mean-reverting brutais o desempenho é misto (1/3 aprovado)."

### Onde o sistema é frágil

<preencher categorias onde sistema repetidamente falha>

Exemplo: "Mean-reverting brutais (BR 2011-12, Volmageddon 2018) expõem limitação do filtro de regime quando ADX/Hurst momentâneo sinaliza tendência mas regime real é oscilatório."

### Sobre os "alpha negativos" em cenários bull-like dentro de períodos bear

Alguns dos novos cenários têm sub-períodos de recuperação. Se sistema ficou fora durante a recuperação, alpha vs B&H pode ser **negativo** mesmo em "bear", refletindo o trade-off documentado: prêmio em bull, sinistro em crash.

---

## Implicações estratégicas

### Para recomendação de uso (Sprint 31 — relatórios)

A UI/relatórios devem disclosure ao usuário:

> "Esta estratégia foi validada em N cenários. Performance esperada é favorável em [categorias X]. Em [categorias Y] o desempenho é misto ou negativo. Use com cautela em mercados Y."

### Para o `RELATORIO_TECNICO.md`

- [ ] Seção 1.2 (Validação contra crashes): substituir "7 cenários" pela tabela expandida
- [ ] Seção 7 (Resultados): adicionar subseção "Validação expandida cross-categoria"
- [ ] Seção 7.3 (Limitações): atualizar com categorias onde falhou
- [ ] Conclusão: reformular se base ampliada contradisser narrativa original

### Para o `MARCO_BLOCO_I.md`

Este finding alimenta diretamente a Dimensão 1 (Preservação) e Dimensão 3 (Robustez):
- ≥ 80% aprovados → Cenário A
- 50-80% aprovados → Cenário B
- < 50% aprovados → Cenário C

---

## Decisões tomadas

1. **Cenários canônicos do produto**: lista oficial é `scenarios/bears_v2.yaml`. Adições futuras seguem o mesmo schema.
2. **Re-execução automatizada**: criar `scripts/regression_bears.py` que roda em CI quando há mudança em código de estratégia (Sprint 26)
3. **Disclosure em UI**: relatórios (Sprint 31) incluem tabela das categorias e onde estratégia se aplica
4. **Documentar limitação de fonte de dados**: README do projeto menciona que algumas validações regionais usam yfinance e podem ter cobertura parcial

---

## Limitações deste finding

- **Sobrevivência narrativa parcialmente persiste**: ainda estamos escolhendo cenários conhecidos. Para teste verdadeiramente robusto, walk-forward em janelas aleatórias do histórico inteiro seria complementar (não escopo atual).
- **Sample size por categoria modesto**: 3-4 cenários por categoria é pouco para conclusões fortes. Adicionar cenários no futuro (lista de candidatos: 2020 Saudi-Russia oil war, 2022 EUR-USD parity, 1994 Mexican Tequila, etc).
- **yfinance qualidade variável** para tickers regionais antigos.
- **Custos modelados otimistas para regiões**: spread em ações da Turquia ou Argentina é tipicamente maior que B3. Sprint 19 modelou só BR; aplicar mesma sensibilidade aos regionais seria ideal.

---

## Próximos passos

- [ ] Finalizar Marco do Bloco I com este finding como input principal da Dimensão 1 e 3
- [ ] Se Cenário A ou B no Marco: prosseguir para Sprint 23 (Bloco II)
- [ ] Se Cenário C: pausar programa e planejar pesquisa exploratória
- [ ] Adicionar `scripts/regression_bears.py` em pipeline CI (Sprint 26)
