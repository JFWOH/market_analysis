# Finding Sprint 20 — Decomposição Fatorial do Alpha

**Status**: 🟢 preenchido (execução real, dados yfinance)
**Data**: 2026-06-02
**Autor**: Jeferson Wohanka
**Sprint relacionado**: `sprints/sprint_20_decomposicao.md`
**Tag pós-finding**: `v0.20.0`

---

## TL;DR

> ## ⚠️ NÃO HÁ ALPHA A DECOMPOR — O SISTEMA COMPLETO É QUASE-FLAT E LIGEIRAMENTE NEGATIVO EM ^BVSP ⚠️
>
> **Rodado continuamente sobre ^BVSP (2000–2026, 6543 barras, split IS/OOS 70/30), o
> sistema Sprint-13 fica FLAT em ~72% das barras e tem retorno total NEGATIVO em ambos
> os segmentos (IS −2.73% em 18,5 anos; OOS −0.21% em ~8 anos). Sua exposição líquida a
> qualquer fator — mercado, momentum 12-1, e o próprio Sistema Mínimo — é estatisticamente
> ZERO (β≈0, R²<0.003 em todos os 6 ajustes). O alpha é negativo e NÃO-significativo em
> todos os modelos e segmentos (p de 0.28 a 0.90). Não existe alpha positivo para atribuir
> a fatores; a pergunta "quanto é replicável?" é vazia porque não há retorno a explicar.**

Sharpe bruto anualizado do sistema: **IS = −0.21 · OOS = −0.04** (ambos negativos).

**Pergunta crucial (Modelo 3 — a regressão dura):** a complexidade (ensemble + macro-lock +
partial-exit + chandelier) agrega valor mensurável sobre o filtro de regime puro (Hurst+ADX)?

> **NÃO.** O alpha residual do Modelo 3 é −0.140% (IS, p=0.40) e −0.031% (OOS, p=0.90) — não
> significativo. Pior que o "Cenário 2" antecipado (β_min≈1, complexidade decorativa): aqui
> **β_min≈0 e corr(sistema, mínimo)≈0** — o sistema completo nem sequer *reproduz* a exposição
> do regime puro. A sofisticação não adiciona alpha e não captura o prêmio de regime que o
> filtro mínimo captura. (Ressalva de sizing na §Interpretação — a comparação de retorno
> nominal mínimo×completo é apples-to-oranges.)

---

## Metodologia

Três regressões OLS sequenciais com erros-padrão **Newey-West/HAC** (`maxlags = int(4·(n/100)^(2/9))`),
cada uma adicionando um fator, ajustadas **separadamente em IS (primeiros 70%) e OOS (últimos 30%)**:

### Modelo 1 — CAPM Local
```
R_system = α + β_mkt · R_market + ε
```

### Modelo 2 — CAPM + Momentum 12-1
```
R_system = α + β_mkt · R_market + β_mom · MOM_12_1 + ε
```
MOM_12_1 = `market_prices.pct_change(231).shift(21)` (retorno de t-252 a t-21 do ^BVSP).

### Modelo 3 — vs Sistema Mínimo (a regressão DURA)
```
R_system = α + β · R_minimal + ε
```
R_minimal = long(1) se `Hurst[i-1] > 0.55 AND ADX[i-1] > 25`, senão flat(0), × retorno diário do
mercado. **Reusa `TechnicalIndicators.compute_all`** (mesmas features do sistema completo, NÃO
reimplementa) com `shift(1)` anti-lookahead (CLAUDE.md §2.2).

**Construção de `R_system`:** o sistema completo (`CombinedStrategy` + `Backtester`, `SPRINT13_PARAMS`,
comissão R$0.001/trade + slippage 0.1%) roda **continuamente** sobre todo o histórico; `R_system` é
o `pct_change` da curva de equity. O fluxo de retornos é então **particionado** em IS/OOS — o sistema
não é re-inicializado no corte. Detalhes em `scripts/factor_decomposition.py` (núcleo: `fit_capm_local`,
`fit_capm_plus_momentum`, `fit_vs_minimal_system`, `build_minimal_system_returns`; execução: `run_decomposition`).

### Disclosures obrigatórias (LEIA antes de interpretar os números)

1. **Diluição por barras flat — esta é a disclosure mais importante.** O sistema fica **flat em
   ~72% das barras** (IS 73.0%, OOS 71.4%) e, quando posicionado, é dimensionado a ~1% de risco. Logo
   `R_system` é dominado por zeros e tem variância minúscula (residual_std ≈ 0.00045). Consequências:
   (a) o **β** medido é uma exposição **líquida-de-tempo-no-mercado**, não condicional a estar
   posicionado — daí β≈0 contra todos os fatores; (b) o **α** (intercepto) é essencialmente o
   **retorno diário médio anualizado** do equity, daí a magnitude minúscula (|α| < 0.21%/ano). A
   regressão responde "o equity tem drift positivo não-explicado pelo fator?" — e a resposta é
   "não, é levemente negativo". Não confundir β≈0 com "market-neutral por construção sofisticada":
   é market-quase-ausente.

2. **Fatores calculados no histórico completo, alinhados ao segmento.** Momentum 12-1 e o Sistema
   Mínimo são computados sobre **toda** a série (são públicos e backward-looking) e depois restritos
   às datas de IS/OOS — não há "reset" do fator num corte arbitrário. O momentum no início do OOS usa
   preços do IS (legítimo: momentum é informação passada de mercado, não do sistema).

3. **Escopo do "sistema completo": SEM meta-labeler nem Fibonacci** (`SPRINT13_PARAMS` não os ativa),
   idêntico ao escopo do S19. Logo o Modelo 3 mede **ensemble + macro-lock + partial-exit + chandelier**
   vs. regime puro — **não** mede a contribuição do meta-labeler+Fibonacci (ver Pergunta aberta ao Marco).
   Custos modelados (slippage/comissão 0.1%) são **otimistas** (CLAUDE.md §6.6).

4. **Inferência assintótica sob não-normalidade.** HAC corrige autocorrelação e heterocedasticidade
   dos resíduos, mas retornos financeiros têm caudas pesadas; os p-values são assintóticos. Os Q-Q plots
   anexados mostram desvio de normalidade nas caudas (esperado). Dado que **nenhum** p-value chega perto
   de 0.05 (o menor é 0.10, do β_momentum), a conclusão de não-significância é robusta a esse caveat.

---

## Resultados

### Tabela consolidada (fonte: `findings/sprint_20_data/decomposition_summary.csv`)

| Modelo | Seg | n_obs | Alpha anual | β principal | R² | Alpha p-value | Significativo? |
|---|---|---|---|---|---|---|---|
| 1 — CAPM | IS | 4579 | −0.141% | −0.0007 | 0.0008 | 0.401 | ✗ |
| 1 — CAPM | OOS | 1963 | −0.042% | +0.0013 | 0.0017 | 0.863 | ✗ |
| 2 — + Momentum | IS | 4328 | −0.203% | −0.0003 | 0.0007 | 0.278 | ✗ |
| 2 — + Momentum | OOS | 1963 | −0.203% | +0.0013 | 0.0023 | 0.492 | ✗ |
| 3 — vs Mínimo | IS | 4579 | −0.140% | −0.0011 | 0.0009 | 0.405 | ✗ |
| 3 — vs Mínimo | OOS | 1963 | −0.031% | +0.0016 | 0.0017 | 0.898 | ✗ |

Janelas: IS = 2000-01-04 → 2018-07-04; OOS = 2018-07-05 → 2026-06-01. Split em 2018-07-05 (70% das 6543 barras).
6 JSONs em `findings/sprint_20_data/model{1,2,3}_*_bvsp_{is,oos}.json`; 18 PNGs (scatter/residual/Q-Q × 6, gitignored).

### Modelo 1 — CAPM Local

β_mkt ≈ 0 (−0.0007 IS / +0.0013 OOS), R² ≈ 0.001–0.002. O sistema **não carrega exposição
direcional líquida** ao ^BVSP — mas, pela disclosure 1, porque opera pouco, não por desenho
market-neutral. Alpha negativo e não-significativo nos dois segmentos.

### Modelo 2 — CAPM + Momentum

β_momentum = 3.5e-05 (IS, p=0.101) / 6.4e-05 (OOS, p=0.257) — **não-significativo**. Adicionar
momentum **não** absorve alpha (não há alpha positivo a absorver); o α apenas oscila no ruído.

**VIF (mercado, momentum): 1.0 (IS) / 1.0009 (OOS).** Mercado e momentum 12-1 são praticamente
**ortogonais** nesta amostra — multicolinearidade nula. (Confirma empiricamente que o VIF reportado
é o dos **regressores mkt/mom**, não o da constante: o VIF da constante seria estruturalmente diferente.
VIF≈1 é exatamente o caso ortogonal esperado entre um fator lento 12-1 e o retorno diário ruidoso.)

### Modelo 3 — vs Sistema Mínimo (a regressão DURA)

α residual = −0.140% (IS, p=0.405) / −0.031% (OOS, p=0.898) — **não-significativo**. β_min ≈ 0
(−0.0011 / +0.0016); corr(sistema, mínimo) = **−0.03 (IS) / +0.04 (OOS)** ≈ zero.

**Resultado obtido: nem o "Cenário 1" (alpha residual significativo) nem o "Cenário 2" clássico
(β_min≈1, complexidade decorativa).** É um terceiro caso: **β_min≈0 e correlação nula** — o sistema
completo e o filtro de regime puro são quase-ortogonais. A sofisticação não reproduz a exposição do
regime mínimo nem adiciona retorno sobre ela.

---

## Interpretação (sem maquiagem)

### Não há alpha — e a decomposição confirma o S19

O resultado é coerente com o achado do S19 (`findings/sprint_19_cost_sensitivity.md`): a config
Sprint-13 **não tem edge em ^BVSP**, nem in-sample nem out-of-sample, antes mesmo de custos sérios.
A decomposição fatorial adiciona uma camada: não só não há edge, como **não há sequer exposição
líquida a fator** que pudéssemos chamar de "beta replicável". O sistema, como configurado (ultra-defensivo,
1% de risco, flat em ~72% das barras), **mal toca o mercado** — e o pouco que toca rende drift levemente
negativo, estatisticamente indistinguível de zero.

A pergunta de pitch do sprint ("o sistema vende alpha proprietário ou acessibilidade a um fator
conhecido?") tem resposta inesperada: **vende nenhum dos dois nesta janela** — não há retorno positivo
a atribuir. A discussão "quanto é commodity replicável" pressupõe um retorno a decompor que aqui não existe.

### A ressalva de sizing no Modelo 3 (honestidade obrigatória)

O Sistema Mínimo rendeu **+258.6% (IS) / +17.5% (OOS)** nominal (full-series 321%, em `minimal_total_return`),
contra ~flat do sistema completo. **Isso NÃO é prova de que "o mínimo bate o completo por edge".** O
Sistema Mínimo aqui é **notional e full-invested** quando em regime (sem position sizing, sem custos,
sem stop), enquanto o sistema completo dimensiona a ~1% de risco e paga custos. O grosso do gap de
magnitude é **alavancagem/sizing**, não edge. O que a regressão (Modelo 3) legitimamente afirma — e que
**não** depende de sizing — é: o equity do sistema completo não tem drift positivo significativo, nem
explicado nem residual ao mínimo (β_min≈0, α n.s.). A complexidade não compra retorno mensurável.

### Onde a complexidade *poderia* ser justificada

Como β_min≈0 (e não ≈1), o "Caminho A — simplificação radical para o Sistema Mínimo" do template **não**
se segue automaticamente: o mínimo e o completo não são a mesma coisa sub uma constante de escala; são
estratégias diferentes. O que se segue é mais básico: **a config Sprint-13 em ^BVSP não é defensável como
geradora de alpha** nesta janela. Antes de "simplificar para o mínimo", é preciso validar o próprio
Sistema Mínimo com sizing e custos reais (ele pode ser só beta-de-regime alavancado). Decisão deferida
ao Marco do Bloco I.

### Estabilidade IS vs OOS

Os coeficientes são consistentes entre IS e OOS no que importa: **α n.s. e β≈0 nos dois**. Não há
inversão de sinal economicamente relevante (os sinais de β oscilam em torno de zero, dentro do ruído).
A não-significância é **estável** — não é artefato de um único segmento.

---

## Pergunta aberta registrada para o Marco do Bloco I

> **O meta-labeler + Fibonacci, quando ativados, adicionam alpha?** Este finding mede explicitamente o
> escopo `SPRINT13_PARAMS` — **sem** meta-labeler e **sem** Fibonacci (disclosure 3). Logo o Modelo 3
> isola ensemble+macro-lock+partial+chandelier vs. regime puro, e conclui que **esse subconjunto** não
> adiciona alpha. A contribuição do meta-labeler+Fibonacci permanece **não medida** por este sprint. O
> RELATORIO_TECNICO (7.2) reporta PF mais alto *com* meta-labeler treinado em IS e aplicado em OOS — uma
> metodologia diferente. **Decisão deferida ao Marco:** desenhar um experimento que ative meta-labeler+Fibonacci
> e re-rode a decomposição, para fechar a Dimensão 2 (Alpha) com escopo completo.

---

## Impacto no RELATORIO_TECNICO.md

**Via híbrida (lição do S19), diff apresentado e aprovado pelo Jeferson ANTES de aplicar — 3 cross-refs
factuais mínimos aplicados; tabelas 7.1/7.2 intactas; reescrita profunda deferida ao Marco do Bloco I (pós-S22):**

- [x] ✅ aplicado — §5.3 (Ensemble): nota de que o conjunto ensemble+macro-lock+partial+chandelier não
  exibe alpha significativo sobre o regime puro (Modelo 3, α n.s. em IS e OOS) + cross-ref.
- [x] ✅ aplicado — §5.6 (Meta-Labeler): nota de que o S20 rodou `SPRINT13_PARAMS` **sem** meta-labeler;
  contribuição **não-medida** (≠ testada-e-falhou) → pergunta aberta ao Marco. **Desvio consciente do
  template**, que sugeria marcar o meta-labeler como "valor não demonstrado" — recusado por imprecisão.
- [x] ✅ aplicado — §8.1 (Quants): bullet de atenção (sem alpha significativo, β≈0 contra tudo) + fecha o
  loop da Sugestão 3 ("avaliar factor exposure Fama-French+momentum"), marcada como implementada pelo S20.

Critério de aceitação §4 da spec ("se Modelo 3 retornar alpha não-significativo, o RELATORIO_TECNICO é
atualizado para refletir esse fato"): **atendido** (correção mínima factual; reescrita profunda no Marco).

---

## Decisões tomadas

1. **Escopo do sistema = `SPRINT13_PARAMS`** (sem meta-labeler/Fibonacci), por continuidade com S19 e
   comparabilidade. A contribuição desses dois componentes vira pergunta explícita ao Marco.
2. **Split IS/OOS 70/30** sobre o fluxo de retornos do sistema rodado continuamente (não re-inicializado
   no corte) — coerente com a partição proporcional do S18/S19.
3. **JSONs + summary.csv versionados; PNGs gitignored** (regeneráveis via
   `python scripts/factor_decomposition.py --ticker ^BVSP`) — padrão S18/S19.
4. **Sistema Mínimo notional** (sem sizing/custo) é diagnóstico, não candidato a produto, até ser
   validado com sizing e custos reais.

---

## Limitações deste finding

- **Diluição por barras flat** (disclosure 1): a decomposição mede exposição líquida-de-tempo, não
  condicional-a-posição. Uma análise condicional (regredir só nas barras ativas) responderia outra
  pergunta e fica para trabalho futuro.
- **Sizing no Modelo 3**: a comparação de retorno nominal mínimo×completo é apples-to-oranges (§Interpretação).
- **Janela única por segmento**: um split 70/30, não walk-forward. A estabilidade temporal fina é tema do S21.
- **Fatores omitidos**: value, size, low-vol, quality não testados (fora de escopo do programa atual).
- **Custos otimistas** (0.1%): com 0.3% pessimista, o já-negativo ficaria mais negativo (não muda a conclusão).
- **Não-normalidade** (disclosure 4): p-values assintóticos; robusto aqui pela folga (menor p = 0.10).

---

## Próximos passos

- [ ] **Marco do Bloco I (pós-S22)**: experimento meta-labeler+Fibonacci ON + re-decomposição (Dimensão 2 / Alpha).
- [x] **Cross-refs do `RELATORIO_TECNICO.md`** (§5.3, §5.6, §8.1) aplicados via híbrida (aprovados pelo Jeferson).
- [ ] Sprint 21 (walk-forward honesto): confirmar estabilidade da não-significância entre folds.
- [ ] Validar o Sistema Mínimo **com sizing e custos** antes de considerá-lo baseline/preset (Sprint 27).
