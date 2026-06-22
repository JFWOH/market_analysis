# Finding Sprint 22 — Bears Não-Canônicos: Validação Expandida

**Status**: 🟢 preenchido (execução real, dados yfinance, 2026-06-16)
**Data**: 2026-06-16
**Autor**: Jeferson Wohanka
**Sprint relacionado**: `sprints/sprint_22_bears_extras.md` · Plano: `docs/sprint_plans/sprint_22_plan.md`
**Tag pós-finding**: `v0.22.0`

---

## TL;DR

> ## ⚠️ A CATEGORIA-TESTE CENTRAL FALHA POR COMPLETO: `mean_reverting_brutal` = 0/3 APROVADOS ⚠️
>
> **Os três bears mean-reverting brutais — Euro 2011 (^STOXX50E), Brasil 2011-12 (^BVSP),
> Volmageddon 2018 (^GSPC) — têm Sharpe OOS NEGATIVO (−1.44 / −0.27 / −0.89) e nenhum passa.
> É exatamente o regime que tipicamente quebra trend-following, e o filtro de regime
> ADX+Hurst não protege: o sistema entra e apanha na oscilação. Em 14 cenários-núcleo
> (forex à parte), apenas 5 são "aprovados" (35,7%).**

**Mas o achado é mais incômodo que isso:** mesmo os **crashes canônicos** (os "validados" do
S16/S18) majoritariamente **REPROVAM** quando julgados sobre o **capital em risco** (MDD-CAR,
S18) e não sobre o equity total: GFC 2008 (^BVSP MDD-CAR 19,5%; ^GSPC 21,7%), COVID 2020
(22,8%), bear 2022 (17,5%) — todos `reprovado` (MDD-CAR > 15%), apesar de Sharpe às vezes
positivo. **Só `br_bear_2015` passa entre os 5 controles.**

**A nuance honesta que sobra a favor do sistema:** o **alpha vs Buy&Hold é positivo em 13 dos
15 cenários** (B&H despencou; o sistema, fora do mercado ~75% do tempo, preservou mais).
O sistema é **protetor RELATIVO** a B&H — mas "menos pior que B&H" não é "seguro": no eixo
absoluto de risco-ajustado e capital-em-risco, ele não se sustenta como "downside protection
insurance". E **quase todos os IC95% de Sharpe cruzam zero** — nenhum cenário tem Sharpe
significativamente positivo.

**Surpresa contraintuitiva:** a categoria **regional** (Argentina 2001, Rússia 2014, Turquia
2018, Ásia 1997) é a única **4/4 aprovada** — o sistema preservou capital melhor nas crises
emergentes do que nos crashes famosos.

**Resultado consolidado** (config **base auditada Sprint-13**, métricas na janela de eval):

| Categoria | Aprovados | Reprovados | Inconclusivos | Indisponíveis |
|---|---|---|---|---|
| Crash linear (6) | 1 | 4 | 1 | 0 |
| Regional (4) | 4 | 0 | 0 | 0 |
| **Mean-reverting brutal (3)** | **0** | **3** | **0** | **0** |
| Lost decade (1) | 0 | 1 | 0 | 0 |
| **Núcleo (14)** | **5 (35,7%)** | **8** | **1** | **0** |
| Forex (1, à parte) | — | (1) | — | 0 |

**Veredito: FRÁGIL na categoria mean-reverting brutal (calcanhar confirmado) e não-validável
como proteção absoluta de capital nos crashes; protetor relativo a B&H. Alimenta o
`MARCO_BLOCO_I.md` na direção do Cenário C (<50% aprovados).**

Fecha o Bloco I: S18 (MDD-CAR real ~17-23%) → S19 (sem edge a custo realista) → S20 (sem alpha,
β≈0) → S21 (OOS honesto negativo) → **S22 (falha na categoria-teste; crashes canônicos reprovam
sob a régua de capital-em-risco; nenhuma desculpa de dados — 15/15 reais).**

---

## Metodologia

- **Lista completa**: `scenarios/bears_v2.yaml` — 15 cenários, 5 categorias (decisão C: forex à parte).
- **Config**: **base auditada Sprint-13** (`SPRINT13_PARAMS`, registry `sprint_13_reference`).
  *"Validada" aqui = a base que passou pela auditoria do Bloco I, **não** "a que foi aprovada"*
  (o S21 mostrou que nenhuma config tem edge OOS). Decisão A do plano.
- **Métricas, TODAS na janela de eval `[start, end]`** (decisão item 1):
  - **Sharpe**: retornos diários da janela, anualizados √252. **IC95% bootstrap (N=1000,
    `default_rng(42)`)** dos MESMOS retornos diários, anualizado → o ponto fica dentro da banda
    (coerência); `sharpe_ci_point == sharpe`.
  - **return_pct / alpha**: variação de equity na janela; alpha = retorno_estratégia(eval) −
    retorno_B&H(eval) — **ambas as pernas no eval** (corrige descasamento herdado).
  - **MDD-equity + MDD-CAR + time-in-market**: `metrics.compute_drawdown_dual` nas curvas
    recortadas à janela (convenção S18; reuso direto do protótipo `rerun_bear_validation_dual_mdd`).
  - **num_trades / win_rate / profit_factor**: trades por **data de saída** na janela
    (descritivos — **não** entram em `classify_status`).
  - **Custos**: comissão 0,1% + slippage **0,1% (baseline)** e **0,3% (estressado, S19)**.
- **Status**: `aprovado` (Sharpe > 0 **e** MDD-CAR < 10%) · `reprovado` (Sharpe < 0 **ou**
  MDD-CAR > 15%) · `inconclusivo` (resto, ex.: Sharpe > 0 mas MDD-CAR 10-15%).
- **Gate S18**: aborta/marca `data_unavailable` se `yfinance` devolver sintético. **Nenhum
  ticker abortado** (15/15 reais).

### Nota metodológica — inversão da premissa pessimista (registrar com destaque)

A spec §5 e o template do finding foram escritos **esperando falha por dados ausentes**
(^MERV/IMOEX.ME/^HSI dados como "Alta prob." de indisponíveis). A sondagem (CP1 e re-sondagem
CP3) achou **15/15 com dados reais**. Isso **inverte a premissa e FORTALECE o finding**: onde o
sistema falha, falhou **com dados reais, sem desculpa de lacuna**. O caminho `data_unavailable`
ficou **testado (robustez) mas vazio**. O teste real do S22 não é "há dados?" — é **onde o
SISTEMA falha**, e ele falha na categoria mean-reverting brutal e no eixo de capital-em-risco.

---

## Resultados por categoria

Sharpe = anualizado da janela (IC95% bootstrap entre parênteses). MDD em % positivo.

### Crash linear (6 — sendo 5 controles do S16/S18 + `china_2015` novo)

| Cenário | Ticker | Sharpe (IC95%) | MDD-eq% | MDD-CAR% | TiM% | Alpha pp | Status |
|---|---|---|---|---|---|---|---|
| GFC 2008 | ^BVSP | +0.22 (−1.69, +2.07) | 0.44 | **19.51** | 25.3 | +27.65 | reprovado |
| GFC 2008 | ^GSPC | −0.25 (−2.10, +1.69) | 0.95 | **21.75** | 26.1 | +32.86 | reprovado |
| COVID 2020 | ^BVSP | −0.72 (−3.94, +2.06) | 0.97 | **22.80** | 31.2 | +18.91 | reprovado |
| 2022 bear | ^IXIC | −1.30 (−3.14, +0.59) | 1.49 | **17.50** | 21.5 | +33.04 | reprovado |
| 2015 BR bear | ^BVSP | +0.78 (−1.19, +2.69) | 0.37 | 4.19 | 29.1 | +17.37 | **aprovado** |
| China 2015 | 000001.SS | +0.61 (−1.78, +2.68) | 0.41 | 13.23 | 38.1 | +45.58 | inconclusivo |

**1 aprovado / 4 reprovado / 1 inconclusivo.** Os 4 reprovados famosos caem pela régua de
**MDD-CAR > 15%** (exatamente o que o S18 expôs: o "drawdown sub-1%" era do equity total; sobre
capital empregado é ~17-23%). `china_2015` fica inconclusivo (Sharpe +0.61 mas MDD-CAR 13,2% na
faixa 10-15%).

### Regional (4 — novos)

| Cenário | Ticker | Sharpe (IC95%) | MDD-eq% | MDD-CAR% | TiM% | Alpha pp | Status |
|---|---|---|---|---|---|---|---|
| Argentina 2001 | ^MERV | +1.51 (−0.11, +3.27) | 0.52 | 7.32 | 21.5 | +17.84 | **aprovado** |
| Rússia 2014 | IMOEX.ME | +0.21 (−1.76, +2.09) | 0.97 | 5.68 | 23.2 | −11.47 | **aprovado** |
| Turquia 2018 | XU100.IS | +0.10 (−2.30, +2.28) | 0.75 | 7.70 | 25.1 | +0.55 | **aprovado** |
| Ásia 1997 | ^HSI | +1.08 (−0.50, +2.58) | 0.41 | 6.87 | 19.7 | +34.51 | **aprovado** |

**4/4 aprovado** — a única categoria limpa. MDD-CAR baixo (5-8%) e Sharpe pontual positivo nas
quatro. **Ressalva forte:** os IC ainda cruzam (ou tocam) zero — só Argentina (−0.11) e Ásia
(−0.50) chegam perto de significância. Rússia tem alpha **negativo** (−11,5pp): o sistema ficou
de fora da recuperação do rublo/IMOEX — "prêmio em bull" pagando o sinistro.

### Mean-reverting brutal (3 — a categoria-teste central)

| Cenário | Ticker | Sharpe (IC95%) | MDD-eq% | MDD-CAR% | TiM% | Alpha pp | Status |
|---|---|---|---|---|---|---|---|
| Euro sovereign 2011 | ^STOXX50E | **−1.44** (−2.83, +0.12) | 1.48 | 7.61 | 16.6 | +11.22 | **reprovado** |
| BR mini-bear 2011 | ^BVSP | **−0.27** (−2.16, +1.44) | 1.04 | 4.58 | 22.6 | +21.28 | **reprovado** |
| Volmageddon 2018 | ^GSPC | **−0.89** (−6.05, +2.15) | 0.55 | 4.55 | 36.1 | +3.56 | **reprovado** |

**0/3 — FALHA TOTAL.** MDD-CAR é até baixo (4-8%), mas o **Sharpe é negativo nos três**: o
sistema **opera** (12-22 trades) e **perde** na oscilação em banda. É a confirmação empírica da
hipótese da spec: trend-following com filtro de regime ADX/Hurst não distingue "tendência" de
"ruído direcional" nesses regimes e apanha. Volmageddon tem o IC mais largo (−6.05, +2.15) —
janela curtíssima (72 barras).

### Lost decade (1)

| Cenário | Ticker | Sharpe (IC95%) | MDD-eq% | MDD-CAR% | TiM% | Alpha pp | Status |
|---|---|---|---|---|---|---|---|
| Japão 1995-2003 | ^N225 | −0.32 (−0.95, +0.30) | 2.77 | 13.80 | 26.2 | +43.64 | reprovado |

9 anos, 140 trades, Sharpe −0.32. Fica no mercado 26% do tempo (não "ficou de fora" como a tese
otimista esperava) e sangra devagar — alpha +43,6pp só porque o Nikkei caiu muito mais no período.

### Forex (1 — sanity-check separado, decisão C)

| Cenário | Ticker | Trades | Sharpe (IC95%) | MDD-CAR% | Alpha pp | Status (à parte) |
|---|---|---|---|---|---|---|
| BRL 2020 H2 | BRL=X | **3** | −0.57 (−2.87, +2.39) | 2.53 | +2.19 | reprovado |

**Confirmação COM DADOS de limitação já reconhecida** (RELATORIO: `macro_direction_lock` falha
em forex; S14 reportou 0 trades): com esta config/janela o sistema gera **apenas 3 trades** em 6
meses de USD/BRL — efetivamente **não opera** a classe. **Não conta** no placar de aprovado/
reprovado; é registro factual da inadequação, mais útil mostrada que citada.

---

## Forest plots (regeneráveis; `findings/sprint_22_data/plots/`, não versionados)

- `forest_sharpe.png` — Sharpe anualizado + IC95% por cenário, agrupado por categoria, linha em 0.
  **Leitura central: quase todos os IC cruzam zero** → significância estatística ausente na maioria.
- `forest_mdd_car.png` — MDD-CAR por cenário, com linhas de referência em 10% e 15%.
- `forest_alpha.png` — Alpha vs B&H (pp); positivo em 13/15.
- `scatter_sharpe_tim.png` — Sharpe × time-in-market por categoria.
- `category_medians.png` — mediana de Sharpe por categoria (regional > 0; MRB e lost_decade < 0).
- Evidência versionada: `findings/sprint_22_data/bears_complete.csv`.

---

## Cenários onde o sistema FALHOU (diagnóstico honesto)

**Mean-reverting brutal (0/3) — falha estrutural, não de parâmetro.** Euro 2011 / BR 2011-12 /
Volmageddon 2018: o filtro de regime deixa entrar em pseudo-tendências que revertem; cada entrada
vira stop. Não é ajuste de `adx_threshold`/`hurst_threshold` que resolve (o S21 mostrou que
re-otimizar não acha config estável) — é limitação do paradigma trend-following no regime
oscilatório. **Recuperável? Não por re-tuning; exige hipótese nova** (ex.: detector de regime
mean-reverting explícito), fora do escopo do Bloco I.

**Crashes canônicos (4/6) — falha de régua, não de comportamento novo.** GFC/COVID/2022 reprovam
porque o MDD-CAR (S18) excede 15% — o capital, quando empregado, arrisca de verdade. O sistema se
comporta como sempre; o que mudou é medi-lo honestamente (capital-em-risco, não equity diluído por
caixa ocioso). Continua **melhor que B&H** (alpha +18 a +33pp), mas não é "imune".

**Lost decade (Japão) — sangria lenta.** Reprovado por Sharpe negativo; fica no mercado tempo
demais para um regime sem tendência sustentada.

---

## Significância estatística (ressalva que atravessa tudo)

Dos 15 cenários, **nenhum tem IC95% de Sharpe inteiramente acima de zero**. Os melhores
(Argentina −0.11; Ásia −0.50) apenas tangenciam. Ou seja: mesmo os 5 "aprovados" têm Sharpe
**não distinguível de zero** a 95% — janelas anuais de bear têm poucas observações efetivas e
alta variância. **Os "aprovados" devem ser lidos como "não-reprovados", não como "edge provado".**
Coerente com S19/S20/S21.

---

## Cenários com `data_unavailable`

**Nenhum.** 15/15 com dados reais (`source=yfinance`) na execução de 2026-06-16. O caminho de
robustez (`data_unavailable`) está implementado e testado (E4 #5), mas **não foi acionado**. Ver
nota de inversão da premissa na Metodologia.

---

## Qualidade dos dados antigos (disclosure)

15/15 disponíveis ≠ 15/15 sem ressalva. Conferência de gaps (maior intervalo entre barras) e
warmup (~90 barras antes de `start`) na re-sondagem CP3:

- **Warmup OK em todos**: `warmup_pre` ≥ 117 barras em todos os 15 (incl. Ásia 1997 = 122; Japão
  1994 = 123) — indicadores aquecem sem comer a janela de eval.
- **Gaps maiores, mas reais**: `argentina_2001` (gap máx **13 dias**) e `china_2015` (**10 dias**)
  têm fechamentos prolongados — consistentes com **eventos reais** (corralito/feriados argentinos
  2001-02; circuit-breakers/feriado lunar na China jan-2016), **não** artefatos de yfinance. Demais
  cenários: gap máx 3-7 dias (fins de semana/feriados normais).
- **Janela mais fina**: `vol_spike_2018_feb` = 72 barras → IC de Sharpe o mais largo (−6.05, +2.15);
  ler o ponto com cautela.

Não invalida nenhum cenário; registrado para honestidade sobre períodos antigos/emergentes.

---

## Implicações estratégicas

- **Quando NÃO recomendar**: mercados/regimes **mean-reverting brutais** (oscilação severa em
  banda) — falha confirmada 3/3. E como **proteção absoluta de capital** em crashes — o MDD-CAR
  chega a ~20%+.
- **Onde se sustenta (com ressalva de significância)**: preservação **relativa** a B&H em crashes
  lineares e crises regionais — alpha positivo, MDD-CAR menor que o tombo do B&H. É "seguro de
  sinistro com franquia alta", não "imunidade".
- **Disclosure de produto (Sprint 31)**: a UI deve dizer "validado em N cenários; favorável em
  crises regionais e parte dos crashes lineares; **misto/negativo em mean-reverting e como
  proteção absoluta**; não opera forex".

---

## Atualização do RELATORIO_TECNICO.md (§7) — VIA HÍBRIDA, diff a aprovar ANTES

Disciplina S18-S21: **NÃO** fazer hard-replace do "7/7 cenários com alpha positivo". Em vez disso,
adicionar subseção **"Validação expandida cross-categoria (Sprint 22)"** com a tabela ampla + nota
de metodologia (janela de eval; `return_pct`/`num_trades` agora diferem de qualquer figura
full-run anterior) + cross-ref a este finding; números originais intactos como registro histórico;
reescrita profunda do posicionamento deferida ao `MARCO_BLOCO_I.md`.

- [ ] §7: subseção "Validação expandida cross-categoria" + tabela por categoria + cross-ref.
- [ ] §7.3 (Limitações): registrar falha em mean-reverting brutal e o reprovado-por-MDD-CAR dos crashes.

**(Checkboxes marcados quando o diff for mostrado, aprovado e aplicado — pendente de aprovação.)**

---

## Input para o `MARCO_BLOCO_I.md` (pós-S22)

Dimensão 1 (Preservação) e Dimensão 3 (Robustez): **5/14 cenários-núcleo aprovados = 35,7%**.
Limiares do template: ≥80% → Cenário A; 50-80% → B; **<50% → Cenário C**. Este finding aponta
para **Cenário C** (a decisão estrutural é do Marco, não deste finding). Reforça a pergunta
aberta do meta-labeler (S20) e a regra do S21: qualquer reabilitação exige hipótese nova, não
re-tuning.

---

## Decisões tomadas

1. **Lista oficial de cenários**: `scenarios/bears_v2.yaml` (schema validado; adições futuras seguem-no).
2. **Métricas na janela de eval** (item 1): Sharpe anualizado + IC bootstrap coerente; alpha 2-pernas-eval.
3. **Forex à parte** (decisão C): sanity-check, fora do placar.
4. **Disclosure de fonte de dados**: validações regionais antigas usam yfinance (cobertura/gaps
   reais documentados acima).
5. **`scripts/regression_bears.py` em CI** (Sprint 26): re-rodar ao mudar código de estratégia.

---

## Limitações deste finding

- **Sobrevivência narrativa persiste parcialmente**: ainda são cenários escolhidos. Walk-forward
  em janelas aleatórias do histórico (complementar) fica fora de escopo.
- **Sample por categoria modesto** (1-6 cenários) e **IC de Sharpe largos** (janelas anuais) → os
  pontos por cenário são ruidosos; conclusões são por categoria/direção, não por célula.
- **Custos regionais modelados como B3** (0,1%/0,3%) — otimista para Turquia/Argentina (spread maior).
- **`classify_status` é um corte** (Sharpe sinal + MDD-CAR 10/15%); a leitura honesta é a tabela +
  os IC, não só o rótulo.

---

## Próximos passos

- [ ] Mostrar o diff do `RELATORIO_TECNICO §7` e aplicar **após aprovação** (via híbrida).
- [ ] `MARCO_BLOCO_I.md` (pós-S22) com este finding como input principal das Dimensões 1 e 3.
- [ ] `scripts/regression_bears.py` no pipeline CI (Sprint 26).
