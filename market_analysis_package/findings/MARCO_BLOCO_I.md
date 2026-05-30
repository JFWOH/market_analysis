# Marco do Bloco I — Decisão Estratégica de Continuidade

**Status**: 🔴 pending — preencher após Sprint 22 fechar
**Última atualização**: <YYYY-MM-DD>
**Responsável**: Jeferson Wohanka

---

## Como usar este documento

Este arquivo é **template**. Após o Sprint 22 fechar e antes do Sprint 23 começar, ele deve ser preenchido com os achados consolidados dos 5 sprints da auditoria. A decisão registrada aqui determina o destino dos Blocos II e III.

A última linha do documento — `CENARIO_FINAL: <A|B|C>` — é o que define a continuidade do programa. Tudo que vem antes serve para justificar essa única linha.

**Honestidade é o ponto**. Se a evidência aponta para o Cenário C, registrar Cenário A para "não desperdiçar o trabalho" inverte completamente a razão de ser do Bloco I.

---

## 1. Snapshot dos Achados

### Sprint 18 — Drawdown em base dupla

| Métrica | Valor reportado original | Valor MDD-equity | Valor MDD-capital-at-risk |
|---|---|---|---|
| Crash GFC 2008 ^BVSP | 0.74% | <preencher> | <preencher> |
| Crash COVID 2020 ^BVSP | 0.94% | <preencher> | <preencher> |
| Bear 2022 ^IXIC | 1.58% | <preencher> | <preencher> |
| Mediana 7 cenários | ~1% | <preencher> | <preencher> |

**Interpretação**: <a tabela mudou o headline? em que medida?>

Resumo do finding: `findings/sprint_18_mdd_dual.md`

---

### Sprint 19 — Sensibilidade a custos

| Ticker | PF baseline (slip 0.1%) | PF @ slip 0.3% | Breakeven slip |
|---|---|---|---|
| ^BVSP | <preencher> | <preencher> | <preencher>% |
| VALE3.SA | <preencher> | <preencher> | <preencher>% |
| PETR4.SA | <preencher> | <preencher> | <preencher>% |

**Interpretação**: <quantos tickers passam no teste de slip 0.3%?>

Resumo do finding: `findings/sprint_19_cost_sensitivity.md`

---

### Sprint 20 — Decomposição fatorial

| Modelo | Alpha anual | Significativo? (p < 0.05) | R² |
|---|---|---|---|
| CAPM local | <preencher>% | <Sim/Não> | <preencher> |
| CAPM + Momentum | <preencher>% | <Sim/Não> | <preencher> |
| vs Sistema Mínimo (Hurst+ADX) | <preencher>% | <Sim/Não> | <preencher> |

**A pergunta crucial**: o Modelo 3 mostra alpha **estatisticamente significativo** sobre o Sistema Mínimo?

- ☐ Sim — a complexidade do sistema (ensemble + meta-labeler + Fibonacci + Chandelier) agrega valor mensurável
- ☐ Não — Sistema Mínimo captura ≥ 80% do retorno; complexidade adicional é decorativa

Resumo do finding: `findings/sprint_20_factor_decomp.md`

---

### Sprint 21 — Walk-forward honesto

| Método | IS Sharpe mean | OOS Sharpe mean | Degradação |
|---|---|---|---|
| Antigo (params fixos) | <preencher> | <preencher> | <preencher>% |
| Honesto (re-otim) | <preencher> | <preencher> | <preencher>% |

| Ticker | Param stability score (Jaccard) |
|---|---|
| ^BVSP | <preencher> |
| ^GSPC | <preencher> |
| VALE3.SA | <preencher> |

**Classificação da degradação**:
- ☐ Robusto (< 20% de degradação)
- ☐ Moderado overfitting (20-50%)
- ☐ Severo overfitting (50-80%)
- ☐ Artefato de fitting (> 80%)

Resumo do finding: `findings/sprint_21_walkforward_honest.md`

---

### Sprint 22 — Bears não-canônicos

| Categoria | Cenários testados | Cenários aprovados (Sharpe > 0, MDD-CAR < 10%) |
|---|---|---|
| Crash linear | 5 | <preencher>/5 |
| Regional | 4 | <preencher>/4 |
| Mean-reverting brutal | 3 | <preencher>/3 |
| Lost decade | 1 | <preencher>/1 |
| **Total** | **13+** | **<preencher>/13+** |

Cenários com data_unavailable: <listar>

**Cenários onde sistema FALHOU explicitamente**:
- <preencher>
- <preencher>

Resumo do finding: `findings/sprint_22_bears_complete.md`

---

## 2. Síntese Cruzada

Avaliação das três dimensões do produto, agora com evidência empírica:

### Dimensão 1 — Headline (preservação de capital em crashes)
**Antes do Bloco I**: "MDD < 1% em todos os cenários de crise"
**Após Bloco I**:
- MDD-capital-at-risk: <preencher>% (mediana)
- Sistema falhou em <N> de <M> cenários novos
- Veredito: <preservação confirmada | parcialmente confirmada | comprometida>

### Dimensão 2 — Alpha
**Antes do Bloco I**: "Sharpe 1.72 OOS, PF 2.17"
**Após Bloco I**:
- Sharpe OOS honesto (Sprint 21): <preencher>
- Alpha residual após fatores (Sprint 20 Modelo 3): <preencher>% (significativo: <Sim/Não>)
- Veredito: <alpha proprietário | alpha de fator replicável | alpha artefato de seleção>

### Dimensão 3 — Robustez
**Antes do Bloco I**: "validado em 7 crashes históricos"
**Após Bloco I**:
- Cenários totais testados: <preencher>
- Passou em: <preencher>%
- Sensibilidade a custos (Sprint 19): <quantos tickers passam slip 0.3%>
- Veredito: <robusto | moderado | frágil>

---

## 3. Cenários Possíveis

Três caminhos mutuamente exclusivos. Marcar **apenas um**.

---

### ☐ Cenário A — Sistema é Produto

**Condições para escolher A** (todas devem ser verdadeiras):

- [ ] Dimensão 1: preservação **confirmada** em ≥ 80% dos cenários expandidos
- [ ] Dimensão 2: alpha residual significativo no Modelo 3 do Sprint 20
- [ ] Dimensão 3: ≥ 70% dos cenários aprovados; ≥ 2 de 3 tickers passam slip 0.3%
- [ ] Sharpe OOS honesto ≥ 1.0

**Implicação para o programa**:
- Bloco II prossegue como planejado (audit log, kill switch, SQLite, CI)
- Bloco III constrói UI completa para uso operacional
- Sprint 32 (Paper Trading Live) é destino final do programa
- Pode considerar futuramente integração com corretora real (fora deste programa)

**O que muda no `RELATORIO_TECNICO.md`**:
- Headlines do Sumário Executivo atualizados com números honestos
- Seção "Limitações conhecidas" expandida com achados dos Sprints 19, 20, 22
- Mantém posicionamento de "downside protection insurance"

---

### ☐ Cenário B — Sistema é Laboratório

**Condições para escolher B**:

- [ ] Dimensão 1: preservação **parcial** (50-80% dos cenários)
- [ ] Dimensão 2: alpha residual marginal ou não-significativo
- [ ] Dimensão 3: passa em algumas mas não na maioria; fragilidade visível a slip 0.3%
- [ ] Sharpe OOS honesto entre 0.4 e 1.0

**Implicação para o programa**:
- Bloco II prossegue, mas com posicionamento ajustado:
  - UI é **ferramenta de pesquisa**, não plataforma de operação
  - Sprint 32 (Paper Trading Live) é entregue mas marcado como "modo experimental"
  - Foco do produto desloca para: "framework reproduzível de backtesting + replay + análise estatística"
- Valor estratégico permanece (educação, base para pesquisa futura, talvez consultoria)
- Não recomendado para uso com capital real

**O que muda no `RELATORIO_TECNICO.md`**:
- Reposicionamento explícito do produto
- Sumário Executivo reescrito: "ferramenta de pesquisa quantitativa para estudo de estratégias trend-following com regime filtering"
- Seção 1.1 (Perfil estratégico validado) reduzida para apresentar apenas a dimensão onde performance é demonstrada (provavelmente preservação em crashes lineares)
- Seção sobre "Sistema Mínimo" adicionada se Sprint 20 mostrar que ele captura a maior parte do retorno

---

### ☐ Cenário C — Sistema Precisa Rework

**Condições para escolher C** (qualquer uma é suficiente):

- [ ] Dimensão 1: preservação **fictícia** — MDD-capital-at-risk revela drawdowns reais > 15% em cenários documentados
- [ ] Dimensão 2: alpha **não-significativo** em Modelo 3 + degradação severa em Sprint 21
- [ ] Dimensão 3: sistema falha em mais de 50% dos cenários expandidos
- [ ] Sharpe OOS honesto < 0.4

**Implicação para o programa**:
- **Bloco II é SUSPENSO**. Não faz sentido endurecer infra para sistema sem edge demonstrado.
- **Bloco III é SUSPENSO**. Não construir UI para algo que precisa ser reformulado.
- Novo programa de pesquisa exploratória precisa ser planejado:
  - Identificar onde o sistema mínimo (Hurst+ADX) tem edge real
  - Reconstruir partes da estratégia sobre base validada
  - Possivelmente abandonar componentes (ex.: Fibonacci se Sprint 20 mostrar inutilidade)
- Estimativa de rework: 3-6 meses adicionais antes de retomar Blocos II/III

**O que muda no `RELATORIO_TECNICO.md`**:
- Documento atual é arquivado como `RELATORIO_TECNICO_v0_pre_audit.md`
- Novo `RELATORIO_TECNICO_audit_findings.md` explica o que aprendemos
- Roadmap de pesquisa exploratória substitui Sprints 23-33

---

## 4. Decisão final

**Cenário escolhido**: <A | B | C>

**Justificativa em uma frase**:
<preencher — esta é a frase que justifica todas as decisões dos próximos 3-6 meses>

**Aprovado por**: Jeferson Wohanka
**Data da decisão**: <YYYY-MM-DD>

---

## 5. Ações imediatas pós-decisão

Após preencher este arquivo, executar **antes** de qualquer linha de código do Sprint 23:

- [ ] Commitar este arquivo como `findings/MARCO_BLOCO_I.md` com mensagem `audit(marco): decisão de continuidade do programa`
- [ ] Atualizar `RELATORIO_TECNICO.md` conforme implicações do cenário escolhido
- [ ] Atualizar `sprints/ROADMAP.md` v2.0 refletindo o cenário (se A: nenhuma mudança; se B: ajustes; se C: substituição)
- [ ] Se Cenário C: criar novo arquivo `sprints/EXPLORATORIO_ROADMAP.md` substituindo o programa atual
- [ ] Comunicar a decisão a quaisquer stakeholders (se houver)

---

## 6. Linha de máquina

Esta linha é parseada por scripts e ferramentas. Preencher exatamente:

```
CENARIO_FINAL: <preencher: A | B | C>
DATA_DECISAO: <preencher: YYYY-MM-DD>
SHARPE_OOS_HONESTO: <preencher: número>
DEGRADACAO_IS_OOS_PCT: <preencher: número>
ALPHA_RESIDUAL_SIGNIFICATIVO: <preencher: true | false>
CENARIOS_APROVADOS: <preencher: N>/<preencher: total>
```

---

## 7. Nota sobre honestidade

Se a evidência aponta para C e este arquivo registra A, três pessoas saberão: o autor, o próximo desenvolvedor que tentar continuar o trabalho, e (se houver capital alocado) a realidade do mercado.

A primeira função do Bloco I não é validar uma tese pré-formada. É descobrir a verdade. O custo de descobrir tarde demais — depois de meses de Bloco II/III e potencialmente de capital empregado — é desproporcionalmente maior que o custo de pivotar agora.

O Cenário B é mais frequente do que se reconhece na literatura. A maioria das estratégias quant publicadas e replicadas honestamente cai nessa categoria. **Não é fracasso**. É **calibração**.
