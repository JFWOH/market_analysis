# Finding Sprint 18 — Drawdown em Base Dupla

**Status**: 🔴 template — preencher após execução do Sprint 18
**Data**: <YYYY-MM-DD>
**Autor**: Jeferson Wohanka
**Sprint relacionado**: `sprints/sprint_18_metricas.md`
**Tag pós-finding**: `v0.18.0`

---

## TL;DR

<1-2 frases. Se diferença entre as duas bases for > 5×, escrever em **letras maiúsculas**.>

Exemplo de redação esperada (se números forem dramáticos):

> **MDD reportado no RELATORIO_TECNICO.md (< 1%) reflete equity total, não capital em risco. Quando recalculado sobre capital empregado, a mediana cross-cenário sobe para X.X%, e o crash GFC 2008 sobe de 0.74% para Y.Y%.**

Exemplo se números forem modestos:

> Diferença entre MDD-equity e MDD-capital-at-risk é de fator 1.5-2×. O headline original sobrevive em magnitude mas a métrica correta para operador é a segunda, com mediana X.X%.

---

## Metodologia

- **MDD-equity** (base original do sistema): rolling peak da equity curve total (caixa + posições); drawdown = (curr - peak) / peak.
- **MDD-capital-at-risk** (novo): considera apenas barras com posição aberta; calcula equity sintética "por unidade de capital empregado" e tira MDD dessa curva.

Detalhes técnicos: docstring de `market_analysis.metrics.compute_drawdown_dual`.

Período avaliado: <preencher janelas dos 7 cenários originais>

---

## Tabela renovada (7 cenários × 2 bases)

| Crash | Período | Ticker | MDD-equity | MDD-CAR | Razão CAR/equity | Time-in-market |
|---|---|---|---|---|---|---|
| GFC 2008 ^BVSP | 2008-06 — 2009-06 | ^BVSP | 0.74% | <preencher>% | <preencher>× | <preencher>% |
| GFC 2008 ^GSPC | 2008-06 — 2009-06 | ^GSPC | 1.73% | <preencher>% | <preencher>× | <preencher>% |
| COVID 2020 ^BVSP | 2020-01 — 2020-06 | ^BVSP | 0.94% | <preencher>% | <preencher>× | <preencher>% |
| Bear 2022 ^IXIC | 2022-01 — 2022-12 | ^IXIC | 1.58% | <preencher>% | <preencher>× | <preencher>% |
| 2015 BR bear | 2015-01 — 2016-01 | ^BVSP | 1.73% | <preencher>% | <preencher>× | <preencher>% |
| GFC ^GSPC continuação | <preencher> | ^GSPC | <preencher>% | <preencher>% | <preencher>× | <preencher>% |
| <7º cenário> | <preencher> | <preencher> | <preencher>% | <preencher>% | <preencher>× | <preencher>% |
| **Mediana** | | | <preencher>% | **<preencher>%** | **<preencher>×** | <preencher>% |

CSV completo em `findings/sprint_18_data/bears_dual_mdd.csv`.
Gráfico em `findings/sprint_18_data/dual_mdd_chart.png`.

---

## Interpretação honesta

### Por que a diferença existe

O sistema permanece **fora do mercado em <preencher>%** do tempo nos cenários de crash (filtro de regime + macro_direction_lock bloqueando entradas). O caixa ocioso amortece movimento de equity total. Esse caixa é **real do ponto de vista do portfolio do cliente** (ele tem o dinheiro), mas é **fictício do ponto de vista do operador** (não está sendo arriscado pelo sistema).

A pergunta operacional correta:
> "Quando o sistema está com posição aberta, quanto ele perde no pior caso?"

Esta é a métrica MDD-capital-at-risk. É a que importa para:
- Determinar tamanho apropriado de capital alocado ao sistema (Kelly fraction)
- Comparar com outros sistemas (benchmark justo)
- Calcular Sharpe e Sortino sobre capital efetivamente arriscado

### O que muda no posicionamento

<preencher conforme o que os números mostrarem. Algumas possibilidades:>

**Se MDD-CAR é < 5% em todos os cenários**: o headline original sobrevive em substância — sistema **realmente** preserva capital quando opera. O ajuste é técnico (reportar a métrica correta) mas não estratégico.

**Se MDD-CAR é 5-15% em maioria dos cenários**: posicionamento de "extreme downside protection" precisa ser temperado. Sistema continua protetor relativo a B&H (que perdeu 30-60% nos mesmos crashes), mas não é "imune".

**Se MDD-CAR é > 15% em algum cenário**: posicionamento original é insustentável. Sistema é "menos pior que B&H em crashes" mas chamar de "downside protection insurance" seria enganoso.

---

## Impacto no RELATORIO_TECNICO.md

Mudanças aplicadas no mesmo PR deste finding:

- [ ] Seção 1.1 (Perfil estratégico validado): coluna "Max Drawdown" desdobrada em duas colunas
- [ ] Seção 1.2 (Validação contra crashes): tabela atualizada com nova coluna MDD-CAR
- [ ] Seção 7 (Resultados Empíricos): tabela cross-ticker atualizada
- [ ] Sumário Executivo: nova frase de honestidade sobre as duas bases
- [ ] Glossário (novo, se não existir): definição clara de MDD-equity vs MDD-CAR

---

## Decisões tomadas

1. **Métrica primária** em relatórios futuros: <MDD-equity | MDD-CAR | ambos sempre>
2. **Banner condicional** em relatórios de sessão (Sprint 31): se MDD-CAR exceder X%, banner amarelo
3. **Atualização do dashboard** (Sprint 29): exibir ambas as métricas lado a lado, com MDD-CAR em destaque
4. **Convenção de comunicação**: sempre que falar "MDD" em discussão sobre o sistema, especificar qual base

---

## Limitações deste finding

- **Definição de capital-at-risk em partial exit**: após fechar 50% da posição com breakeven movido, a posição residual tem **risco assimétrico** (stop em entry; lucro ilimitado). A métrica trata isso como capital em risco proporcional ao tamanho. Pode subestimar marginalmente.
- **Shorts**: lógica simétrica aos longs, mas margin requirements reais (que não são modelados) podem afetar capital empregado.
- **Posições simultâneas multi-ticker**: capital-at-risk é soma dos valores absolutos; não desconta correlação. Ver `risk_guard.max_correlated_exposure_pct` (Sprint 24) para mitigação operacional.

---

## Próximos passos

- [ ] Mover para Sprint 19 (sensibilidade a custos)
- [ ] No Sprint 25 (SQLite), a tabela `equity_snapshots` armazena ambos os MDDs por barra — ao calcular métricas de sessão, usar ambos
- [ ] No Sprint 31 (relatórios), template exibe ambas as métricas
