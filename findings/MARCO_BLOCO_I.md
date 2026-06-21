# Marco do Bloco I — Decisão Estratégica de Continuidade

**Status**: 🟢 fechado — 5/5 sprints executados (dados reais). Um experimento deferido (meta-labeler+Fibonacci ON) permanece NÃO-MEDIDO e segue para o Bloco II; não altera o veredito (ver §2 Dim. 2 e §3).
**Última atualização**: 2026-06-21
**Responsável**: Jeferson Wohanka
**Sprints consolidados**: 18, 19, 20, 21, 22 (todos 🟢, dados reais yfinance)

---

## Definição dos cenários

- **Cenário A** — edge confirmado. A complexidade agrega valor mensurável e o
  sistema sobrevive à validação honesta. Prosseguir com produtização (Blocos II/III).
- **Cenário B** — edge parcial/condicional. Há um núcleo defensável, mas cercado de
  ressalvas; continuação exige reescopo antes de qualquer produtização.
- **Cenário C** — sem edge. As métricas históricas favoráveis são artefatos de
  metodologia. O sistema Sprint-13 não é candidato a capital real. Encerrar a linha
  de produtização e redirecionar o aparato de validação para uma tese nova.

A última linha deste documento define a continuidade do programa. Tudo acima a justifica.
**Honestidade é o ponto**: registrar A para não desperdiçar trabalho inverteria a razão
de ser do Bloco I.

---

## 1. Snapshot dos Achados

### Sprint 18 — Drawdown em base dupla
O MDD < 1% reportado nos crashes refletia o **equity total**, não o capital empregado.
Sobre o capital efetivamente em risco (CAR), a mediana cross-cenário sobe para **17,50%**;
o GFC 2008 ^BVSP salta de 0,43% para **19,51% (45×)**. Mediana da razão CAR/equity = **24×**.
O "sub-1%" era artefato de caixa ocioso: o sistema fica fora do mercado **~76%** do tempo
nos crashes. → `findings/sprint_18_mdd_dual.md`

### Sprint 19 — Sensibilidade a custos
| Ticker | PF baseline | PF @ slip 0,3% | Breakeven | Veredito |
|---|---:|---:|---|---|
| ^BVSP | 0,82 | 0,69 | N/A (sem edge nem a custo zero; bruto −0,71%) | ❌ |
| VALE3.SA | 1,43 | 1,34 | ≈ 0,88% | ✅ (só 16 trades, retorno ~nulo) |
| PETR4.SA | — | — | reprovado | ❌ |
**1 de 3 tickers** passa, e o único que passa o faz com retorno economicamente
desprezível. → `findings/sprint_19_cost_sensitivity.md`

### Sprint 20 — Decomposição fatorial
**Não há alpha a decompor.** Sobre ^BVSP (2000–2026, 6543 barras), o sistema fica flat
em **~72%** das barras e tem retorno total **negativo** em ambos os segmentos
(IS −2,73% em 18,5 anos; OOS −0,21% em ~8 anos). Sharpe bruto: **IS −0,21 · OOS −0,04**.
Exposição a qualquer fator é estatisticamente zero (β≈0, R²<0,003 em todos os 6 ajustes;
alpha não-significativo, p de 0,28 a 0,90). Modelo 3 (vs Sistema Mínimo Hurst+ADX):
alpha residual −0,140% (IS, p=0,40) e −0,031% (OOS, p=0,90); **β_min≈0 e corr≈0** — o
sistema completo nem reproduz a exposição do filtro de regime puro. A complexidade é
decorativa **e** não captura o prêmio de regime. → `findings/sprint_20_factor_decomp.md`

### Sprint 21 — Walk-forward honesto
Anchored, 14 folds, IS 504+ / OOS 252, embargo 20, seleção por DSR deflado, 2010→2026.
**Sharpe OOS honesto negativo nos três tickers: ^BVSP −0,21 · ^GSPC −0,41 · VALE3 −1,65.**
O método de params fixos nem produz IS positivo (^BVSP −0,09; ^GSPC −0,20; VALE3
inavaliável, 0 trades). A única forma de obter IS positivo é re-otimizar por janela
(+0,12 / +0,04) — e esse IS **colapsa** para OOS negativo, degradação >100% (cruza zero),
param_stability 0,25–0,46. As redes de sanidade (sinal estável → degradação ≈0; ruído →
alta) passam: o método distingue sinal de ruído, e o que a re-otimização encontra é
**ruído, não edge**. O "Sharpe 1,72" não sobrevive a nenhuma forma de walk-forward
honesto. → `findings/sprint_21_walkforward_honest.md`

### Sprint 22 — Bears não-canônicos (15 cenários reais)
| Categoria | Cenários | Aprovados | Sharpe (IC cruza 0) | Observação |
|---|---:|---:|---|---|
| Crash linear | 6 | 1 | ~0 | GFC/COVID/2022 reprovam por MDD-CAR ~17–23% |
| Regional | 4 | 4 | +0,2 a +1,5 | única categoria limpa |
| **Mean-reverting brutal** | 3 | **0** | **negativa** | Sharpe OOS −1,44 / −0,27 / −0,89 |
| Lost decade | 1 | 0 | −0,32 | Japão 1995–2003, sangria lenta |
| Forex (à parte) | 1 | — | — | BRL=X: 3 trades, não opera a classe |
**5/14 cenários-núcleo aprovados (35,7%)**, "aprovado" = "não-reprovado". Alpha vs B&H
positivo em 13/15 — "protetor relativo", não "imune". Quase todos os IC95% de Sharpe
cruzam zero: sem edge significativo. A falha mean-reverting é **estrutural** — o filtro
ADX/Hurst não impede entradas que revertem, e o S21 já provou que re-tuning não corrige.
→ `findings/sprint_22_bears_complete.md`

---

## 2. Síntese Cruzada

**Dimensão 1 — Headline (preservação de capital em crashes).**
Antes: "MDD < 1% em todas as crises". Depois: MDD-CAR mediano **17,5%**; reprovação dos
crashes canônicos sob capital-em-risco. Veredito: **comprometida** — o sistema é protetor
relativo (alpha vs B&H), não imune; e a proteção vinha majoritariamente de não estar
posicionado.

**Dimensão 2 — Alpha (o motor).**
Não existe retorno positivo a atribuir. Flat ~72%, negativo IS e OOS, β≈0 contra todos os
fatores, complexidade sem valor mensurável sobre o filtro mínimo. Veredito: **inexistente no escopo auditado** (`SPRINT13_PARAMS`, meta-labeler e Fibonacci OFF — idêntico a S19/S20/S21).

**Fio aberto, registrado (não omitido):** S20 e S21 deferiram explicitamente a este
Marco um experimento que ativa meta-labeler+Fibonacci e re-roda a decomposição. Ele
permanece **não-medido** — distinto de *testado-e-falhou* (S20 §5.6 recusou marcá-lo
como 'valor não demonstrado'). O Cenário C se sustenta mesmo assim por ônus da prova:
o primário não tem edge bruto nem a custo zero (S19), o PF/Sharpe superior do 7.2 vinha
de meta-labeler treinado-IS-aplicado-OOS que não sobrevive a walk-forward honesto (S21),
e o programa migra para uma tese validada do zero. Re-medir o sistema morto com escopo
completo tem baixo valor para a decisão de encerramento — mas o experimento é
**carregado ao Bloco II** como sonda: 'meta-labeling adiciona precisão a um primário
rule-based?', diretamente relevante para os setups Ogro.

**Dimensão 3 — Robustez fora-da-amostra (sobrevive à validação honesta?).**
Sharpe OOS negativo nos três tickers; categoria-teste central 0/3; qualquer IS positivo é
artefato de seleção. Veredito: **falha**.

As três dimensões convergem. Não há divergência entre métricas a reconciliar — o arco
S19 (sem edge a custo zero) → S20 (sem alpha) → S21 (IS é artefato) → S22 (falha
estrutural cross-categoria) é monotônico.

---

## 3. Decisão

O sistema Sprint-13 **não tem edge demonstrável** e não é candidato a capital real. As
métricas históricas favoráveis (Sharpe 1,72, PF 2,17, MDD <1%) foram, sem exceção,
artefatos de metodologia: caixa ocioso mascarando drawdown, janelas curtas mascarando o
colapso OOS, seleção fabricando Sharpe in-sample.

Consequências formais deste marco:
1. A linha de **produtização do Sprint-13 é encerrada**. O roadmap dos sprints 23–33
   (audit log, killswitch, SQLite, UI, replay, live, packaging) fica **suspenso sob
   Cenário C** — não se leva a produção um sistema sem edge.
2. O **aparato de validação** (walk-forward honesto, MDD-CAR, decomposição fatorial,
   sensibilidade a custo, stress test, os 8 gates, a estrutura de findings) é declarado
   **ativo herdável** e atravessa para a tese nova. É a contribuição duradoura do Bloco I.
3. Os números consolidados aqui passam a ser o **benchmark mínimo** que qualquer tese
   sucessora deve bater sob o mesmo crisol.
4. O experimento meta-labeler+Fibonacci ON, deferido por S20/S21, é transferido como
   item aberto ao Bloco II (sonda inicial), não como pendência de produtização do Sprint-13.

---

## 4. O que atravessa para o Bloco II

A falha mean-reverting estrutural (S22) e a ausência de prêmio de regime capturado (S20)
definem a hipótese sucessora: **operar exclusivamente a favor da tendência, com filtro
explícito de lateralidade** — precisamente o eixo do método Ogro (Tabajara + gravata
borboleta + entrada por toque/rejeição, nunca por cruzamento). Não é continuidade do
sistema antigo; é uma tese nova submetida ao mesmo juiz.

Reaproveita-se: camada de validação (íntegra), motor de backtest (esqueleto + métricas +
anualização granularidade-aware, com adaptador de fill intra-bar a construir),
indicadores primitivos (SMA/EMA/ATR/ADX/Hurst). Substitui-se: camada de dados
(yfinance/diário → M5 WIN/WDO com rollover). Novo: setups Ogro e o benchmark aleatório
(gate 4, ainda não implementado).

---

CENARIO_FINAL: C
