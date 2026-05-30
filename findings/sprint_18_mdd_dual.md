# Finding Sprint 18 — Drawdown em Base Dupla

**Status**: 🟢 preenchido com números reais (yfinance, 7 cenários)
**Data**: 2026-05-30
**Autor**: Jeferson Wohanka
**Plano do sprint**: `docs/sprint_plans/sprint_18_plan.md`
**Tag pós-finding**: `v0.18.0`

---

## TL;DR

> **O MAX DRAWDOWN REPORTADO COMO < 1% NOS CRASHES REFLETE O EQUITY TOTAL, NÃO O CAPITAL EM RISCO. RECALCULADO SOBRE O CAPITAL EFETIVAMENTE EMPREGADO, A MEDIANA CROSS-CENÁRIO SOBE PARA 17.50%, E O GFC 2008 ^BVSP SALTA DE 0.43% PARA 19.51% — UMA RAZÃO DE 45×. A MEDIANA DA RAZÃO CAR/EQUITY É 24×.** O headline de "drawdown sub-1%" é um artefato do caixa ocioso: o sistema fica fora do mercado ~76% do tempo nos crashes.

---

## Metodologia

- **MDD-equity** (base original do sistema): rolling peak da equity curve total (caixa + posições); drawdown = (curr − peak) / peak.
- **MDD-capital-at-risk** (novo): equity sintética "por unidade de capital empregado", construída multiplicativamente; só avança em barras com posição aberta. MDD dessa curva.

Convenção CAR (explícita, não silenciosa): a curva sintética só avança com posição aberta em **duas barras consecutivas**. O PnL da **barra de abertura** de cada trade **não entra** na CAR — semeia o nível e o recuo só é medido contra uma barra anterior já em mercado (simétrico ao tratamento de short). Pode subestimar marginalmente o MDD-CAR de trades muito curtos. Detalhes: docstring de `metrics.compute_drawdown_dual`.

Janela de MDD: calculada **apenas sobre o período de avaliação** (sem o pré-aquecimento de indicadores). `num_trades` e `sharpe` vêm da rodada completa (mesma convenção do `scripts/bear_market_validation.py` legado). Config: Sprint-13 ("ultra-defensiva"), custos 0.1% slippage + 0.1% comissão, cooldown 2 barras.

Período avaliado (7 cenários): GFC 2008 (2008-06→2009-06, ^BVSP e ^GSPC), COVID 2020 (2020-01→2020-06, ^BVSP e ^GSPC), bear 2022 (2022-01→2022-12, ^GSPC e ^IXIC), bear BR 2015 (2015-01→2016-01, ^BVSP).

---

## Tabela renovada (7 cenários × 2 bases)

| Crash | Período | Ticker | MDD-equity | MDD-CAR | Razão CAR/equity | Time-in-market |
|---|---|---|---|---|---|---|
| GFC 2008 ^BVSP | 2008-06 — 2009-06 | ^BVSP | 0.43% | 19.51% | 45.08× | 22.9% |
| GFC 2008 ^GSPC | 2008-06 — 2009-06 | ^GSPC | 0.90% | 21.75% | 24.23× | 28.3% |
| COVID 2020 ^BVSP | 2020-01 — 2020-06 | ^BVSP | 0.94% | 22.80% | 24.27× | 31.1% |
| COVID 2020 ^GSPC | 2020-01 — 2020-06 | ^GSPC | 0.30% | 8.58% | 28.76× | 20.2% |
| Bear 2022 ^GSPC | 2022-01 — 2022-12 | ^GSPC | 0.82% | 9.53% | 11.57× | 23.5% |
| Bear 2022 ^IXIC | 2022-01 — 2022-12 | ^IXIC | 1.43% | 17.50% | 12.24× | 21.5% |
| Bear BR 2015 | 2015-01 — 2016-01 | ^BVSP | 0.37% | 4.19% | 11.26× | 29.1% |
| **Mediana** | | | 0.82% | **17.50%** | **24.23×** | 23.5% |

CSV completo em `findings/sprint_18_data/bears_dual_mdd.csv`.
Gráfico em `findings/sprint_18_data/dual_mdd_chart.png` (regenerável; não versionado).

---

## Interpretação honesta

### Por que a diferença existe

O sistema permanece **fora do mercado em ~76% do tempo** (mediana) nos cenários de crash (filtro de regime + `macro_direction_lock` bloqueando entradas; time-in-market mediano de 23.5%). O caixa ocioso amortece o movimento do equity total. Esse caixa é **real do ponto de vista do portfolio do cliente** (ele tem o dinheiro), mas **fictício do ponto de vista do operador** (não está sendo arriscado pelo sistema).

A pergunta operacional correta:
> "Quando o sistema está com posição aberta, quanto ele perde no pior caso?"

Essa é a métrica MDD-capital-at-risk. É a que importa para: dimensionar o capital alocado (Kelly), comparar com outros sistemas (benchmark justo), e calcular Sharpe/Sortino sobre capital efetivamente arriscado.

### O que muda no posicionamento

Os números caem na faixa mais severa do template: **MDD-CAR > 15% em 4 dos 7 cenários** (19.51%, 21.75%, 22.80%, 17.50%). Conforme o critério pré-definido:

> **MDD-CAR > 15% em algum cenário**: o posicionamento original é insustentável. O sistema é "menos pior que B&H em crashes" (B&H perdeu 30–60% nos mesmos períodos) mas chamá-lo de "downside protection insurance" / "drawdown sub-1%" seria **enganoso**.

O sistema continua **protetor relativo** a B&H. O que cai é a narrativa de imunidade absoluta: quando opera, ele arrisca de verdade.

---

## Impacto no RELATORIO_TECNICO.md

**🔴 GATILHO ACIONADO** — o critério de aceitação 8 ("se CAR ≥ 5× equity em algum cenário") disparou com folga (mediana 24×, máximo 45×). A atualização do `RELATORIO_TECNICO.md` é **recomendada e necessária**, mas **NÃO foi aplicada neste checkpoint**: reescrever o headline do produto é mudança de narrativa que merece a decisão explícita do desenvolvedor (ver o RELATÓRIO DE CHECKPOINT). Pendências propostas (mesmo PR ou follow-up dedicado, à sua escolha):

- [ ] Seção 1.1 (Perfil estratégico validado): "Max Drawdown" desdobrado em duas colunas (equity / CAR)
- [ ] Seção 1.2 (Validação contra crashes): tabela com a nova coluna MDD-CAR
- [ ] Seção 7 (Resultados Empíricos): tabela cross-ticker atualizada
- [ ] Sumário Executivo: frase de honestidade sobre as duas bases
- [ ] Glossário: definição de MDD-equity vs MDD-CAR

---

## Decisões tomadas

1. **Métrica primária** em relatórios futuros: **ambos sempre** (equity para o cliente, CAR para o operador) — nunca MDD sozinho sem especificar a base.
2. **Janela de MDD** medida sobre o período de avaliação (sem warmup), para comparabilidade com o B&H eval-only do script legado.
3. **Convenção CAR** (barra de abertura fora; duas barras consecutivas) documentada no docstring e nesta metodologia — comportamento explícito, não silencioso.
4. **PNG não versionado** (`findings/sprint_18_data/*.png` no `.gitignore`); a evidência versionada é o CSV + esta tabela. O gráfico é regenerável via `python scripts/rerun_bear_validation_dual_mdd.py`.

---

## Limitações deste finding

- **Barra de abertura fora da CAR**: trades de 1 barra não contribuem para o MDD-CAR (regra das duas barras consecutivas). Subestima marginalmente em trades muito curtos.
- **Partial exit**: após fechar 50% com breakeven movido, a posição residual tem risco assimétrico; a métrica trata o capital em risco proporcional ao tamanho corrente (decisão 6.2 do plano).
- **Shorts**: lógica simétrica aos longs; margin requirements reais (não modelados) podem afetar o capital empregado.
- **Posições simultâneas multi-ticker**: cada cenário aqui é single-ticker; CAR não desconta correlação. Ver `risk_guard.max_correlated_exposure_pct` (Sprint 24).
- **Sharpe negativo na maioria dos cenários** é esperado (config defensiva em janelas de crash; o objetivo é preservar capital, não lucrar).

---

## Próximos passos

- [ ] Decisão do desenvolvedor sobre a atualização do `RELATORIO_TECNICO.md` (gatilho acionado).
- [ ] Sprint 19 (sensibilidade a custos): re-rodar com 0.3% slippage pessimista e observar o efeito nas duas bases.
- [ ] Sprint 25 (SQLite): `equity_snapshots` deve armazenar ambos os MDDs por barra.
- [ ] Sprint 31 (relatórios): template exibe ambas as métricas, CAR em destaque.
