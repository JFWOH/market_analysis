# Sprint 20 — Decomposição Fatorial do Alpha

**Bloco**: I (Auditoria)
**Duração estimada**: 5-7 dias úteis
**Pré-requisito**: Sprint 19 fechado (`v0.19.0`)
**Status**: pending
**Tag ao fechar**: `v0.20.0`

---

## 1. Contexto

O sistema reporta Sharpe de 1.72 (mediana) e PF de 2.17 em condições favoráveis. A pergunta que ainda não foi respondida com rigor estatístico:

> **Quanto desse retorno é alpha genuíno, e quanto é exposição implícita a fatores conhecidos (replicáveis por ETFs baratos)?**

Trend-following com filtro de regime tende a carregar:
- **Beta de mercado** baixo (mas não-zero)
- **Momentum 12-1** alto (compra o que subiu)
- **Low-volatility** moderado (rejeita regimes voláteis)
- **Short-volatility implícito** (vende prêmio em alguns momentos)

Se o Sharpe de 1.72 é majoritariamente explicado por esses fatores, o "alpha" do sistema é principalmente *acessibilidade a um fator conhecido* — replicável e barato. Isso não anula o valor do sistema, mas **muda fundamentalmente o pitch**: "vendemos exposição a momentum + low-vol com gestão de risco assimétrica" é muito diferente de "vendemos alpha proprietário".

---

## 2. Objetivo

Regredir os retornos do sistema contra três modelos sucessivos, do mais simples ao mais sofisticado, e quantificar com p-value e R² quanto resta como alpha estatisticamente significativo.

---

## 3. Entregáveis

### E1 — Módulo `scripts/factor_decomposition.py`

Três análises sequenciais.

#### Modelo 1 — CAPM local
```python
def fit_capm_local(
    system_returns: pd.Series,
    market_returns: pd.Series,
    risk_free_rate: float = 0.0,  # SELIC pode ser proxy se quiser
) -> dict:
    """
    R_system = alpha + beta * R_market + epsilon
    
    Returns
    -------
    dict com:
        - alpha_annualized: float (em %)
        - beta: float
        - r_squared: float
        - alpha_pvalue: float
        - beta_pvalue: float
        - residual_std: float
        - n_obs: int
        - significant_alpha: bool (p < 0.05)
    """
```

#### Modelo 2 — Momentum simples
Adiciona fator momentum 12-1 do mercado de referência:

```python
def fit_capm_plus_momentum(
    system_returns: pd.Series,
    market_returns: pd.Series,
    market_prices: pd.Series,  # para calcular momentum
    momentum_lookback: int = 252,
    momentum_skip: int = 21,
) -> dict:
    """
    R_system = alpha + beta_mkt * R_market + beta_mom * MOM + epsilon
    
    MOM = retorno do mercado de t-252 a t-21 (momentum 12-1 mensal aproximado).
    """
```

Mesmo schema de retorno do Modelo 1, com adição de `beta_momentum` e `beta_momentum_pvalue`.

#### Modelo 3 — Sistema mínimo (a regressão crucial)
Versão minimalista da própria estratégia como fator:

```python
def fit_vs_minimal_system(
    system_returns: pd.Series,
    market_data: pd.DataFrame,  # OHLCV
    minimal_strategy_params: dict = None,
) -> dict:
    """
    Constrói "Sistema Mínimo" = long se (Hurst[i-1] > 0.55 AND ADX[i-1] > 25) else flat.
    
    Calcula returns_minimal sobre mesma série.
    
    Regride: R_system = alpha + beta * R_minimal + epsilon
    
    Esta é a pergunta DURA:
    "O ensemble + meta-labeler + Fibonacci adiciona algo sobre o 
    filtro de regime puro?"
    """
```

Se `alpha` aqui não é estatisticamente significativo, toda a sofisticação do sistema (ensemble, meta-labeler, Fibonacci, Chandelier) está adicionando complexidade sem adicionar retorno comprovado.

### E2 — Visualizações

Para cada modelo:

1. **Scatter** `system_returns vs market_returns` com linha de regressão e bandas de confiança 95%.
2. **Residual plot** (resíduos vs valores ajustados) para diagnóstico de não-linearidade.
3. **Q-Q plot** dos resíduos para checar normalidade.

Salvar em `findings/sprint_20_data/<model>_<ticker>.png`.

### E3 — Testes `tests/unit/test_factor_decomposition.py`

Mínimo 10 casos:

1. **Identidade**: `system_returns == market_returns` → `alpha ≈ 0`, `beta ≈ 1`, `R² ≈ 1`.
2. **Sistema puro alpha**: `system_returns = alpha_known + noise` → recupera `alpha_known` dentro de margem.
3. **Sistema com beta puro**: `system_returns = beta_known * market_returns` → recupera `beta_known`.
4. **Sistema independente**: returns aleatórios → `R² ≈ 0`, `alpha` provavelmente não significativo.
5. **Estatisticamente significativo**: 1000 obs com alpha 10% anualizado → p < 0.01.
6. **Estatisticamente não significativo**: 50 obs com alpha 2% → p > 0.05.
7. **Momentum factor**: sistema construído para seguir momentum → `beta_momentum` significativo positivo.
8. **Determinismo**: rodar duas vezes → resultado idêntico.
9. **Edge case**: N obs < 30 → ValueError ou warning explícito.
10. **Minimal system construction**: parâmetros fixos produzem resultado idêntico em duas execuções.

### E4 — Execução

Rodar os 3 modelos para `^BVSP` com config Sprint-13 reference, sobre toda a série disponível:

- Output em `findings/sprint_20_data/`:
  - `model1_capm_bvsp.json`
  - `model2_momentum_bvsp.json`
  - `model3_minimal_bvsp.json`
  - 9 PNGs (3 modelos × 3 visualizações)
  - `decomposition_summary.csv` consolidando os três

### E5 — Relatório `findings/sprint_20_factor_decomp.md`

Estrutura obrigatória:

```markdown
# Finding Sprint 20 — Decomposição Fatorial

## TL;DR
[Em 1-2 frases: "Sharpe bruto = X. Após neutralizar mercado, sobra Y. 
Após adicionar momentum, sobra Z. Após comparar com sistema mínimo, sobra W."]

## Tabela consolidada
| Modelo | Alpha anual | Beta mkt | R² | Alpha p-value | Significativo? |
|---|---|---|---|---|---|
| 1 — CAPM | ... | ... | ... | ... | ✓/✗ |
| 2 — + Momentum | ... | ... | ... | ... | ✓/✗ |
| 3 — vs Mínimo | ... | ... | ... | ... | ✓/✗ |

## Visualizações
[Embedded scatters dos 3 modelos]

## Interpretação
[Sem maquiagem: quanto do retorno é genuíno? O que é replicável?]

## Implicações estratégicas
[Se o Modelo 3 mostrar alpha não-significativo, escrever explicitamente:
"O Sistema Mínimo (Hurst + ADX) captura X% do retorno do sistema completo. 
A complexidade adicional precisa de justificativa ou simplificação."]

## Decisões tomadas
[Atualizar RELATORIO_TECNICO.md seção 8.1 se necessário]
```

---

## 4. Critério de Aceitação

- [ ] Suite completa passa
- [ ] `factor_decomposition.py` tem cobertura ≥ 85%
- [ ] 3 JSONs de resultados existem
- [ ] 9 PNGs de visualização existem
- [ ] `decomposition_summary.csv` consolida os três modelos
- [ ] Relatório responde explicitamente: "Alpha do sistema sobrevive ao Modelo 3?"
- [ ] Se Modelo 3 retornar alpha não-significativo (p > 0.05), `RELATORIO_TECNICO.md` é atualizado para refletir esse fato

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Pouco dado para significância estatística | Média | Reportar n_obs e poder estatístico; exigir mínimo 500 obs |
| Não-normalidade dos resíduos | Alta | Usar Newey-West para erros padrão robustos; Q-Q plot revela |
| Modelo 3 mostra que sistema mínimo é "quase igual" ao completo | Média-Alta | Esperado e desejado. Aceitar honestamente |
| Multicolinearidade entre momentum e market | Média | Reportar VIF (Variance Inflation Factor) |

---

## 6. Notas para o Claude Code

- **Biblioteca**: usar `statsmodels.api.OLS` (não `sklearn.linear_model.LinearRegression`, que não dá p-values direto).
- **Annualização**: retornos diários × 252 (assumindo dados diários). Se intraday, ajustar conforme.
- **Newey-West**: usar `cov_type='HAC'` com `maxlags` igual a `int(4 * (n/100)**(2/9))`.
- **Momentum 12-1**: retorno de t-252 a t-21. Implementação:
  ```python
  mom = market_prices.pct_change(231).shift(21)
  ```
- **Sistema Mínimo** precisa usar **as mesmas features** que o sistema completo (mesmos parâmetros de Hurst, ADX). Caso contrário, comparação não é justa.
- **Returns alignment**: garantir que `system_returns` e `market_returns` tenham mesmo index. Drop NaN antes de regredir.
- Reportar `n_obs` em todos os resultados.

---

## 7. Comandos de validação

```bash
pytest tests/unit/test_factor_decomposition.py -v
python scripts/factor_decomposition.py --ticker ^BVSP --config sprint_13_reference
ls findings/sprint_20_data/
cat findings/sprint_20_factor_decomp.md | head -50
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — 3 modelos | 1.5-2 dias |
| E2 — visualizações | 0.5 dia |
| E3 — testes (10 casos) | 1-1.5 dias |
| E4 — execução | 0.5 dia |
| E5 — relatório (interpretação cuidadosa) | 1.5-2 dias |
| Buffer | 0.5 dia |
| **Total** | **5-7 dias** |
