# Finding Sprint 21 — Walk-Forward Honesto com Re-otimização

**Status**: 🔴 template — preencher após execução do Sprint 21
**Data**: <YYYY-MM-DD>
**Autor**: Jeferson Wohanka
**Sprint relacionado**: `sprints/sprint_21_walkforward.md`
**Tag pós-finding**: `v0.21.0`

---

## TL;DR

Walk-forward com re-otimização **dentro** de cada janela IS, aplicado em três tickers:

- **^BVSP**: IS Sharpe = <preencher>, OOS Sharpe = <preencher>, degradação = <preencher>%
- **^GSPC**: IS Sharpe = <preencher>, OOS Sharpe = <preencher>, degradação = <preencher>%
- **VALE3.SA**: IS Sharpe = <preencher>, OOS Sharpe = <preencher>, degradação = <preencher>%

**Comparação com método antigo** (params fixos):
- Antigo: OOS Sharpe = 1.72 (reportado no RELATORIO_TECNICO)
- Honesto: OOS Sharpe = <preencher>
- Gap: <preencher> pontos de Sharpe → estimativa de data dredging na seleção original

**Classificação do overfitting**: <robusto | moderado | severo | artefato>

---

## Metodologia

### O problema com o walk-forward original

O `walk_forward_real.py` e `walk_forward_sprintN.py` originais usam params fixos — selecionados uma vez sobre o histórico inteiro, depois aplicados em janelas rolantes. Isso mede apenas "OOS do meta-labeler", não "OOS da seleção de hiperparâmetros".

A seleção de hiperparâmetros é a fonte principal de overfitting estatístico, e portanto a degradação medida pelo método original é **subestimada**.

### O walk-forward honesto

Para cada fold:
1. Define janelas IS e OOS sequenciais (com embargo entre elas)
2. **Re-otimiza** params dentro de IS (grid search ou Optuna, depende do espaço)
3. Aplica os params ótimos **daquela janela** em OOS
4. Registra ambas as métricas
5. Repete

A degradação IS→OOS observada é estimativa não-enviesada de overfitting.

### Parâmetros do walk-forward

- N folds: 5
- IS window: 504 barras (~2 anos)
- OOS window: 252 barras (~1 ano)
- Embargo: 20 barras
- Modo: anchored (IS_start fixo)
- Param space: <listar 5-8 params críticos otimizados>
- Otimizador: <grid | optuna>
- Métrica: Sharpe DSR (Deflated Sharpe Ratio)

---

## Resultados por ticker

### ^BVSP

| Fold | IS Sharpe | IS PF | OOS Sharpe | OOS PF | Degradação Sharpe | Best params |
|---|---|---|---|---|---|---|
| 1 | <preencher> | <preencher> | <preencher> | <preencher> | <preencher>% | <preencher> |
| 2 | <preencher> | <preencher> | <preencher> | <preencher> | <preencher>% | <preencher> |
| 3 | <preencher> | <preencher> | <preencher> | <preencher> | <preencher>% | <preencher> |
| 4 | <preencher> | <preencher> | <preencher> | <preencher> | <preencher>% | <preencher> |
| 5 | <preencher> | <preencher> | <preencher> | <preencher> | <preencher>% | <preencher> |
| **Média** | **<preencher>** | **<preencher>** | **<preencher>** | **<preencher>** | **<preencher>%** | |

Param stability score (Jaccard top-3 entre folds consecutivos): <preencher>

Visualização: `findings/sprint_21_data/wf_bvsp_folds.png`

### ^GSPC

<repetir estrutura>

### VALE3.SA

<repetir estrutura>

---

## Comparação com walk-forward antigo

| Método | Ticker | IS Sharpe mean | OOS Sharpe mean | Degradação | Param stability |
|---|---|---|---|---|---|
| Antigo (params fixos) | ^BVSP | 1.85* | 1.72* | -7% | N/A (params únicos) |
| Honesto (re-otim) | ^BVSP | <preencher> | <preencher> | <preencher>% | <preencher> |
| Antigo | ^GSPC | <preencher>* | <preencher>* | <preencher>% | N/A |
| Honesto | ^GSPC | <preencher> | <preencher> | <preencher>% | <preencher> |
| Antigo | VALE3.SA | <preencher>* | <preencher>* | <preencher>% | N/A |
| Honesto | VALE3.SA | <preencher> | <preencher> | <preencher>% | <preencher> |

\* Valores do RELATORIO_TECNICO.md original — re-executados com mesmo dataset para comparabilidade justa.

**Gap médio entre métodos**: <preencher> pontos de Sharpe.

Esse gap é a estimativa empírica de **data dredging** na seleção original — quanto da performance reportada vem de olhar para o histórico inteiro ao escolher params.

---

## Param stability — análise detalhada

Top-3 params por Sharpe IS em cada fold:

### ^BVSP

| Fold | Top-1 params | Top-2 params | Top-3 params |
|---|---|---|---|
| 1 | <preencher> | <preencher> | <preencher> |
| 2 | <preencher> | <preencher> | <preencher> |
| ... | ... | ... | ... |

**Jaccard similarity** entre folds consecutivos:
- Folds 1-2: <preencher>
- Folds 2-3: <preencher>
- Folds 3-4: <preencher>
- Folds 4-5: <preencher>
- **Média**: <preencher>

**Interpretação**:
- Jaccard > 0.6 = top-K converge para mesma região do espaço → params estáveis → robusto
- Jaccard 0.3-0.6 = parcial overlap → param landscape suave
- Jaccard < 0.3 = top-K muda drasticamente entre folds → overfitting

### Parâmetros mais frequentemente ótimos

Quais parâmetros aparecem em quase todos os top-3 dos folds? Esses são os "modos estáveis":

| Parâmetro | Valor mais frequente | Frequência |
|---|---|---|
| <ex: adx_threshold> | <ex: 25> | <ex: 5/5 folds> |
| <ex: hurst_threshold> | <ex: 0.55> | <ex: 4/5 folds> |
| <ex: chandelier_atr_mult> | <ex: 3.0> | <ex: 3/5 folds> |
| ... | ... | ... |

Params que NUNCA aparecem entre top-3 podem ser candidatos a remoção do espaço de busca futuro.

---

## Interpretação

### Classificação da degradação (média across tickers)

Limiares pré-acordados:
- **< 20%**: robusto. Estratégia tem edge real. Manter config atual.
- **20-50%**: moderado overfitting. Estratégia tem edge mas reportar números honestos.
- **50-80%**: severo overfitting. Considerar simplificação ou abandono.
- **> 80%**: artefato de fitting. Estratégia não tem edge demonstrável.

**Classificação obtida**: <preencher>

### O que isso significa para o produto

<preencher conforme classificação>

**Se robusto**: o headline "Sharpe 1.72" sobrevive em essência. Reportar Sharpe OOS honesto = <preencher>, ligeiramente menor mas dentro do erro de estimativa.

**Se moderado**: reportar **intervalo** (IS-OOS) como faixa de incerteza. Algo como "Sharpe esperado: 0.8 a 1.6 (faixa IS-OOS)". Mais honesto e útil para dimensionar capital.

**Se severo**: a config atual está overfitted. Buscar config mais simples (Sistema Mínimo do Sprint 20?) ou aceitar que o produto tem performance esperada bem menor que o headline original.

**Se artefato**: cenário crítico. Estratégia não tem edge demonstrável após corrigir o overfitting da seleção. Marco do Bloco I aponta para Cenário C.

### Cross-ticker

Tickers com degradação muito diferente sugerem que:
- A estratégia funciona melhor em alguns mercados que outros (esperado)
- Ou a otimização está pegando ruído específico de cada ticker (preocupante)

Param stability inter-ticker:
- Tickers chegam aos mesmos params ótimos? → estratégia é genérica
- Cada ticker quer params diferentes? → estratégia precisa calibração por ativo (ou está overfitting padrões específicos)

---

## Implicações estratégicas

### Para o `RELATORIO_TECNICO.md`

Atualizar Sharpe reportado pelo Sharpe OOS honesto:

- [ ] Seção 1.1 (Perfil estratégico): substituir "Sharpe mediana +1.72" pelo valor honesto
- [ ] Seção 5.7.3 (Validação OOS): adicionar metodologia honesta como referência principal
- [ ] Seção 7.1 (Evolução do PF): tabela renovada com OOS honesto + IS para contexto
- [ ] Seção 8.1 (Análise para quants): nota sobre walk-forward honesto vs antigo

### Para o `MARCO_BLOCO_I.md`

Este finding alimenta a Dimensão 2 (Alpha) e a classificação geral:
- Degradação < 20% favorece Cenário A
- Degradação 20-50% favorece Cenário B
- Degradação > 50% favorece Cenário C

### Para Sprints futuros

Se degradação > 50%, considerar Sprint 21.5 (não planejado) "Config robusta":
- Buscar config com menos parâmetros otimizados
- Re-rodar walk-forward
- Reportar Sharpe ainda menor mas mais defensável

Decisão sobre 21.5: <preencher>

---

## Decisões tomadas

1. **Sharpe oficial do sistema**: <preencher> (OOS honesto, média across tickers)
2. **Config de referência**: <manter Sprint-13 | mudar para X>
3. **Espaço de otimização default**: <preencher dimensões removidas, se aplicável>
4. **UI mostrará param stability score** ao usuário ao carregar preset (Sprint 30)
5. **Re-execução periódica**: walk-forward honesto deve ser re-rodado a cada 6 meses para detectar drift

---

## Limitações deste finding

- **N de folds = 5**: estatisticamente modesto. Variabilidade entre folds pode ser grande.
- **Param space limitado**: otimizamos 5-8 params dos 30+ disponíveis. Outros params estão fixos. Trade-off entre cobertura e tempo de computação.
- **Embargo de 20 barras**: pode ser insuficiente para meta-labeler que aprende sobre triple-barrier de 60+ barras. Considerar aumentar para 60 em rodada futura.
- **DSR (Deflated Sharpe Ratio)**: tenta penalizar múltiplas hipóteses mas tem premissas sobre distribuição que podem ser violadas em finanças. Bootstrap como validação adicional seria desejável (não escopo deste sprint).
- **Walk-forward anchored**: IS cresce a cada fold. Versão sliding (IS_start avança) testa diferente tipo de robustez (estacionariedade do processo). Atual mistura tipos de evidência.

---

## Próximos passos

- [ ] Sprint 22 (bears expandido) usa a config validada aqui — não a do RELATORIO_TECNICO original
- [ ] Atualizar `configs/presets/sprint_13_reference.yaml` com Sharpe OOS honesto na descrição
- [ ] Adicionar campo `sharpe_oos_honest` nos metadados de cada preset
- [ ] Se houver Sprint 21.5 (config robusta), criar `configs/presets/robust_simplified.yaml`
