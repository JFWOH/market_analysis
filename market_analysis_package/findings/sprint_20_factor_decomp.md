# Finding Sprint 20 — Decomposição Fatorial do Alpha

**Status**: 🔴 template — preencher após execução do Sprint 20
**Data**: <YYYY-MM-DD>
**Autor**: Jeferson Wohanka
**Sprint relacionado**: `sprints/sprint_20_decomposicao.md`
**Tag pós-finding**: `v0.20.0`

---

## TL;DR

Sharpe bruto do sistema: <preencher>
Após neutralizar mercado (CAPM): alpha de <preencher>% anual (significativo: <Sim/Não>)
Após adicionar momentum: alpha de <preencher>% anual (significativo: <Sim/Não>)
Após comparar com Sistema Mínimo (Hurst+ADX puro): alpha de <preencher>% anual (significativo: <Sim/Não>)

**Pergunta crucial**: a complexidade do sistema (ensemble + meta-labeler + Fibonacci + Chandelier) agrega valor mensurável sobre o Sistema Mínimo?

> **<Sim — alpha residual de X% é estatisticamente significativo (p < 0.05) sobre o Sistema Mínimo>**
> **<Não — Sistema Mínimo captura ~Y% do retorno; complexidade adicional não justifica>**

---

## Metodologia

Três regressões sequenciais, cada uma adicionando um fator:

### Modelo 1 — CAPM Local
```
R_system = α + β_mkt · R_market + ε
```
- R_market = retornos do ticker de referência (ex.: ^BVSP para sistema rodado em BR equities)
- R_system = retornos do sistema configurado para Sprint-13 reference

### Modelo 2 — CAPM + Momentum
```
R_system = α + β_mkt · R_market + β_mom · MOM_12_1 + ε
```
- MOM_12_1 = retorno de t-252 a t-21 do mercado de referência (proxy de fator momentum)

### Modelo 3 — vs Sistema Mínimo
```
R_system = α + β · R_minimal + ε
```
- R_minimal = retornos de "long em ^BVSP se Hurst[i-1] > 0.55 AND ADX[i-1] > 25, senão flat"
- Mesmos parâmetros de regime que o sistema completo usa
- Esta é a pergunta dura: o resto da estratégia adiciona algo?

Erros padrão calculados via Newey-West com `maxlags = int(4 * (n/100)**(2/9))` para corrigir auto-correlação residual.

Detalhes em `scripts/factor_decomposition.py`.

---

## Resultados

### Modelo 1 — CAPM Local (referência: ^BVSP)

| Parâmetro | Estimativa | Std Err (HAC) | t-stat | p-value |
|---|---|---|---|---|
| α (anualizado) | <preencher>% | <preencher> | <preencher> | <preencher> |
| β (mercado) | <preencher> | <preencher> | <preencher> | <preencher> |
| R² | <preencher> | | | |
| N observações | <preencher> | | | |

Alpha significativo (p < 0.05): <Sim/Não>

Scatter + linha de regressão: `findings/sprint_20_data/model1_capm_bvsp.png`
Residual plot: `findings/sprint_20_data/model1_residual.png`
Q-Q plot: `findings/sprint_20_data/model1_qq.png`

**Interpretação preliminar**: <O sistema tem beta próximo de zero? Se sim, é "market-neutral"; se moderado, carrega exposição direcional.>

### Modelo 2 — CAPM + Momentum

| Parâmetro | Estimativa | Std Err | t-stat | p-value |
|---|---|---|---|---|
| α (anualizado) | <preencher>% | <preencher> | <preencher> | <preencher> |
| β (mercado) | <preencher> | <preencher> | <preencher> | <preencher> |
| β (momentum) | <preencher> | <preencher> | <preencher> | <preencher> |
| R² | <preencher> | | | |
| ΔR² vs Modelo 1 | <preencher> | | | |

**Interpretação preliminar**: <O fator momentum absorveu parte do alpha do Modelo 1? Em quanto?>

VIF (Variance Inflation Factor) entre R_market e MOM_12_1: <preencher>

### Modelo 3 — vs Sistema Mínimo (a regressão DURA)

| Parâmetro | Estimativa | Std Err | t-stat | p-value |
|---|---|---|---|---|
| α (anualizado) | <preencher>% | <preencher> | <preencher> | <preencher> |
| β (sistema mínimo) | <preencher> | <preencher> | <preencher> | <preencher> |
| R² | <preencher> | | | |

**Cenário 1 — alpha residual significativo** (p < 0.05): o ensemble, meta-labeler, Fibonacci e Chandelier juntos adicionam X% anualizado sobre o filtro de regime puro. Vale o custo de complexidade.

**Cenário 2 — alpha residual NÃO significativo** (p > 0.05): Sistema Mínimo captura essencialmente todo o retorno do sistema. A complexidade adicional é decorativa — adiciona testes, parâmetros, código, mas não retorno mensurável.

**Resultado obtido**: <preencher qual cenário>

---

## Tabela consolidada

| Modelo | Alpha anual | Alpha sig.? | β principal | R² |
|---|---|---|---|---|
| 1 — CAPM | <preencher>% | <Sim/Não> | <β_mkt> | <preencher> |
| 2 — + Momentum | <preencher>% | <Sim/Não> | <β_mkt> | <preencher> |
| 3 — vs Mínimo | <preencher>% | <Sim/Não> | <β_min> | <preencher> |

---

## Interpretação

### O que o sistema "vende implicitamente"

Cada beta significativo é uma "exposição implícita" que o cliente do sistema está carregando:

- **β_mkt > 0.3**: cliente tem exposição direcional ao mercado. Pode ser obtido mais barato com ETF.
- **β_mom > 0**: cliente tem exposição a momentum factor. Replicável com fundos momentum.
- **β_min próximo de 1.0**: cliente está pagando pela versão complexa do que poderia obter com regras simples.

A fração do retorno "explicada" por fatores conhecidos é o quanto o sistema é commodity — replicável e barato.

### Onde a complexidade poderia ser justificada

Se Modelo 3 mostra alpha não-significativo, dois caminhos:

**Caminho A — Simplificação radical**:
Mover para Sistema Mínimo + gestão de risco (partial exit + breakeven + chandelier). Remover: meta-labeler, ensemble, Fibonacci. Resultado: menos código, menos parâmetros, menor overfitting, mesma performance esperada.

**Caminho B — Identificar contexto onde complexidade ajuda**:
Talvez o ensemble adiciona valor em **regimes específicos** que não aparecem na média. Sub-período onde sistema completo bate sistema mínimo materialmente.

Recomendação: <preencher>

### Sobre a estabilidade dos coeficientes

Re-rodar regressões em sub-períodos (anos individuais ou splits 60/40):

| Sub-período | α Modelo 3 | β Modelo 3 |
|---|---|---|
| 2015-2018 | <preencher> | <preencher> |
| 2019-2022 | <preencher> | <preencher> |
| 2023-2026 | <preencher> | <preencher> |

Coeficientes estáveis: <Sim/Não>. Instabilidade sugere que o "alpha" varia no tempo — talvez não seja persistente.

---

## Implicações estratégicas

### Para o posicionamento do produto

<preencher conforme resultado>

**Se alpha residual significativo e estável**: o sistema vende algo proprietário. Headline "sistema com alpha demonstrável sobre fatores conhecidos" é justificável.

**Se alpha residual marginal mas com β_min próximo de 1.0**: o sistema vende "filtro de regime + gestão de risco assimétrica". Replicável por quem entende as duas peças. O valor é na execução disciplinada, não no algoritmo.

**Se alpha residual não-significativo**: o sistema vende **complexidade**. Honestamente, não há diferenciação estatística sobre uma versão muito mais simples. Reposicionar para o que de fato funciona.

### Para o `RELATORIO_TECNICO.md`

- [ ] Seção 5.3 (Ensemble): adicionar nota sobre contribuição empírica dos componentes
- [ ] Seção 5.6 (Meta-Labeler): se Modelo 3 não-significativo, marcar meta-labeler como "valor não demonstrado"
- [ ] Seção 8.1 (Análise para quants): atualizar com decomposição fatorial
- [ ] Seção 10 (Conclusão): reformular se diagnóstico apontar para simplificação

### Para o `MARCO_BLOCO_I.md`

Este finding alimenta diretamente a Dimensão 2 (Alpha) do Marco:
- Alpha residual significativo → Cenário A possível
- Alpha residual marginal/instável → Cenário B
- Alpha residual não-significativo + degradação alta no Sprint 21 → Cenário C

---

## Decisões tomadas

1. **Sistema Mínimo é parte do produto**: se Modelo 3 mostrar β_min ~ 1.0, expor "Sistema Mínimo" como configuração disponível na UI (presets do Sprint 27)
2. **Documentação de transparência**: na UI, mostrar ao usuário "esta config tem β_X% explicado por fatores Y" — full disclosure
3. **Re-avaliação periódica**: re-rodar decomposição a cada 12 meses ou após mudanças significativas no sistema

---

## Limitações deste finding

- **N de observações**: estatísticas robustas exigem ≥ 500 obs. Em sub-períodos, n pode cair abaixo disso, comprometendo significância.
- **Não-normalidade dos retornos**: Q-Q plot pode mostrar caudas pesadas (esperado em finanças). Newey-West ajuda mas não resolve completamente. Considerar bootstrap de coeficientes para validação adicional.
- **Multicolinearidade**: market e momentum têm correlação positiva (momentum é derivado de market). VIF moderado é esperado e tolerável (< 5).
- **Fatores omitidos**: não testamos exposição a value, size, low-volatility, quality. Programa atual exclui isso explicitamente (ver `ROADMAP.md`). Programa futuro pode revisitar.
- **Período de regime único**: se janela inteira for bull market, sistema parece carregar momentum; em janela com bear, talvez carregue short-vol implícito. Ideal seria janela cobrindo múltiplos regimes — que é o caso aqui, mas vale lembrar.

---

## Próximos passos

- [ ] Sprint 21 (walk-forward honesto) usa configurações vencedoras desta análise como base
- [ ] Se Caminho A (simplificação) for indicado, considerar Sprint 21.5 "Sistema Mínimo validado" antes do Marco
- [ ] Sprint 31 (relatórios) inclui linha "fatores explicativos" no relatório de sessão
