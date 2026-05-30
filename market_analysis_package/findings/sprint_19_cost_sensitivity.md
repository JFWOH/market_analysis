# Finding Sprint 19 — Sensibilidade a Custos de Transação

**Status**: 🔴 template — preencher após execução do Sprint 19
**Data**: <YYYY-MM-DD>
**Autor**: Jeferson Wohanka
**Sprint relacionado**: `sprints/sprint_19_custos.md`
**Tag pós-finding**: `v0.19.0`

---

## TL;DR

Para cada ticker testado, três números importam:

- **PF baseline** (slip 0.1%, comm 0.1%)
- **PF estressado** (slip 0.3%)
- **Breakeven slip** — slippage no qual PF cai para 1.0

Exemplo de redação esperada:

> ^BVSP: PF baseline = X.X; cai para Y.Y em slip 0.3%; breakeven em Z.Z%.
> VALE3.SA: <preencher>
> PETR4.SA: <preencher>
> **Veredito**: <N> de 3 tickers passam no teste de robustez (PF > 1.0 com slip 0.3%).

---

## Metodologia

- **Grade de busca**: commission ∈ {0.05%, 0.1%, 0.2%, 0.5%} × slippage ∈ {0.05%, 0.1%, 0.2%, 0.3%, 0.5%}
- **Janela**: OOS (último 30% do histórico de cada ticker)
- **Config**: Sprint-13 reference (validada no Sprint 21 se já fechado; caso contrário, baseline original)
- **Breakeven**: busca binária com tolerância 1%
- **Métrica observada**: Profit Factor (primária), Sharpe (secundária)

Detalhes em `scripts/cost_sensitivity.py`.

---

## Resultados por ticker

### ^BVSP

| Slippage \ Commission | 0.05% | 0.1% | 0.2% | 0.5% |
|---|---|---|---|---|
| 0.05% | <preencher PF> | <preencher PF> | <preencher PF> | <preencher PF> |
| 0.10% | <preencher PF> | <preencher PF> | <preencher PF> | <preencher PF> |
| 0.20% | <preencher PF> | <preencher PF> | <preencher PF> | <preencher PF> |
| 0.30% | <preencher PF> | <preencher PF> | <preencher PF> | <preencher PF> |
| 0.50% | <preencher PF> | <preencher PF> | <preencher PF> | <preencher PF> |

- **PF baseline** (slip 0.1%, comm 0.1%): <preencher>
- **PF @ slip 0.3% comm 0.1%**: <preencher>
- **Breakeven slip** (comm fixa 0.1%): <preencher>%

Heatmap: `findings/sprint_19_data/heatmap_sprint_13_bvsp_pf.png`
Curva de degradação: `findings/sprint_19_data/degradation_bvsp.png`

### VALE3.SA

<repetir estrutura>

### PETR4.SA

<repetir estrutura>

---

## Tabela consolidada

| Ticker | PF baseline | PF @ slip 0.3% | Breakeven slip | Passa @ 0.3%? |
|---|---|---|---|---|
| ^BVSP | <preencher> | <preencher> | <preencher>% | <Sim/Não> |
| VALE3.SA | <preencher> | <preencher> | <preencher>% | <Sim/Não> |
| PETR4.SA | <preencher> | <preencher> | <preencher>% | <Sim/Não> |

Critério "Passa @ 0.3%": PF > 1.0 com slip 0.3% e comm 0.1%.

---

## Interpretação

### Diagnóstico de fragilidade

<preencher conforme resultados. Algumas possibilidades:>

**Se todos passam**: estratégia tem margem de segurança razoável. Custos modelados otimistas no relatório original (0.1%) são conservadores — ainda há edge mesmo a 0.3%.

**Se ^BVSP passa mas Sprint-13 cross-ticker falha em algum**: o sistema é sensível ao perfil de liquidez. Tickers menos líquidos (com slippage real maior) não sustentam a tese.

**Se ^BVSP não passa**: tese de robustez do sistema é mais frágil do que documentado. Em condições reais de spread (B3 em momentos de stress facilmente atinge 0.3%), PF cai abaixo de 1.0.

### Componente do PnL absorvido por custos

Para cada ticker, calcular:
- Total de PnL bruto (antes de custos): <preencher>
- Total de custos pagos: <preencher>
- Razão custos/PnL bruto: <preencher>%

Se essa razão for > 30%, sistema está "rodando para os custos" — pouco edge real.

### Implicação para sizing

Custos crescem linearmente com size de ordem (slippage piora com impacto de mercado). Sistema testado com sizes pequenos (R$ 100k de capital, ~R$ 10k por ordem). Para sizes maiores:

- R$ 1M por ordem em ações brasileiras médias: slip realista 0.3-0.5%
- R$ 5M+ por ordem: slip realista 0.5-1%, com impacto de mercado adicional

Recomendação: <preencher conforme resultado — incluir tabela de "PF estimado por tier de capital">

---

## Impacto no RELATORIO_TECNICO.md

Mudanças aplicadas no mesmo PR:

- [ ] Seção 5.7.1 (Motor event-driven): nota sobre limitações do modelo de custos fixos
- [ ] Seção 7 (Resultados): tabela cross-ticker adiciona coluna "PF @ slip 0.3%"
- [ ] Seção 8.1 (Pontos de atenção quants): item sobre custos atualizado com referência a este finding
- [ ] Seção 8.2 (Sugestões TI): adicionar item sobre integração futura com modelo de impacto de mercado dinâmico

---

## Decisões tomadas

1. **Custos default em backtester**: <manter 0.1% / aumentar para 0.15% / configurar baseado em ticker>
2. **Relatórios de sessão (Sprint 31)**: sempre exibir os custos usados na corrida + linha de "PF a slip 0.3%" como pessimista
3. **Avisos automáticos**: se simulação usar slip < 0.1%, banner amarelo "modelo otimista de custos"
4. **Capital máximo recomendado** por ticker: documentar com base no Average Daily Volume

---

## Limitações deste finding

- **Custos modelados são lineares e simétricos** (long e short pagam mesmo slippage). Realidade: shorts em ações brasileiras frequentemente têm custos adicionais (aluguel de papel).
- **Impacto de mercado não-linear** não é modelado. Para ordens grandes em ativos pouco líquidos, slippage real pode ser 2-3× o linear.
- **Variação intra-dia**: slippage no leilão de abertura/fechamento difere drasticamente do meio do dia. Modelo agrega.
- **Forex (BRL=X)**: não incluído neste sprint por ter quase nenhum trade na config Sprint-13 — análise comprometida por amostra pequena.

---

## Próximos passos

- [ ] Sprint 20 (decomposição fatorial) usa configurações que **passem** no teste de robustez deste sprint, como fonte de "system returns"
- [ ] Sprint 22 (bears expandido) inclui também análise de sensibilidade simplificada
- [ ] Considerar adicionar futuramente modelo de impacto de mercado dinâmico (não está no roadmap atual)
