# Sprint 21 — Walk-Forward com Re-otimização Honesta

**Bloco**: I (Auditoria)
**Duração estimada**: 7-10 dias úteis
**Pré-requisito**: Sprint 20 fechado (`v0.20.0`)
**Status**: pending
**Tag ao fechar**: `v0.21.0`

---

## 1. Contexto

O walk-forward implementado em `walk_forward_real.py` e nos scripts `walk_forward_sprintN.py` é descrito como validação OOS, mas a leitura atenta do código (e do RELATORIO_TECNICO.md seção 5.7) sugere que os **parâmetros são fixos** — selecionados uma vez sobre o histórico inteiro, depois aplicados em janelas rolantes.

Isso é um problema metodológico sério:

- O que está sendo medido é apenas **fora da amostra de treino do meta-labeler**.
- A **seleção de hiperparâmetros** (que é a fonte real de overfitting estatístico) aconteceu olhando para o histórico inteiro.
- O "OOS Sharpe = 1.72" reportado é, portanto, contaminado por data dredging na seleção de parâmetros.

Walk-forward honesto **re-otimiza dentro de cada janela IS** e aplica esses parâmetros — específicos daquela janela — na janela OOS subsequente. A degradação IS→OOS observada é a estimativa não-enviesada de overfitting.

---

## 2. Objetivo

Reescrever o walk-forward para re-otimização real em cada janela IS, medir a degradação esperada, e decidir se a config atual continua válida ou precisa ser substituída por algo mais conservador.

---

## 3. Entregáveis

### E1 — Módulo `walkforward_honest.py`

```python
from dataclasses import dataclass
from typing import Callable

@dataclass
class WalkForwardFold:
    fold_id: int
    is_start: pd.Timestamp
    is_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp
    best_params: dict
    is_metrics: dict
    oos_metrics: dict


@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold]
    is_sharpe_mean: float
    oos_sharpe_mean: float
    is_pf_mean: float
    oos_pf_mean: float
    degradation_pct: float
    param_stability_score: float  # Jaccard similarity entre top-K params
    
    def to_dataframe(self) -> pd.DataFrame: ...
    def to_dict(self) -> dict: ...


def walk_forward_with_reopt(
    data: pd.DataFrame,
    param_space: dict[str, list],
    n_folds: int = 5,
    is_window_bars: int = 252 * 2,    # 2 anos IS default
    oos_window_bars: int = 252,        # 1 ano OOS default
    embargo_bars: int = 20,
    optimizer: str = "grid",            # "grid" ou "optuna"
    n_trials_optuna: int = 100,
    metric_to_optimize: str = "sharpe_dsr",  # DSR para deflar
    n_jobs: int = 1,
) -> WalkForwardResult:
    """
    Walk-forward anchored com re-otimização em cada janela IS.
    
    Para cada fold:
        1. Define janelas IS e OOS sequenciais (com embargo entre elas)
        2. Roda otimização sobre IS
        3. Aplica params ótimos em OOS
        4. Registra ambas as métricas
    
    Param stability score:
        Jaccard similarity entre os top-3 params de cada fold consecutivo.
        Próximo de 1.0 = params estáveis = robusto.
        Próximo de 0.0 = params variam muito = overfitting.
    """
```

Implementação:
- Embargo entre IS e OOS para evitar leakage (importante quando meta-labeler é treinado).
- Otimização interna usa Deflated Sharpe Ratio (DSR) para penalizar múltiplas hipóteses.
- Logs claros: cada fold imprime IS metrics, OOS metrics, e degradação.

### E2 — Function `compute_degradation`

```python
def compute_degradation(
    is_metric: float,
    oos_metric: float,
    metric_type: str = "sharpe",
) -> dict:
    """
    Mede degradação IS→OOS de forma interpretável.
    
    Returns
    -------
    dict com:
        - absolute_degradation: oos - is
        - relative_degradation_pct: (oos - is) / is * 100
        - is_significant: bool (degradação > limiar estabelecido)
        - interpretation: str ("robusto", "moderado overfitting", "severo overfitting")
    """
```

Limiares de interpretação (documentados):
- < 20% de degradação → "robusto"
- 20-50% → "moderado overfitting"
- 50-80% → "severo overfitting"
- \> 80% → "estratégia essencialmente artefato de fitting"

### E3 — Param stability score

```python
def param_stability_score(
    folds: list[WalkForwardFold],
    top_k: int = 3,
) -> float:
    """
    Para cada par de folds consecutivos, computa Jaccard similarity 
    entre os top-K conjuntos de parâmetros (por Sharpe IS).
    
    Retorna média dos Jaccard scores.
    
    1.0 = mesmo conjunto top-K em todos os folds → params estáveis
    0.0 = top-K totalmente diferente entre folds → overfitting
    """
```

### E4 — Testes `tests/unit/test_walkforward_honest.py`

Mínimo 10 casos:

1. **Série sintética AR(1) mean-reverting**: parâmetros ótimos recuperados em todos os folds, degradação ≈ 0.
2. **Série aleatória pura**: walk-forward deve mostrar alta degradação (overfitting puro).
3. **Embargo respeitado**: garantir que OOS não contém datas dentro de IS+embargo.
4. **Anchored vs sliding**: opção `anchored=True` mantém IS_start fixo.
5. **Param space exaustivo**: grid pequeno (4 combinações) testa exaustivamente.
6. **Determinismo**: mesma seed → mesmo resultado.
7. **Edge case**: dados insuficientes para n_folds solicitado → ValueError.
8. **Stability score = 1.0** quando todos folds têm mesmo param ótimo.
9. **Stability score = 0.0** quando folds têm params disjuntos.
10. **DSR penaliza** múltiplas hipóteses: grid grande com pouca diferença real produz Sharpe DSR menor.

### E5 — Comparação com implementação anterior

Script `scripts/compare_walkforward_methods.py`:

- Roda walk-forward **antigo** (params fixos) sobre `^BVSP` com config Sprint-13.
- Roda walk-forward **honesto** (re-otim) sobre mesmo dataset, mesmo param_space.
- Produz tabela comparativa:

```
| Método | IS Sharpe mean | OOS Sharpe mean | Degradação |
|---|---|---|---|
| Antigo (params fixos) | 1.85 | 1.72 | -7% |
| Honesto (re-otim) | ? | ? | ? |
```

A diferença entre essas duas linhas é a estimativa do data dredging.

### E6 — Execução completa

Rodar walk-forward honesto sobre:
- `^BVSP` (15 anos de dados, 5 folds)
- `^GSPC` (15 anos, 5 folds)
- `VALE3.SA` (10 anos, 4 folds)

Outputs em `findings/sprint_21_data/`:
- 3 JSONs com resultados completos
- 3 PNGs com gráficos IS-vs-OOS por fold
- `walkforward_comparison.csv`

### E7 — Relatório `findings/sprint_21_walkforward_honest.md`

Estrutura obrigatória:

```markdown
# Finding Sprint 21 — Walk-Forward Honesto

## TL;DR
[Em 1-2 frases: "Degradação IS→OOS: X%. Interpretação: <robusto/overfitting>."]

## Comparação de métodos
[Tabela do E5]

## Resultados por ticker
[3 subseções, cada uma com tabela de folds + visualização]

## Param stability score
[Tabela com score por ticker]

## Interpretação e decisão
[Cenários:
 - Degradação < 20% e stability > 0.6: config atual validada. 
   Reportar Sharpe OOS honesto como número de referência.
 - Degradação 20-50%: config atual ainda usável, mas reportar 
   intervalo (IS-OOS) como faixa de incerteza.
 - Degradação > 50%: config atual está overfitted. 
   Buscar config mais robusta (menos parâmetros, mais conservadora).]

## Atualização do RELATORIO_TECNICO.md
[Substituir Sharpe reportado pelo Sharpe OOS honesto. 
Adicionar nota sobre metodologia.]
```

---

## 4. Critério de Aceitação

- [ ] Suite completa passa
- [ ] `walkforward_honest.py` tem cobertura ≥ 85%
- [ ] 3 JSONs + 3 PNGs + 1 CSV em `findings/sprint_21_data/`
- [ ] Relatório responde: "Qual o Sharpe OOS honesto?"
- [ ] Decisão explícita documentada sobre config atual (manter / ajustar / substituir)
- [ ] Se degradação > 50%, busca por config mais robusta é registrada como Sprint 21.5 ou nota no Marco do Bloco I
- [ ] `RELATORIO_TECNICO.md` atualizado com Sharpe OOS honesto

---

## 5. Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Re-otimização demora muito (grid × n_folds × tickers) | Alta | Otimizar via Optuna; cache de avaliações intermediárias |
| Degradação > 80% revela overfitting severo | Média-Alta | Esperado em alguma medida. Marco do Bloco I documenta |
| Param stability baixo mas degradação aceitável | Baixa | Manter ambas métricas no relatório; interpretação cuidadosa |
| Embargo insuficiente para meta-labeler | Média | Documentar trade-off; usar 21 bars (1 mês) como default conservador |

---

## 6. Notas para o Claude Code

- **Optuna é opcional** mas recomendado para param_space grande (> 100 combinações).
- **Paralelização**: cada fold é independente; usar `multiprocessing.Pool(n_jobs)`.
- **Caching**: avaliações de mesma combinação (param + dados) devem ser cacheadas — usar `functools.lru_cache` ou pickle de DataFrame.
- **DSR (Deflated Sharpe Ratio)**: implementação em Bailey & López de Prado (2014). Já existe no `optimizer.py`? Verificar e reutilizar.
- **Anchored vs sliding**: implementar ambos; default anchored (IS_start fixo) por convenção.
- **Param space**: começar com subset de 5-8 params críticos (não otimizar 30+ ao mesmo tempo).
- **Logging**: cada fold deve imprimir resumo em ≤ 5 linhas para console.

---

## 7. Comandos de validação

```bash
pytest tests/unit/test_walkforward_honest.py -v
python -m walkforward_honest --ticker ^BVSP --n_folds 5
python scripts/compare_walkforward_methods.py
ls findings/sprint_21_data/
cat findings/sprint_21_walkforward_honest.md | head -50
```

---

## 8. Estimativa detalhada

| Tarefa | Estimativa |
|---|---|
| E1 — walkforward_honest module | 2-3 dias |
| E2-E3 — degradation + stability score | 0.5-1 dia |
| E4 — testes (10 casos) | 1.5-2 dias |
| E5 — comparação | 0.5-1 dia |
| E6 — execução para 3 tickers (compute time) | 0.5-1 dia |
| E7 — relatório (decisão estratégica cuidadosa) | 1.5-2 dias |
| Buffer | 1 dia |
| **Total** | **7-10 dias** |
