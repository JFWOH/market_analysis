# Finding Sprint 19 — Sensibilidade a Custos de Transação

**Status**: 🟢 preenchido (execução real, dados yfinance)
**Data**: 2026-06-01
**Autor**: Jeferson Wohanka
**Sprint relacionado**: `sprints/sprint_19_custos.md`
**Tag pós-finding**: `v0.19.0`

---

## TL;DR

> ## ⚠️ ⚠️ ⚠️ ^BVSP NÃO SOBREVIVE A SLIPPAGE 0.3% — E NÃO TEM EDGE NEM SEM CUSTOS ⚠️ ⚠️ ⚠️
>
> **Na janela OOS (últimos 30% = 2018-07 a 2026-05), a config Sprint-13 sobre ^BVSP
> tem PF = 0.82 já no baseline (slip 0.1% / comm 0.1%), cai para PF = 0.69 com slip
> 0.3%, e o retorno BRUTO (custo zero) é NEGATIVO (−0.71%). Não existe breakeven:
> não há edge a custo NENHUM. O ticker principal do sistema falha o teste de robustez
> de custos de forma decisiva.**

Três números por ticker (comissão fixa 0.1%):

> - **^BVSP**: PF baseline = **0.82**; cai para **0.69** em slip 0.3%; **breakeven = N/A (sem edge nem a custo zero)**. ❌
> - **VALE3.SA**: PF baseline = **1.43**; cai para **1.34** em slip 0.3%; **breakeven ≈ 0.88%**. ✅ (ressalva: só 16 trades, retorno absoluto ~nulo).
> - **PETR4.SA**: PF = **0.00** (apenas 3 trades em 8 anos, todos perdedores); amostra insuficiente — sem veredito estatístico. ❌
> - **Veredito**: **1 de 3 tickers** passa no teste de robustez (PF > 1.0 com slip 0.3%) — e o único que passa o faz com retorno economicamente desprezível.

---

## Metodologia

- **Grade de busca**: commission ∈ {0.05%, 0.1%, 0.2%, 0.5%} × slippage ∈ {0.05%, 0.1%, 0.2%, 0.3%, 0.5%} (20 células/ticker).
- **Janela**: OOS = **últimos 30% das barras** de cada ticker (split proporcional, coerente com `expected_return_analysis` e Sprint-18).
- **Config**: Sprint-13 reference (`SPRINT13_PARAMS`, importado de `scripts/bear_market_validation.py` — DRY; ainda não há registry YAML).
- **Breakeven**: busca binária com tolerância 1%, comissão fixa 0.1%, faixa de slippage [0.01%, 1.0%].
- **Métrica observada**: Profit Factor (primária), Sharpe (secundária).
- **Dados**: reais (fonte `yfinance`, v8 chart API). Conectividade verificada ANTES da execução; a disciplina do Sprint-18 (abortar se a fonte voltar `synthetic`) está codificada em `run_ticker` — nenhum número aqui é fabricado.

Detalhes em `scripts/cost_sensitivity.py` (núcleo: `cost_sensitivity_sweep`, `find_breakeven_slippage`; CLI: `run_ticker` / `main`).

### Disclosures obrigatórias (LEIA antes de interpretar os números)

1. **Comissão percentual com a absoluta zerada.** O eixo "comissão" do sweep usa o
   parâmetro **`commission_pct`** (fracionário, adicionado no Sprint-19), e **zera a
   comissão absoluta de R$ 5/trade** (`commission_per_trade=0.0`) do baseline padrão do
   motor. Isso isola o eixo percentual. **Consequência:** estes PFs **não são
   diretamente comparáveis** aos do `RELATORIO_TECNICO.md`, que assumiam outro modelo de
   custo. A comparação correta é interna a este sweep (célula vs célula).

2. **As janelas de 30% diferem por ticker (datas de calendário).** Como cada ticker tem
   seu próprio número de barras, o "último 30%" cai em datas de início diferentes:
   ^BVSP começa em **2018-07-04** (1963 barras), VALE3.SA e PETR4.SA em **2018-05-28**
   (1989 barras). Todos terminam em 2026-05-29. Isso é consequência do 30% proporcional,
   não um bug — mas significa que os tickers **não cobrem exatamente o mesmo período**.

3. **Slippage e comissão são eixos NÃO-redundantes.** Slippage move o **preço de
   execução** em ambas as pernas (entrada `×(1+slip)`, saída `×(1−slip)`) e, portanto,
   **afeta também o sizing** (via `entry_price`/stop). `commission_pct` é uma **dedução
   fracionária direta do PnL** e **não afeta o sizing**. Por isso o heatmap não é
   degenerado na diagonal — os dois eixos carregam informação distinta.

---

## Resultados por ticker

### ^BVSP — ❌ NÃO PASSA (sem edge)

Profit Factor (linhas = slippage, colunas = comissão):

| Slippage \ Commission | 0.05% | 0.1% | 0.2% | 0.5% |
|---|---|---|---|---|
| 0.05% | 0.90 | 0.86 | 0.79 | 0.61 |
| 0.10% | 0.86 | **0.82** | 0.75 | 0.58 |
| 0.20% | 0.67 | 0.64 | 0.59 | 0.44 |
| 0.30% | 0.72 | **0.69** | 0.63 | 0.49 |
| 0.50% | 0.48 | 0.46 | 0.42 | 0.31 |

- **PF baseline** (slip 0.1%, comm 0.1%): **0.82** — já abaixo de 1.0.
- **PF @ slip 0.3% comm 0.1%**: **0.69**.
- **Breakeven slip** (comm fixa 0.1%): **N/A** — PF < 1.0 mesmo no slippage mínimo da faixa; não há slippage que "zere" um edge que não existe.
- **Retorno bruto (custo zero)**: **−0.71%** sobre 8 anos — negativo antes de qualquer custo. 115 trades, win_rate ~61% (muitos ganhos pequenos, poucas perdas grandes → PF < 1).
- Toda a superfície (20 células) está **abaixo de 1.0**.

Heatmap PF: `findings/sprint_19_data/heatmap_sprint_13_bvsp_pf.png`
Heatmap Sharpe: `findings/sprint_19_data/heatmap_sprint_13_bvsp_sharpe.png`
Curva de degradação: `findings/sprint_19_data/degradation_bvsp.png`

### VALE3.SA — ✅ PASSA (com ressalva forte)

| Slippage \ Commission | 0.05% | 0.1% | 0.2% | 0.5% |
|---|---|---|---|---|
| 0.05% | 1.48 | 1.46 | 1.42 | 1.31 |
| 0.10% | 1.45 | **1.43** | 1.40 | 1.28 |
| 0.20% | 1.41 | 1.39 | 1.35 | 1.24 |
| 0.30% | 1.36 | **1.34** | 1.31 | 1.20 |
| 0.50% | 1.30 | 1.29 | 1.25 | 1.15 |

- **PF baseline**: **1.43**.
- **PF @ slip 0.3% comm 0.1%**: **1.34**.
- **Breakeven slip** (comm fixa 0.1%): **≈ 0.88%** (extrapolado pela busca binária além da grade; convergiu). Sobrevive a toda a grade testada (até slip 0.5%).
- **Ressalva crítica**: apenas **16 trades** em 8 anos; retorno baseline = **+0.66%** total (≈ nulo em termos econômicos). PF alto sobre amostra mínima — sobrevive aos custos porque mal toca o mercado, não porque tem edge robusto e ativo.

Heatmap PF: `findings/sprint_19_data/heatmap_sprint_13_vale3_pf.png`
Curva de degradação: `findings/sprint_19_data/degradation_vale3.png`

### PETR4.SA — ❌ NÃO PASSA (amostra degenerada)

Toda a superfície é **PF = 0.00**: o motor disparou apenas **3 trades** em 8 anos de OOS,
**todos perdedores** (win_rate = 0, gross_profit = 0 → PF = 0). Retorno baseline −0.81%,
bruto −0.76%.

| Slippage \ Commission | 0.05% | 0.1% | 0.2% | 0.5% |
|---|---|---|---|---|
| (todas as células) | 0.00 | 0.00 | 0.00 | 0.00 |

- **Veredito**: amostra **insuficiente** (3 trades) para qualquer afirmação de robustez.
  Análoga à exclusão do BRL=X prevista no template — a config Sprint-13 simplesmente não
  ativa em PETR4 nesta janela. Não é "passa" nem "falha por custo": é "não há o que medir".

Heatmap PF: `findings/sprint_19_data/heatmap_sprint_13_petr4_pf.png`
Curva de degradação: `findings/sprint_19_data/degradation_petr4.png`

---

## Tabela consolidada

| Ticker | OOS (início→fim) | barras | PF baseline | PF @ slip 0.3% | Breakeven slip | Passa @ 0.3%? |
|---|---|---|---|---|---|---|
| ^BVSP | 2018-07-04→2026-05-29 | 1963 | 0.82 | 0.69 | N/A (sem edge) | **Não** |
| VALE3.SA | 2018-05-28→2026-05-29 | 1989 | 1.43 | 1.34 | ≈ 0.88% | **Sim*** |
| PETR4.SA | 2018-05-28→2026-05-29 | 1989 | 0.00 | 0.00 | N/A (3 trades) | **Não** |

Critério "Passa @ 0.3%": PF > 1.0 com slip 0.3% e comm 0.1%.
\* VALE3.SA passa o critério de PF mas com retorno absoluto desprezível e amostra pequena (16 trades).

Fonte: `findings/sprint_19_data/breakeven_summary.csv` (+ `sweep_{bvsp,vale3,petr4}.csv`).

---

## Interpretação

### Diagnóstico de fragilidade

O resultado é o **pior cenário previsto pela própria spec** (§5, "Findings revelam
fragilidade do produto — Alta — Esperado"): **o ticker principal não tem edge na janela
OOS, nem antes dos custos.** ^BVSP não cruza PF = 1.0 em nenhuma das 20 células, e seu
retorno bruto a custo zero é negativo. A pergunta "esta estratégia sobrevive a slippage
0.3%?" tem resposta **"não — e a discussão de custos é secundária, porque não há edge a
proteger"**.

VALE3.SA é o único que passa o critério formal (PF > 1.0 até slip 0.5%), mas o faz com
**16 trades e +0.66% de retorno em 8 anos**: é robusto-a-custo por inatividade, não por
margem de segurança. PETR4.SA é uma não-amostra (3 trades).

A leitura honesta (Bloco I): **a tese de robustez cross-ticker da config Sprint-13 não se
sustenta out-of-sample.** O que sobrevivia in-sample não reaparece nos últimos 30%. Custo
de transação não é o que quebra o sistema aqui — ele já está quebrado a custo zero em 2 de
3 tickers; os custos apenas confirmam e aprofundam.

### Componente do PnL absorvido por custos

Diagnóstico bruto vs. líquido no baseline (coluna `cost_absorbed_pp` em `breakeven_summary.csv`):

| Ticker | Retorno bruto (custo 0) | Retorno baseline (slip/comm 0.1%) | Absorvido por custos (pp) |
|---|---|---|---|
| ^BVSP | −0.71% | −2.35% | 1.64 pp |
| VALE3.SA | +0.85% | +0.66% | 0.18 pp |
| PETR4.SA | −0.76% | −0.81% | 0.04 pp |

Os custos absolutos em pp são pequenos **porque o sistema mal opera** nesta janela (baixa
atividade, baixo capital empregado). Não confunda "custo absorvido pequeno" com "robusto":
em ^BVSP os custos transformam −0.71% em −2.35%, mais que **triplicando** a perda. O sinal
de fragilidade não é o tamanho do custo — é a **ausência de edge bruto**.

### Implicação para sizing

O sweep foi rodado com capital de R$ 100k e risco 1%/trade — sizes pequenos. O modelo de
custo aqui é **linear e não captura impacto de mercado** para ordens grandes. Como 2 de 3
tickers já não têm edge nem nesse regime otimista de custo, **não há base para recomendar
qualquer tier de capital** sobre a config Sprint-13 nesta janela. A discussão de "PF por
tier de capital" fica prejudicada pela ausência de edge a montante.

---

## Impacto no RELATORIO_TECNICO.md

O Critério de Aceitação §4 da spec exige: *"Se ^BVSP (ticker principal) não passa no teste
de 0.3%, esse fato aparece em letras grandes no TL;DR e gera atualização no
`RELATORIO_TECNICO.md`."*

**Via híbrida (lição do Sprint-18), aprovada pelo Jeferson — cross-refs factuais mínimos
aplicados; nenhuma tabela alterada; reescrita profunda deferida ao Marco:**

- [x] ✅ aplicado — Seção 5.7.1 (Motor event-driven): nota sobre o custo fixo ser otimista + `commission_pct` opt-in + cross-ref a este finding.
- [x] ✅ aplicado — Seção 7 (Resultados): blockquote `⚠️` (espelhando o do S18) com a janela OOS explícita, o contraste com a 7.2 e a ressalva "não é refutação direta".
- [x] ✅ aplicado — Seção 8.1 (Pontos de atenção quants): item de custos estendido com os números S19 e a distinção de janela.
- [x] ✅ aplicado — Seção 8.2 (Sugestões TI): item 6 "modelo de custo dinâmico / impacto de mercado".

**Correção mínima aplicada** (cross-refs factuais); **reescrita profunda do posicionamento de
robustez deferida ao Marco do Bloco I** (pós-Sprint-22), quando o conjunto de findings
(18–22) permitir reescrever a narrativa de uma vez, com base completa. **As tabelas 7.1/7.2
permanecem intactas como registro histórico.**

### Reconciliação de janela (por que 0.69 ≠ contradição com PF 2.119/2.77 da tabela 7.2)

O PF baixo do S19 e o PF alto do relatório **não medem a mesma coisa** — antes de inserir
qualquer cross-ref, reconciliamos a discrepância (evidência abaixo):

| Eixo | Sprint 19 (este finding) | Relatório (tabelas 7.1/7.2) |
|---|---|---|
| **Janela OOS** | ~8 anos: **2018-07-04 → 2026-05-29** (últimos 30% do histórico completo 2000-2026, 1963 barras) | ~7 meses: últimos 30% de um download de **~730 dias** (`expected_return_analysis.py:149-150`), terminando na data de geração do relatório |
| **Modelo de custo** | comissão **percentual** (`commission_pct`), R$ absoluto **zerado** | `commission_per_trade=R$0.001` (absoluto, ínfimo) + slip 0.1% |
| **Meta-labeler** | **não ativado** (`SPRINT13_PARAMS` não inclui `use_meta_labeler`) | treinado em IS e aplicado no OOS **se** `use_meta_labeler` (caminho `_run_oos`) |
| **PF ^BVSP** | 0.82 baseline · 0.69 @ slip 0.3% · **0.92 a custo zero** (<1.0) | 2.119 (7.1) / 2.77 (7.2) |

Conclusão: o S19 é um teste **mais longo e mais exigente** (8 anos vs ~7 meses), com custo
percentual e sem meta-labeler. A ausência de edge do ^BVSP **nessa janela** é um achado
honesto do Bloco I, mas **não refuta diretamente** os números do relatório, que vêm de
janela/metodologia distintas. O número exato de custo-zero (PF 0.9178 > PF 0.9023 do canto
mais barato do grid) também **confirma a propriedade** do teste 7 do CP2 ("custo zero é o
maior PF do grid") no ^BVSP real.

> **Nota para o Marco do Bloco I**: a própria janela de **~7 meses** do relatório original é
> uma **limitação metodológica** a revisitar — *qual* janela OOS é a honesta para afirmar
> robustez? Uma janela trailing curta pode superestimar edge. Decisão deferida ao Marco,
> com S18–S22 completos.

---

## Decisões tomadas

1. **Custos default em backtester**: **manter** (não alterar o default de produção neste
   sprint). O sweep usa `commission_pct` opt-in (default 0.0, não-quebrante); a decisão de
   subir o custo-modelo de produção fica para o hardening (Bloco II), informada por este finding.
2. **Relatórios de sessão (Sprint 31)**: sempre exibir os custos usados + linha "PF a slip
   0.3%" como pessimista — reforçado por este finding.
3. **Avisos automáticos**: se simulação usar slip < 0.1%, banner "modelo otimista de custos".
4. **Capital máximo recomendado por ticker**: **não recomendar** sobre a config Sprint-13
   nesta janela (sem edge OOS em 2/3 tickers).

---

## Limitações deste finding

- **Custos modelados são lineares e simétricos** (long e short pagam o mesmo slippage).
  Realidade: shorts em ações brasileiras têm custo extra (aluguel de papel).
- **Impacto de mercado não-linear** não é modelado; para ordens grandes em ativos pouco
  líquidos, o slippage real pode ser 2–3× o linear.
- **Amostra pequena** em VALE3.SA (16 trades) e **degenerada** em PETR4.SA (3 trades): os
  PFs desses dois carregam pouca informação estatística.
- **Variação intra-dia** (leilão de abertura/fechamento vs. meio do dia) é agregada.
- **Comparabilidade com o RELATORIO_TECNICO.md**: limitada pela disclosure 1 (comissão
  absoluta zerada) — não interprete os PFs deste sweep como continuação direta dos números
  do relatório original.

---

## Próximos passos

- [ ] **Marco do Bloco I (pós-S22)**: reescrita do posicionamento de robustez do
  `RELATORIO_TECNICO.md` à luz deste finding + S20/S21/S22.
- [ ] Sprint 20 (decomposição fatorial): usar configs que **passem** no teste de robustez —
  o que, nesta janela, **exclui ^BVSP/Sprint-13**. Reavaliar a escolha de "system returns".
- [ ] Sprint 21 (walk-forward honesto): confirmar se a ausência de edge OOS do ^BVSP é
  estável entre folds (este finding é um único split 70/30).
- [ ] Sprint 22 (bears expandido): incluir sensibilidade de custo simplificada.
