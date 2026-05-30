# Sprint 19 — Sensibilidade a Custos de Transação

**Bloco**: I (Auditoria)
**Duração estimada**: 3-4 dias úteis
**Pré-requisito**: Sprint 18 fechado (`v0.18.0`)
**Status**: pending
**Tag ao fechar**: `v0.19.0`

---

## 1. Contexto

O `RELATORIO_TECNICO.md` modela custos como percentual fixo: 0.1% de slippage e ~R$ 0.001 de comissão. Esses valores são otimistas:

- **Spread bid-ask dinâmico** em ativos brasileiros pode dobrar em momentos de stress.
- **Impacto de mercado** cresce não-linearmente com o size da ordem. Para ordens > R$ 1M em ações pouco líquidas, custo real pode ser 3-5× o modelado.
- **Forex (BRL=X)** tem spread tipicamente 0.05-0.15% em condições normais, mas 0.5%+ em volatilidade.

Sharpe e Profit Factor reportados podem colapsar quando custos sobem. Antes de qualquer afirmação sobre robustez, é preciso saber **quão sensível** a estratégia é a esses parâmetros.

---

## 2. Objetivo

Transformar custos de "parâmetro fixo" em "superfície de sensibilidade" que acompanha todo relatório de performance. Saber, para cada configuração e cada ticker, o **nível de slippage que faz a estratégia perder dinheiro**.

---

## 3. Entregáveis

### E1 — Módulo `scripts/cost_sensitivity.py`

Função principal:

```python
def cost_sensitivity_sweep(
    strategy_config: dict,
    data: pd.DataFrame,
    comm_grid: list[float] = None,
    slip_grid: list[float] = None,
    initial_capital: float = 100_000,
    risk_per_trade: float = 0.01,
) -> pd.DataFrame:
    """
    Roda backtest sobre cada combinação (comm × slip) na grade.
    
    Defaults:
        comm_grid = [0.0005, 0.001, 0.002, 0.005]   # 0.05% a 0.5%
        slip_grid = [0.0005, 0.001, 0.002, 0.003, 0.005]
    
    Returns
    -------
    DataFrame com colunas:
        comm, slip, pf, sharpe, win_rate, num_trades,
        total_return_pct, mdd_total_pct, mdd_capital_at_risk_pct
    
    Shape: (len(comm_grid) * len(slip_grid), 9)
    """
```

Implementação:
- Cada combinação dispara um backtest independente.
- Paralelizar via `multiprocessing.Pool` se `n_jobs > 1` (opcional).
- Resultado em memória; gravação opcional em CSV.

### E2 — Função de breakeven `find_breakeven_slippage`

```python
def find_breakeven_slippage(
    strategy_config: dict,
    data: pd.DataFrame,
    commission: float = 0.001,
    slip_search_range: tuple = (0.0001, 0.01),
    metric: str = "profit_factor",
    target_value: float = 1.0,
    tolerance: float = 0.01,
) -> dict:
    """
    Busca binária pelo nível de slippage onde `metric` atinge `target_value`.
    
    Returns
    -------
    dict com:
        - breakeven_slippage: float (ou NaN se não atinge nem com slip mínimo)
        - metric_at_breakeven: float
        - num_iterations: int
        - converged: bool
    """
```

Critério: se mesmo com `slip_search_range[0]` a métrica já está abaixo do target, retorna NaN (estratégia não tem edge nem com custos mínimos).

### E3 — Visualizações

Para cada (config, ticker), gerar:

1. **Heatmap PF**: eixo X = slippage, eixo Y = comissão, cor = profit factor. Cell labels com valor. Salvar como `findings/sprint_19_data/heatmap_<config>_<ticker>_pf.png`.
2. **Heatmap Sharpe**: idem para Sharpe.
3. **Curva de degradação**: slippage no X, métricas (PF, Sharpe, Win Rate) no Y, com linha horizontal em `y=1.0` (breakeven). Marca vertical no breakeven slippage.

Usar matplotlib (sem dependências adicionais).

### E4 — Testes `tests/unit/test_cost_sensitivity.py`

Mínimo 8 casos:

1. **Estratégia perdedora**: `find_breakeven_slippage` retorna NaN.
2. **Estratégia muito robusta** (sintética com edge enorme): `breakeven_slippage > 0.005`.
3. **Monotonia**: PF decresce monotonicamente com aumento de slippage (mantendo comissão fixa).
4. **Idempotência**: rodar duas vezes com mesma seed → mesmo resultado.
5. **Grid sweep retorna DataFrame com shape correto**.
6. **Defaults respeitados** quando `comm_grid` / `slip_grid` são None.
7. **Custo zero é caso degenerado**: PF com slip=0 e comm=0 deve ser o maior do grid.
8. **Convergência**: `find_breakeven_slippage` converge em < 30 iterações na busca binária.

### E5 — Execução para 3 tickers principais

Rodar `cost_sensitivity_sweep` para:
- `^BVSP` (Sprint-13 reference config)
- `VALE3.SA` (Sprint-13 reference config)
- `PETR4.SA` (Sprint-13 reference config)

Em janela OOS (2024-2026 ou último 30% do histórico).

Saídas em `findings/sprint_19_data/`:
- `sweep_bvsp.csv`, `sweep_vale3.csv`, `sweep_petr4.csv`
- 9 PNGs (3 tickers × 3 visualizações)
- `breakeven_summary.csv` com 1 linha por ticker

### E6 — Relatório `findings/sprint_19_cost_sensitivity.md`

Estrutura obrigatória:

```markdown
# Finding Sprint 19 — Sensibilidade a Custos

## TL;DR
[Para cada ticker: "PF = X.X no baseline; cai para Y.Y com slip 0.3%. 
Breakeven em Z.Z%."]

## Heatmaps por ticker
[Embedded: 3 heatmaps de PF]

## Tabela de breakeven slippage
| Ticker | PF baseline | PF @ slip 0.3% | Breakeven slip |
|---|---|---|---|
| ^BVSP | ... | ... | ... |

## Interpretação
[Quão fragilizada está a tese de robustez? 
Quais tickers passam no "teste de slip 0.3%" (PF > 1.0)?]

## Recomendações
[Se algum ticker não passa, registrar como limitação conhecida 
no RELATORIO_TECNICO.md]
```

---

## 4. Critério de Aceitação

- [ ] Suite completa passa
- [ ] `cost_sensitivity.py` tem cobertura ≥ 90%
- [ ] 3 CSVs de sweep existem
- [ ] 9 PNGs de visualização existem e são legíveis
- [ ] `breakeven_summary.csv` tem 3 linhas
- [ ] `findings/sprint_19_cost_sensitivity.md` responde explicitamente "esta estratégia sobrevive a slippage 0.3%?" para cada ticker
- [ ] Se ^BVSP (ticker principal) **não** passa no teste de 0.3%, esse fato aparece em letras grandes no TL;DR e gera atualização no `RELATORIO_TECNICO.md`

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Sweep demora muito (75 combinações × 3 tickers × período longo) | Média | Paralelização opcional; default sequencial é < 30 min |
| Findings revelam fragilidade do produto | Alta | Esperado. Bloco I existe para isso |
| Visualizações ilegíveis com muitos cells | Baixa | Validar com humano antes de fechar |

---

## 6. Notas para o Claude Code

- Backtester precisa aceitar `commission` e `slippage` como parâmetros — verificar se já aceita. Se não, ajustar (pequena modificação não-quebrante).
- `multiprocessing` em Windows: usar `if __name__ == "__main__":` guard no script.
- Heatmaps: usar `matplotlib.pyplot.imshow` com `cmap='RdYlGn'` (vermelho = ruim, verde = bom).
- Para Sharpe heatmap, fixar escala de cor em [-2, 3] para comparabilidade visual entre tickers.
- Salvar PNGs com `dpi=150` (qualidade boa, arquivo razoável).
- Adicionar nota no docstring: "Custos modelados aqui não capturam impacto de mercado para sizes muito grandes."

---

## 7. Comandos de validação

```bash
pytest tests/unit/test_cost_sensitivity.py -v
python scripts/cost_sensitivity.py --ticker ^BVSP --config sprint_13_reference
python scripts/cost_sensitivity.py --all-tickers   # roda os 3
ls findings/sprint_19_data/
cat findings/sprint_19_cost_sensitivity.md | head -30
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — sweep function | 0.5 dia |
| E2 — breakeven binary search | 0.5 dia |
| E3 — visualizações | 0.5 dia |
| E4 — testes | 0.5-1 dia |
| E5 — execução para 3 tickers | 0.5 dia (compute time) |
| E6 — relatório | 0.5-1 dia |
| **Total** | **3-4 dias** |
